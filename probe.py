"""
probe.py - enumerate everything the iPhone exposes over BLE.

Read-only reconnaissance. Dumps the full GATT database (services,
characteristics, properties, descriptors, and the value of anything
readable), then optionally sits and logs raw ANCS + AMS traffic so we can see
what the phone actually volunteers during a real call or while music plays.

    python probe.py                       # dump GATT and exit
    python probe.py --listen 120          # dump, then log traffic for 2 min
    python probe.py --listen 120 --no-read
    python probe.py AA:BB:CC:DD:EE:FF --listen 60

Everything is mirrored to probe-<timestamp>.txt so the output can be shared.

Quit Phone Link first - it holds the link and starves this client.
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import time
from datetime import datetime

from bleak import BleakClient

import ancs
import app_ble

BASE = os.path.dirname(os.path.abspath(__file__))

# --- Apple Media Service (unexplored so far) ---------------------------------
AMS_SERVICE          = "89d3502b-0f36-433a-8ef4-c502ad55f8dc"
AMS_REMOTE_COMMAND   = "9b3c81d8-57b1-4a8a-b8df-0e56f7ca51c2"  # write, notify
AMS_ENTITY_UPDATE    = "2f7cabce-808d-411f-9a0c-bb92ba96c102"  # write, notify
AMS_ENTITY_ATTRIBUTE = "c6b2f38c-23ab-46d8-a6ab-a3a870bbd5d7"  # read, write

AMS_ENTITIES = {0: "Player", 1: "Queue", 2: "Track"}
AMS_ATTRS = {
    0: {0: "Name", 1: "PlaybackInfo", 2: "Volume"},
    1: {0: "Index", 1: "Count", 2: "ShuffleMode", 3: "RepeatMode"},
    2: {0: "Artist", 1: "Album", 2: "Title", 3: "Duration"},
}
# What we ask AMS to push at us
AMS_SUBSCRIPTIONS = [(0, [0, 1, 2]), (1, [0, 1, 2, 3]), (2, [0, 1, 2, 3])]

KNOWN_UUIDS = {
    ancs.ANCS_SERVICE:        "ANCS (Apple Notification Center Service)",
    ancs.NOTIFICATION_SOURCE: "  ANCS Notification Source",
    ancs.CONTROL_POINT:       "  ANCS Control Point",
    ancs.DATA_SOURCE:         "  ANCS Data Source",
    AMS_SERVICE:              "AMS (Apple Media Service)",
    AMS_REMOTE_COMMAND:       "  AMS Remote Command",
    AMS_ENTITY_UPDATE:        "  AMS Entity Update",
    AMS_ENTITY_ATTRIBUTE:     "  AMS Entity Attribute",
    "7905f431-b5ce-4e99-a40f-4b1e122d00d0": "ANCS",
    "d0611e78-bbb4-4591-a5f8-487910ae4366": "Apple Continuity / ANCS pairing",
    "9fa480e0-4967-4542-9390-d343dc5d04ae": "Apple Continuity (unknown)",
    "0000180a-0000-1000-8000-00805f9b34fb": "Device Information Service",
    "0000180f-0000-1000-8000-00805f9b34fb": "Battery Service",
    "00001805-0000-1000-8000-00805f9b34fb": "Current Time Service",
    "00001801-0000-1000-8000-00805f9b34fb": "Generic Attribute",
    "00001800-0000-1000-8000-00805f9b34fb": "Generic Access",
}

# ANCS notification attributes worth asking for while probing
PROBE_ATTRS = {
    0: "AppIdentifier", 1: "Title", 2: "Subtitle", 3: "Message",
    4: "MessageSize", 5: "Date", 6: "PositiveActionLabel",
    7: "NegativeActionLabel",
}
EVENT_NAMES = {0: "ADDED", 1: "MODIFIED", 2: "REMOVED"}


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #

class _Tee:
    def __init__(self, path):
        self.file = open(path, "w", encoding="utf-8", buffering=1)
        self.term = sys.__stdout__

    def write(self, text):
        self.term.write(text)
        self.file.write(text)

    def flush(self):
        self.term.flush()
        self.file.flush()


def stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def printable(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    return "".join(c if c.isprintable() else "." for c in text)


# --------------------------------------------------------------------------- #
# GATT enumeration
# --------------------------------------------------------------------------- #

async def dump_gatt(client: BleakClient, do_read: bool) -> dict:
    print("\n" + "=" * 74)
    print("GATT DATABASE")
    print("=" * 74)

    found = {}
    for service in client.services:
        label = KNOWN_UUIDS.get(service.uuid.lower(), service.description or "")
        print(f"\nservice {service.uuid}  {label}")
        found[service.uuid.lower()] = service

        for char in service.characteristics:
            props = ",".join(char.properties)
            clabel = KNOWN_UUIDS.get(char.uuid.lower(), char.description or "")
            print(f"  char  {char.uuid}  [{props}]  {clabel}")

            if do_read and "read" in char.properties:
                try:
                    value = await asyncio.wait_for(
                        client.read_gatt_char(char), timeout=4
                    )
                    print(f"          value: {hexdump(value)}")
                    if any(32 <= b < 127 for b in value):
                        print(f"          text : {printable(value)!r}")
                except Exception as exc:
                    print(f"          (read failed: {type(exc).__name__}: {exc})")

            for desc in char.descriptors:
                print(f"    desc  {desc.uuid}  handle={desc.handle}")
                if do_read:
                    try:
                        value = await asyncio.wait_for(
                            client.read_gatt_descriptor(desc.handle), timeout=4
                        )
                        print(f"          value: {hexdump(value)}")
                    except Exception as exc:
                        print(f"          (read failed: {type(exc).__name__})")

    print("\n" + "-" * 74)
    for uuid, name in (
        (ancs.ANCS_SERVICE, "ANCS"),
        (AMS_SERVICE, "AMS"),
        ("0000180f-0000-1000-8000-00805f9b34fb", "Battery Service"),
        ("0000180a-0000-1000-8000-00805f9b34fb", "Device Information"),
        ("00001805-0000-1000-8000-00805f9b34fb", "Current Time"),
    ):
        print(f"{name:20} {'PRESENT' if uuid.lower() in found else 'absent'}")
    print("-" * 74)
    return found


# --------------------------------------------------------------------------- #
# ANCS listening (raw, unfiltered - unlike app_ble)
# --------------------------------------------------------------------------- #

def build_probe_request(uid: int, flags: int) -> bytes:
    """Delegate to ancs.py now that the attribute-length rules are correct."""
    payload, _ids = ancs.build_get_attributes(uid, flags)
    return payload


class RawDataSource:
    """Generic Data Source walker - prints whatever attributes turn up."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf += data
        if len(self.buf) < 5:
            return
        uid = struct.unpack("<I", self.buf[1:5])[0]
        i, out = 5, []
        while i + 3 <= len(self.buf):
            attr_id = self.buf[i]
            length = struct.unpack("<H", self.buf[i + 1:i + 3])[0]
            if i + 3 + length > len(self.buf):
                break                                    # wait for more
            value = self.buf[i + 3:i + 3 + length].decode("utf-8", "replace")
            out.append((attr_id, value))
            i += 3 + length
        if out:
            print(f"[{stamp()}] DS  uid={uid}")
            for attr_id, value in out:
                name = PROBE_ATTRS.get(attr_id, f"attr{attr_id}")
                print(f"           {name:20} {value!r}")
        self.buf = self.buf[i:] if i < len(self.buf) else bytearray()


