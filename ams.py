"""
ams.py - Apple Media Service: now playing, and remote control.

Confirmed working against iPhone16,1 from probe logs. The phone pushes:

    Player.Name          'Spotify'
    Player.PlaybackInfo  '1,1.0,174.717'     state,rate,elapsed
    Player.Volume        '0.5035011'
    Track.Title          'Hey Minnale'
    Track.Artist / Album / Duration

PlaybackInfo state: 0 paused, 1 playing, 2 rewinding, 3 fast-forwarding.

The Remote Command characteristic notifies once with the list of commands the
current player supports - Spotify reported play, pause, toggle, next, prev,
volume up/down, skip fwd/back, but not shuffle/repeat/like.
"""

from __future__ import annotations

import asyncio

from applog import log
from store import MEDIA

SERVICE          = "89d3502b-0f36-433a-8ef4-c502ad55f8dc"
REMOTE_COMMAND   = "9b3c81d8-57b1-4a8a-b8df-0e56f7ca51c2"   # write, notify
ENTITY_UPDATE    = "2f7cabce-808d-411f-9a0c-bb92ba96c102"   # write, notify
ENTITY_ATTRIBUTE = "c6b2f38c-23ab-46d8-a6ab-a3a870bbd5d7"   # read, write

ENTITY_PLAYER, ENTITY_QUEUE, ENTITY_TRACK = 0, 1, 2

# Entity -> attribute id -> our store field
FIELDS = {
    ENTITY_PLAYER: {0: "player", 1: "_playback", 2: "_volume"},
    ENTITY_QUEUE:  {2: "shuffle", 3: "repeat"},
    ENTITY_TRACK:  {0: "artist", 1: "album", 2: "title", 3: "_duration"},
}

# What we ask the phone to push at us
SUBSCRIPTIONS = [
    (ENTITY_PLAYER, [0, 1, 2]),
    (ENTITY_QUEUE,  [0, 1, 2, 3]),
    (ENTITY_TRACK,  [0, 1, 2, 3]),
]

CMD_PLAY = 0
CMD_PAUSE = 1
CMD_TOGGLE = 2
CMD_NEXT = 3
CMD_PREVIOUS = 4
CMD_VOLUME_UP = 5
CMD_VOLUME_DOWN = 6
CMD_ADVANCE_REPEAT = 7
CMD_ADVANCE_SHUFFLE = 8
CMD_SKIP_FORWARD = 9
CMD_SKIP_BACKWARD = 10
CMD_LIKE = 11
CMD_DISLIKE = 12
CMD_BOOKMARK = 13

CMD_NAMES = {
    CMD_PLAY: "play", CMD_PAUSE: "pause", CMD_TOGGLE: "toggle",
    CMD_NEXT: "next", CMD_PREVIOUS: "previous",
    CMD_VOLUME_UP: "volume up", CMD_VOLUME_DOWN: "volume down",
    CMD_ADVANCE_REPEAT: "repeat", CMD_ADVANCE_SHUFFLE: "shuffle",
    CMD_SKIP_FORWARD: "skip forward", CMD_SKIP_BACKWARD: "skip back",
    CMD_LIKE: "like", CMD_DISLIKE: "dislike", CMD_BOOKMARK: "bookmark",
}

# Commands the current player actually accepts, from the notify on connect
AVAILABLE: set[int] = set()


def _float(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def handle_entity_update(data: bytes) -> None:
    """EntityID(1) | AttributeID(1) | Flags(1) | Value(utf-8)."""
    if len(data) < 3:
        return
    entity, attr = data[0], data[1]
    value = data[3:].decode("utf-8", "replace")
    field = FIELDS.get(entity, {}).get(attr)
    if field is None:
        return

    if field == "_playback":
        parts = value.split(",")
        if len(parts) >= 3:
            MEDIA.set_playback(int(_float(parts[0])), _float(parts[1]),
                               _float(parts[2]))
    elif field == "_volume":
        MEDIA.update(volume=_float(value))
    elif field == "_duration":
        MEDIA.update(duration=_float(value))
    else:
        MEDIA.update(**{field: value})


def handle_remote_command(data: bytes) -> None:
    AVAILABLE.clear()
    AVAILABLE.update(data)
    names = ", ".join(CMD_NAMES.get(c, str(c)) for c in sorted(AVAILABLE))
    log(f"media controls: {names}", "ams", debug=True)


async def subscribe(client) -> bool:
    """Wire up notifications and ask for everything. Never fatal."""
    try:
        await client.start_notify(
            ENTITY_UPDATE, lambda _s, d: handle_entity_update(bytes(d))
        )
        await client.start_notify(
            REMOTE_COMMAND, lambda _s, d: handle_remote_command(bytes(d))
        )
        for entity, attrs in SUBSCRIPTIONS:
            await client.write_gatt_char(
                ENTITY_UPDATE, bytes([entity] + attrs), response=True
            )
        log("media service ready", "ams")
        return True
    except Exception as exc:
        log(f"media service unavailable: {exc}", "ams")
        return False


async def send(client, command: int) -> bool:
    """Send one remote command. Returns False if the player refused it."""
    try:
        await client.write_gatt_char(REMOTE_COMMAND, bytes([command]),
                                     response=True)
        log(f"sent {CMD_NAMES.get(command, command)}", "ams", debug=True)
        return True
    except Exception as exc:
        log(f"{CMD_NAMES.get(command, command)} failed: {exc}", "ams")
        return False


async def step_volume(client, steps: int) -> None:
    """
    Approximate an absolute volume with AMS step commands.

    The phone moves volume in 1/16ths, so a target becomes round(delta * 16)
    steps. They must be written SEQUENTIALLY - firing them as concurrent
    coroutines meant most were dropped, which is why the slider appeared to do
    nothing and then snapped back.
    """
    command = CMD_VOLUME_UP if steps > 0 else CMD_VOLUME_DOWN
    for _ in range(min(abs(steps), 16)):
        if not await send(client, command):
            return
        await asyncio.sleep(0.06)


def supports(command: int) -> bool:
    """AVAILABLE is empty until the phone tells us, so assume yes until then."""
    return not AVAILABLE or command in AVAILABLE
