"""
lyrics.py - time-synced lyrics, from LRCLIB.

Spotify's Web API does not expose lyrics. What the Spotify app shows comes
from a private endpoint backed by Musixmatch, which is not available to third
parties and would need a paid Musixmatch key to replicate.

LRCLIB (https://lrclib.net) is a free, key-less community database of LRC
files, matched on track / artist / album / duration. It returns plain lyrics
and, usually, synced lyrics with per-line timestamps, which is what lets the
current line highlight as the song plays.

Lookups run on a worker thread and are cached per track, so the UI can call
request() every refresh without generating traffic.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request

import paths
from applog import log

API = "https://lrclib.net/api/get"
HTTP_TIMEOUT = 8
CACHE_PATH = os.path.join(paths.DATA_DIR, "lyrics.json")
USER_AGENT = "iPhoneConnect/1.0 (personal desktop companion)"

LINE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")

_lock = threading.Lock()
_memory: dict[str, dict] = {}
_inflight: set[str] = set()


def _key(title: str, artist: str) -> str:
    return f"{(artist or '').strip().lower()}|{(title or '').strip().lower()}"


def _load_cache() -> None:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            _memory.update(json.load(handle))
    except (OSError, ValueError):
        pass


def _save_cache() -> None:
    try:
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        with _lock:
            payload = dict(list(_memory.items())[-200:])
        with open(CACHE_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        pass


_load_cache()


def parse_lrc(text: str):
    """'[01:23.45] line' -> [(83.45, 'line'), ...], sorted by time."""
    out = []
    for raw in (text or "").splitlines():
        stamps = LINE.findall(raw)
        if not stamps:
            continue
        body = LINE.sub("", raw).strip()
        for minutes, seconds in stamps:
            out.append((int(minutes) * 60 + float(seconds.replace(":", ".")),
                        body))
    return sorted(out, key=lambda pair: pair[0])


def _latin_ratio(text: str) -> float:
    """
    How much of this is Latin script.

    LRCLIB often holds the same song twice - once transliterated into Latin
    and once in the original script. /api/get returns only one match, and for
    Tamil or Hindi tracks that was usually the native script. Searching and
    ranking lets us prefer the readable one.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) < 0x250) / len(letters)


def _score(entry: dict, duration: float):
    synced = entry.get("syncedLyrics") or ""
    plain = entry.get("plainLyrics") or ""
    body = synced or plain
    if not body:
        return (-1.0, 0, 0.0)
    gap = abs((entry.get("duration") or 0) - (duration or 0))
    # Latin first, then synced, then whichever length matches the track best
    return (round(_latin_ratio(body), 1), 1 if synced else 0, -gap)


def _query(path: str, params: dict):
    url = f"https://lrclib.net/api/{path}?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch(key: str, title: str, artist: str, album: str, duration: float):
    result = {"plain": "", "synced": [], "found": False, "latin": False}
    best = None
    try:
        matches = _query("search", {"track_name": title, "artist_name": artist})
        if isinstance(matches, list) and matches:
            best = max(matches, key=lambda entry: _score(entry, duration))
    except Exception as exc:
        log(f"lyrics search failed: {exc}", "lyr", debug=True)

    if best is None:
        try:
            best = _query("get", {"track_name": title, "artist_name": artist,
                                  "album_name": album or "",
                                  "duration": int(duration or 0)})
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                log(f"lyrics lookup failed: {exc.code}", "lyr", debug=True)
        except Exception as exc:
            log(f"lyrics lookup failed: {exc}", "lyr", debug=True)

    if best:
        result["plain"] = best.get("plainLyrics") or ""
        result["synced"] = parse_lrc(best.get("syncedLyrics") or "")
        result["found"] = bool(result["plain"] or result["synced"])
        result["latin"] = _latin_ratio(
            (best.get("syncedLyrics") or "") + result["plain"]) > 0.6
        if result["found"]:
            log(f"lyrics found for {title}", "lyr", debug=True)

    with _lock:
        _memory[key] = result
        _inflight.discard(key)
    _save_cache()


def request(title: str, artist: str, album: str = "",
            duration: float = 0.0) -> dict | None:
    """
    Cached lyrics for this track, or None while a lookup is in flight.
    Never blocks.
    """
    if not title:
        return None
    key = _key(title, artist)
    with _lock:
        if key in _memory:
            return _memory[key]
        if key in _inflight:
            return None
        _inflight.add(key)
    threading.Thread(target=_fetch,
                     args=(key, title, artist, album, duration),
                     name="lyrics", daemon=True).start()
    return None


def current_index(synced, elapsed: float) -> int:
    """Which line should be highlighted at this playback position."""
    index = -1
    for position, (at, _text) in enumerate(synced):
        if at <= elapsed + 0.25:
            index = position
        else:
            break
    return index