async def listen(client: BleakClient, seconds: int, found: dict):
    loop = asyncio.get_running_loop()
    print("\n" + "=" * 74)
    print(f"LISTENING for {seconds}s - make a call, play music, lock the phone")
    print("=" * 74)

    assembler = RawDataSource()

    async def request(uid, flags):
        try:
            await client.write_gatt_char(
                ancs.CONTROL_POINT, build_probe_request(uid, flags), response=True
            )
        except Exception as exc:
            print(f"           (attribute request failed: {exc})")

    def on_notification_source(_sender, data):
        raw = bytes(data)
        info = ancs.parse_notification_source(raw)
        print(f"[{stamp()}] NS  {hexdump(raw)}")
        if not info:
            return
        bits = []
        if info["flags"] & ancs.FLAG_SILENT:
            bits.append("silent")
        if info["flags"] & ancs.FLAG_IMPORTANT:
            bits.append("important")
        if info["flags"] & ancs.FLAG_PRE_EXISTING:
            bits.append("pre-existing")
        if info["positive"]:
            bits.append("+action")
        if info["negative"]:
            bits.append("-action")
        print(f"           event={EVENT_NAMES.get(info['event_id'])} "
              f"uid={info['uid']} category={info['category_name']} "
              f"count={info['category_count']} flags={'|'.join(bits) or 'none'}")
        if info["event_id"] != ancs.EVENT_REMOVED:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(request(info["uid"], info["flags"]))
            )

    def on_data_source(_sender, data):
        assembler.feed(bytes(data))

    def on_ams_entity(_sender, data):
        raw = bytes(data)
        if len(raw) < 3:
            print(f"[{stamp()}] AMS {hexdump(raw)}")
            return
        entity, attr, flags = raw[0], raw[1], raw[2]
        value = raw[3:].decode("utf-8", "replace")
        ename = AMS_ENTITIES.get(entity, f"entity{entity}")
        aname = AMS_ATTRS.get(entity, {}).get(attr, f"attr{attr}")
        print(f"[{stamp()}] AMS {ename}.{aname} = {value!r} (flags={flags:#04x})")

    def on_ams_command(_sender, data):
        print(f"[{stamp()}] AMS available commands: {hexdump(bytes(data))}")

    await client.start_notify(ancs.DATA_SOURCE, on_data_source)
    await client.start_notify(ancs.NOTIFICATION_SOURCE, on_notification_source)
    print("subscribed: ANCS")

    if AMS_SERVICE.lower() in found:
        try:
            await client.start_notify(AMS_ENTITY_UPDATE, on_ams_entity)
            await client.start_notify(AMS_REMOTE_COMMAND, on_ams_command)
            for entity, attrs in AMS_SUBSCRIPTIONS:
                await client.write_gatt_char(
                    AMS_ENTITY_UPDATE, bytes([entity] + attrs), response=True
                )
            print("subscribed: AMS (player, queue, track)")
        except Exception as exc:
            print(f"AMS subscribe failed: {type(exc).__name__}: {exc}")
    else:
        print("AMS not present on this device")

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and client.is_connected:
        await asyncio.sleep(0.5)
    if not client.is_connected:
        print(f"\n[{stamp()}] link dropped")


# --------------------------------------------------------------------------- #

async def main():
    args = [a for a in sys.argv[1:]]
    do_read = "--no-read" not in args
    seconds = 0
    if "--listen" in args:
        index = args.index("--listen")
        seconds = int(args[index + 1]) if len(args) > index + 1 else 120
        del args[index:index + 2]
    args = [a for a in args if not a.startswith("--")]

    address = (args[0] if args else None) or app_ble.load_address()
    if not address:
        address = await app_ble.scan_for_apple()
    if not address:
        print("No Apple device found.")
        return

    log_path = os.path.join(
        BASE, "probe-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".txt"
    )
    sys.stdout = _Tee(log_path)

    print(f"probe.py  {datetime.now().isoformat(timespec='seconds')}")
    print(f"address: {address}")
    print(f"log:     {log_path}")

    async with BleakClient(address) as client:
        print("connected")
        found = await dump_gatt(client, do_read)
        if seconds:
            await listen(client, seconds, found)

    print("\ndone")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
