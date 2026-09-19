"""
spotify.py - optional Spotify Web API link, for the data AMS cannot give us.

AMS provides title, artist, album, duration, elapsed and volume, but no
artwork and no absolute volume control. Spotify's Web API provides both, so
when it is connected we use it for album art and for the volume slider, and
keep AMS as the always-available fallback.

Auth is Authorization Code with PKCE: no client secret, so nothing sensitive
sits on disk. You supply a Client ID from your own Spotify app; we open the
browser, catch the redirect on 127.0.0.1, and store only the refresh token.

    Create an app: https://developer.spotify.com/dashboard
    Redirect URI:  http://127.0.0.1:8899/callback

Absolute volume needs Spotify Premium; the API returns 403 otherwise, which
we surface as a log line rather than an error dialog.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import paths
from applog import log
from store import MEDIA

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

REDIRECT_PORT = 8899
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-read-currently-playing")

CONFIG_PATH = os.path.join(paths.DATA_DIR, "spotify.json")
ART_DIR = os.path.join(paths.DATA_DIR, "art")
POLL_SECONDS = 4.0
HTTP_TIMEOUT = 8


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class _Callback(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):                                    # noqa: N802
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _Callback.code = (params.get("code") or [None])[0]
        _Callback.error = (params.get("error") or [None])[0]
        body = ("<html><body style='background:#0C1016;color:#EAEDF2;"
                "font-family:Segoe UI,sans-serif;text-align:center;"
                "padding-top:80px'><h2>"
                + ("Spotify connected" if _Callback.code else "Spotify refused")
                + "</h2><p>You can close this tab and go back to iPhone "
                  "Connect.</p></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *_args):                       # keep stdout clean
        return


class Spotify:
    def __init__(self):
        self._lock = threading.Lock()
        self.client_id = ""
        self.refresh_token = ""
        self.access_token = ""
        self.expires_at = 0.0
        self.status = "Not connected"
        self.premium = True
        self._art_cache: dict[str, str] = {}
        self._polling = False
        self._load()

    # -- config ----------------------------------------------------------- #

    def _load(self) -> None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.client_id = data.get("client_id", "")
            self.refresh_token = data.get("refresh_token", "")
        except (OSError, ValueError):
            pass
        if self.refresh_token:
            self.status = "Connected"

    def _save(self) -> None:
        try:
            os.makedirs(paths.DATA_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump({"client_id": self.client_id,
                           "refresh_token": self.refresh_token},
                          handle, indent=2)
        except OSError as exc:
            log(f"could not save Spotify config: {exc}", "spot")

    @property
    def connected(self) -> bool:
        return bool(self.client_id and self.refresh_token)

    def set_client_id(self, client_id: str) -> None:
        self.client_id = (client_id or "").strip()
        self._save()

    def disconnect(self) -> None:
        self.refresh_token = ""
        self.access_token = ""
        self.status = "Not connected"
        self._save()
        MEDIA.update(art_path="", source="ams")
        log("Spotify disconnected", "spot")

    # -- auth ------------------------------------------------------------- #

    def authorise(self, on_done=None) -> None:
        """Runs the browser flow on a worker thread."""
        if not self.client_id:
            self.status = "Client ID required"
            if on_done:
                on_done(False, self.status)
            return
        threading.Thread(target=self._authorise, args=(on_done,),
                         name="spotify-auth", daemon=True).start()

    def _authorise(self, on_done) -> None:
        verifier = _b64(secrets.token_bytes(64))
        challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": SCOPES,
        })

        _Callback.code = _Callback.error = None
        try:
            server = HTTPServer(("127.0.0.1", REDIRECT_PORT), _Callback)
        except OSError as exc:
            self.status = f"Port {REDIRECT_PORT} busy"
            log(f"Spotify auth failed: {exc}", "spot")
            if on_done:
                on_done(False, self.status)
            return

        self.status = "Waiting for browser\u2026"
        webbrowser.open(f"{AUTH_URL}?{query}")
        server.timeout = 120
        server.handle_request()
        server.server_close()

        if not _Callback.code:
            self.status = f"Refused ({_Callback.error or 'no code'})"
            log(f"Spotify auth refused: {_Callback.error}", "spot")
            if on_done:
                on_done(False, self.status)
            return

        payload = {
            "grant_type": "authorization_code",
            "code": _Callback.code,
            "redirect_uri": REDIRECT_URI,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        data = self._token_request(payload)
        if not data:
            self.status = "Token exchange failed"
            if on_done:
                on_done(False, self.status)
            return

        self.refresh_token = data.get("refresh_token", "")
        self._apply_token(data)
        self.status = "Connected"
        self._save()
        log("Spotify connected", "spot")
        if on_done:
            on_done(True, self.status)

    def _token_request(self, payload: dict):
        try:
            request = urllib.request.Request(
                TOKEN_URL, data=urllib.parse.urlencode(payload).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            log(f"Spotify token request failed: {exc}", "spot")
            return None

    def _apply_token(self, data: dict) -> None:
        with self._lock:
            self.access_token = data.get("access_token", "")
            self.expires_at = time.time() + data.get("expires_in", 3600) - 60

    def _ensure_token(self) -> bool:
        with self._lock:
            fresh = self.access_token and time.time() < self.expires_at
        if fresh:
            return True
        if not self.connected:
            return False
        data = self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
        })
        if not data or "access_token" not in data:
            self.status = "Re-authorisation needed"
            return False
        # Spotify may hand back a rotated refresh token
        if data.get("refresh_token"):
            self.refresh_token = data["refresh_token"]
            self._save()
        self._apply_token(data)
        self.status = "Connected"
        return True

    # -- requests --------------------------------------------------------- #

    def _call(self, method: str, path: str, params=None):
        if not self._ensure_token():
            return None
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method=method)
        request.add_header("Authorization", f"Bearer {self.access_token}")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
                if resp.status == 204:
                    return {}
                body = resp.read()
                return json.loads(body.decode("utf-8")) if body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                self.premium = False
                log("Spotify refused: Premium required for that control",
                    "spot")
            elif exc.code == 401:
                with self._lock:
                    self.access_token = ""
            elif exc.code != 404:
                log(f"Spotify {path} failed: {exc.code}", "spot", debug=True)
            return None
        except Exception as exc:
            log(f"Spotify {path} failed: {exc}", "spot", debug=True)
            return None

    # -- playback --------------------------------------------------------- #

    def poll_once(self) -> None:
        data = self._call("GET", "/me/player")
        if not data or not data.get("item"):
            return
        item = data["item"]
        album = item.get("album") or {}
        images = album.get("images") or []
        art_url = images[0]["url"] if images else ""
        device = data.get("device") or {}

        MEDIA.update(
            player=(device.get("name") or "Spotify"),
            title=item.get("name", ""),
            artist=", ".join(a.get("name", "")
                             for a in item.get("artists", [])),
            album=album.get("name", ""),
            duration=(item.get("duration_ms") or 0) / 1000,
            source="spotify",
            art_path=self._artwork(album.get("id", ""), art_url),
        )
        MEDIA.set_playback(1 if data.get("is_playing") else 0,
                           1.0 if data.get("is_playing") else 0.0,
                           (data.get("progress_ms") or 0) / 1000)
        volume = device.get("volume_percent")
        if volume is not None:
            MEDIA.update(volume=volume / 100)

    def _artwork(self, album_id: str, url: str) -> str:
        """Download album art once per album and hand back a local path."""
        if not url:
            return ""
        key = album_id or url
        if key in self._art_cache:
            return self._art_cache[key]
        safe = "".join(c for c in key if c.isalnum())[:40] or "art"
        path = os.path.join(ART_DIR, safe + ".jpg")
        if not os.path.exists(path):
            try:
                os.makedirs(ART_DIR, exist_ok=True)
                request = urllib.request.Request(
                    url, headers={"User-Agent": "iPhoneConnect/1.0"})
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as r:
                    payload = r.read()
                with open(path, "wb") as handle:
                    handle.write(payload)
            except Exception as exc:
                log(f"artwork download failed: {exc}", "spot", debug=True)
                return ""
        self._art_cache[key] = path
        return path

    def command(self, name: str) -> bool:
        """play | pause | next | previous"""
        routes = {
            "play": ("PUT", "/me/player/play"),
            "pause": ("PUT", "/me/player/pause"),
            "next": ("POST", "/me/player/next"),
            "previous": ("POST", "/me/player/previous"),
        }
        route = routes.get(name)
        if route is None:
            return False
        return self._call(*route) is not None

    def set_volume(self, percent: int) -> bool:
        """Absolute volume - the thing AMS cannot do."""
        percent = max(0, min(100, int(percent)))
        return self._call("PUT", "/me/player/volume",
                          {"volume_percent": percent}) is not None

    # -- polling ---------------------------------------------------------- #

    def start(self) -> None:
        if self._polling:
            return
        self._polling = True
        threading.Thread(target=self._loop, name="spotify-poll",
                         daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                if self.connected:
                    self.poll_once()
            except Exception as exc:
                log(f"Spotify poll error: {exc}", "spot", debug=True)
            time.sleep(POLL_SECONDS)


CLIENT = Spotify()
