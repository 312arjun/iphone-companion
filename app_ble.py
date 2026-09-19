"""
app_ble.py - the BLE side: connect, subscribe, stay connected.

Strategy (unchanged, this is the combination that works):
  - We do NOT call pair(). Mid-session pairing makes iOS re-encrypt and drop
    the link. This relies on a PERSISTENT bond made once in Windows Settings.
  - Zero settle delay: subscribe the instant we connect, to land inside the
    ~1-second window iOS gives us.
  - Connect by a cached address to skip scan latency.

Subscribes to ANCS (notifications), AMS (now playing + control) and the
standard Battery Service, and reads Device Information once per session.

One-time setup:
  1. iPhone: Settings > Bluetooth > (i) next to the PC > Forget This Device.
  2. Windows: Bluetooth & devices > remove any iPhone entry.
  3. Windows: Add device > Bluetooth > pick the iPhone > confirm on BOTH.
  4. Disable Phone Link's autostart - it holds the link and starves this app.

Run:  python app_ble.py [address]      (or pythonw qt_main.py for the GUI)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from bleak import BleakClient, BleakScanner

import ams
import ancs
import calls
import icons
import paths
from applog import log
from notify import dismiss_notification, show_notification
from status import STATUS
from store import DEVICE

APPLE_COMPANY_ID = 0x004C
SCAN_SECONDS = 5
RECONNECT_DELAY = 2.0
MAX_RECONNECT_DELAY = 30.0
MAX_CONSECUTIVE_FAILS = 8        # 0 = retry forever (what the GUI uses)
RESCAN_AFTER_FAILS = 3           # a cached address goes stale when iOS rotates

# Standard Bluetooth SIG characteristics that iOS really does expose.
BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

# Fallback action labels, used only when iOS sends none of its own.
ACTION_LABELS = {
    1:  ("Answer", "Decline"),
    2:  ("Call back", "Clear"),
    3:  ("Listen", "Clear"),
    12: (None, "End Call"),
}
DEFAULT_LABELS = ("Open", "Clear")
CALL_CATEGORIES = (1, 2, 3, 12)
CALL_STYLE_CATEGORIES = (1, 12)
MAX_TRACKED_UIDS = 64

CONFIG = paths.CONFIG_PATH
LOOP = None      # live event loop, so the GUI can reach the connection
CLIENT = None    # live BleakClient, ditto


# --------------------------------------------------------------------------- #
# address cache
# --------------------------------------------------------------------------- #

def load_address():
    try:
        with open(CONFIG, "r", encoding="utf-8") as handle:
            return json.load(handle).get("address")
    except (OSError, ValueError):
        return None


def save_address(address):
    try:
        with open(CONFIG, "w", encoding="utf-8") as handle:
            json.dump({"address": address}, handle, indent=2)
    except OSError as exc:
        log(f"could not save config: {exc}", "ble")


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

def _looks_like_apple(adv) -> bool:
    try:
        return APPLE_COMPANY_ID in (adv.manufacturer_data or {})
    except Exception:
        return False


async def scan_for_apple():
    log("scanning for iPhone", "ble")
    STATUS.set_state("Scanning", connected=False)
    DEVICE.update(state="Scanning", connected=False)
    found = await BleakScanner.discover(timeout=SCAN_SECONDS, return_adv=True)
    best_address, best_rssi = None, -999
    for address, (_device, adv) in found.items():
        if not _looks_like_apple(adv):
            continue
        rssi = getattr(adv, "rssi", None) or -999
        log(f"saw Apple device {address} at {rssi} dBm", "ble", debug=True)
        if rssi > best_rssi:
            best_address, best_rssi = address, rssi
    return best_address


async def scan_all():
    """
    Every Apple device in range, strongest first.

    Used by Settings > Devices to pick a phone. Returns dicts rather than
    bleak objects so the result can cross the thread boundary into Qt safely.
    """
    log("scanning for devices", "ble")
    found = await BleakScanner.discover(timeout=SCAN_SECONDS, return_adv=True)
    out = []
    for address, (device, adv) in found.items():
        if not _looks_like_apple(adv):
            continue
        out.append({
            "address": address,
            "name": (device.name or adv.local_name or "Apple device"),
            "rssi": getattr(adv, "rssi", None) or -999,
        })
    out.sort(key=lambda entry: -entry["rssi"])
    log(f"scan found {len(out)} Apple device(s)", "ble")
    return out


# --------------------------------------------------------------------------- #
# calls
# --------------------------------------------------------------------------- #

def _report_call(call) -> None:
    """A call reached a terminal state: log it and show a summary."""
    who = call.label()
    if call.state == "missed":
        log(f"missed call from {who}", "call")
        return
    log(f"{call.direction} call with {who} lasted {call.duration_text}", "call")
    STATUS.set_call_summary(f"{who} \u00b7 {call.duration_text}")
    show_notification(call.app or "Phone", who,
                      f"Call ended \u00b7 {call.duration_text}",
                      call.bundle_id or "com.apple.mobilephone",
                      hold_ms=6000)


# --------------------------------------------------------------------------- #
# ANCS plumbing
# --------------------------------------------------------------------------- #

def make_handlers(client, loop):
    assembler = ancs.DataSourceAssembler()
    live: dict[int, dict] = {}       # uid -> Notification Source info

    async def fetch_attributes(uid, flags):
        payload, attr_ids = ancs.build_get_attributes(uid, flags)
        assembler.expect(uid, attr_ids)
        try:
            await client.write_gatt_char(ancs.CONTROL_POINT, payload,
                                         response=True)
        except Exception as exc:
            # 0xA2 just means the notification vanished before we asked
            log(f"attribute request failed: {ancs.error_name(exc)}", "ancs",
                debug=True)

    async def perform_action(uid, action_id, label):
        try:
            await client.write_gatt_char(
                ancs.CONTROL_POINT, ancs.build_perform_action(uid, action_id),
                response=True)
            log(f"{label} sent", "ancs")
        except Exception as exc:
            log(f"{label} failed: {ancs.error_name(exc)}", "ancs")

    def action_callback(uid, action_id, label):
        """Runs on the GUI thread, so hand the write back to the BLE loop."""
        def fire():
            asyncio.run_coroutine_threadsafe(
                perform_action(uid, action_id, label), loop)
        return fire

    def build_actions(uid, info, result):
        """
        Prefer the labels iOS sent - already localised, and more accurate than
        guessing ("Dial" for a missed call, "End Call" for an active one).
        """
        fallback = ACTION_LABELS.get(info.get("category"), DEFAULT_LABELS)
        positive = result.get("positive_label") or fallback[0]
        negative = result.get("negative_label") or fallback[1]
        if info.get("category") == 12:
            positive = None          # already on the call

        actions = []
        if info.get("positive") and positive:
            actions.append((positive,
                            action_callback(uid, ancs.ACTION_POSITIVE, positive),
                            "positive"))
        if info.get("negative") and negative:
            actions.append((negative,
                            action_callback(uid, ancs.ACTION_NEGATIVE, negative),
                            "negative"))
        return actions

    def on_notification_source(_sender, data):
        info = ancs.parse_notification_source(bytes(data))
        if not info:
            return
        uid = info["uid"]
        DEVICE.touch()

        # Runs for every event including REMOVED - that is where duration
        # comes from, since ANCS has no duration field.
        finished = calls.TRACKER.on_notification(info)
        if finished is not None:
            _report_call(finished)

        if info["event_id"] == ancs.EVENT_REMOVED:
            live.pop(uid, None)
            dismiss_notification(uid)
            return

        if info["flags"] & ancs.FLAG_PRE_EXISTING or info["silent"]:
            return

        # An Active Call replaces the ringing banner: pull that one first so
        # the stack does not end up with both.
        if info.get("category") == 12:
            for old_uid, old in list(live.items()):
                if old.get("category") == 1:
                    dismiss_notification(old_uid)
                    live.pop(old_uid, None)

        live[uid] = info
        while len(live) > MAX_TRACKED_UIDS:
            live.pop(next(iter(live)))

        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(fetch_attributes(uid, info["flags"])))

    def on_data_source(_sender, data):
        result = assembler.feed(bytes(data))
        if not result:
            return
        uid = result["uid"]
        info = live.get(uid, {})
        bundle_id = result["app_id"]
        app_name = ancs.friendly_app_name(bundle_id)
        category = info.get("category")

        calls.TRACKER.on_details(uid, app_name, bundle_id, result["title"],
                                 result["subtitle"])

        body = result["message"] or result["subtitle"]
        category = info.get("category")
        title = result["title"]
        if category == 12:
            style = "active_call"        # taller banner with the control row
        elif category == 1:
            style = "call"
        else:
            style = None

        if style:
            body = ""                # the banner shows the live duration here
        elif category in (2, 3):
            # Missed call / voicemail read better the way iOS shows them:
            # the event is the headline, the caller is the detail.
            title = result["message"] or info.get("category_name", "")
            body = f"from {result['title']}" if result["title"] else ""
        elif not body and category in CALL_CATEGORIES:
            body = info.get("category_name", "")

        show_notification(app_name, title, body, bundle_id,
                          actions=build_actions(uid, info, result), key=uid,
                          style=style,
                          category=info.get("category_name", ""))

    return on_notification_source, on_data_source


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #

async def _read_text(client, uuid) -> str:
    try:
        value = await client.read_gatt_char(uuid)
        return value.decode("utf-8", "replace").strip()
    except Exception:
        return ""


async def _setup_extras(client, address) -> None:
    """Battery, device info and media. None of these may break the session."""
    DEVICE.update(address=address)

    name = await _read_text(client, DEVICE_NAME)
    model = await _read_text(client, MODEL_NUMBER)
    maker = await _read_text(client, MANUFACTURER)
    DEVICE.update(name=name or None, model=model or None,
                  manufacturer=maker or None)
    if name:
        log(f"{name} ({model})", "ble")

    try:
        value = await client.read_gatt_char(BATTERY_LEVEL)
        DEVICE.update(battery=value[0])
        log(f"battery {value[0]}%", "ble")

        def on_battery(_sender, data):
            if data:
                DEVICE.update(battery=data[0])
                log(f"battery {data[0]}%", "ble", debug=True)

        await client.start_notify(BATTERY_LEVEL, on_battery)
    except Exception as exc:
        log(f"battery unavailable: {exc}", "ble", debug=True)

    await ams.subscribe(client)


async def connect_and_listen(address: str) -> None:
    global CLIENT
    loop = asyncio.get_running_loop()
    dropped = asyncio.Event()

    def on_disconnect(_client):
        log("link dropped", "ble")
        STATUS.set_state("Link dropped", connected=False)
        DEVICE.update(connected=False, state="Reconnecting")
        loop.call_soon_threadsafe(dropped.set)

    log(f"connecting to {address}", "ble")
    STATUS.set_state("Connecting", connected=False)
    DEVICE.update(state="Connecting", connected=False)

    async with BleakClient(address, disconnected_callback=on_disconnect) as client:
        CLIENT = client

        # NO pair(), NO sleep. Race straight to the subscription.
        ns_handler, ds_handler = make_handlers(client, loop)
        await client.start_notify(ancs.DATA_SOURCE, ds_handler)
        await client.start_notify(ancs.NOTIFICATION_SOURCE, ns_handler)

        log("connected, listening for notifications", "ble")
        STATUS.address = address
        STATUS.set_state("Listening", connected=True)
        DEVICE.update(connected=True, state="Connected")

        await _setup_extras(client, address)

        try:
            await dropped.wait()
        finally:
            CLIENT = None


async def run(address: str | None = None, max_fails: int = MAX_CONSECUTIVE_FAILS):
    """Connect, listen, reconnect. Runs until the loop is stopped."""
    global LOOP
    LOOP = asyncio.get_running_loop()

    icons.prefetch(ancs.APP_NAMES.keys())

    address = address or load_address() or await scan_for_apple()
    if not address:
        log("no iPhone found - keep the Bluetooth screen open and retry", "ble")
        STATUS.set_state("No iPhone found", connected=False)
        DEVICE.update(state="No iPhone found")
        return
    save_address(address)

    fails = 0
    while True:
        try:
            await connect_and_listen(address)
            fails = 0
        except Exception as exc:
            fails += 1
            log(f"connection attempt {fails} failed: {exc}", "ble")
            STATUS.set_state(f"Reconnecting ({fails})", connected=False)
            DEVICE.update(connected=False, state="Reconnecting")
            if fails % RESCAN_AFTER_FAILS == 0:
                found = await scan_for_apple()
                if found and found != address:
                    log(f"address changed to {found}", "ble")
                    address = found
                    save_address(address)

        if max_fails and fails >= max_fails:
            log(f"giving up after {fails} failures - check that Phone Link is "
                "closed and the bond still exists", "ble")
            STATUS.set_state("Gave up", connected=False)
            DEVICE.update(state="Disconnected")
            return

        delay = min(RECONNECT_DELAY * max(1, fails), MAX_RECONNECT_DELAY)
        await asyncio.sleep(delay)


def drop_link() -> bool:
    """Force a reconnect from another thread."""
    if LOOP and CLIENT:
        asyncio.run_coroutine_threadsafe(CLIENT.disconnect(), LOOP)
        return True
    return False


if __name__ == "__main__":
    try:
        asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else None))
    except KeyboardInterrupt:
        log("stopped", "app")
        sys.exit(0)
