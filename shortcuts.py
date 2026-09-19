"""
shortcuts.py - the actions we can actually perform.

Locking the iPhone from here is not possible, and it is worth being precise
about why: over BLE the phone exposes ANCS (notifications), AMS (media), and
the standard battery / device-info services. None of them can lock, wake,
ring or locate the device. Remote lock is an MDM or Find My function, reached
through Apple's cloud with a signed profile, or over iAP2 with an MFi
authentication chip - neither is available to a generic Bluetooth peer.

So these shortcuts are the honest set: things this PC can do, plus the two
BLE actions we really have.
"""

from __future__ import annotations

import ctypes
import os

import paths
from applog import log

PHONE_LOCK_REASON = (
    "iOS exposes no lock command over Bluetooth - it needs MDM or an MFi chip"
)


def can_lock_phone() -> bool:
    return False


def lock_pc() -> bool:
    """Lock this workstation. The phone-lock request, inverted."""
    try:
        ctypes.windll.user32.LockWorkStation()
        log("workstation locked", "app")
        return True
    except Exception as exc:
        log(f"could not lock the PC: {exc}", "app")
        return False


def open_data_folder() -> bool:
    try:
        os.startfile(paths.DATA_DIR)                     # noqa: S606
        return True
    except Exception as exc:
        log(f"could not open data folder: {exc}", "app")
        return False


def open_log() -> bool:
    try:
        os.startfile(paths.LOG_PATH)                     # noqa: S606
        return True
    except Exception as exc:
        log(f"could not open log: {exc}", "app")
        return False


def open_bluetooth_settings() -> bool:
    try:
        os.startfile("ms-settings:bluetooth")            # noqa: S606
        return True
    except Exception as exc:
        log(f"could not open Bluetooth settings: {exc}", "app")
        return False
