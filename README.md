# iPhone Companion

**v2.1** · Windows · Python 3.11+ · PySide6

Mirrors iPhone notifications, calls and media to a Windows desktop over
Bluetooth LE. No app on the phone, no cloud account, no MFi hardware — just
the services iOS already exposes to a bonded Bluetooth peer.

![icon](images/overview_v2.png)

- **Notifications** — every app, with real artwork, and the action labels iOS
  itself advertises ("Answer", "Decline", "Dial", "End Call")
- **Calls** — Apple-style banner with a live duration counter, answer and
  decline from the desktop, dial back from a missed call, plus call history
- **Media** — now playing, transport, volume, album art, synced lyrics
- **Battery** — live level with notifications, and a session history chart
- **Dashboard** — a Qt window that collects all of it, or stay out of the way
  in the system tray

## Screenshots

<table>
  <tr>
    <td width="50%">
      <a href="images/overview_v2.png"><img src="images/overview_v2.png" alt="Overview dashboard" width="100%"></a>
      <br><sub><b>Overview</b> &mdash; phone, battery, six tiles, notifications, media and calls at a glance</sub>
    </td>
    <td width="50%">
      <a href="images/notification_v2.png"><img src="images/notification_v2.png" alt="Notifications page" width="100%"></a>
      <br><sub><b>Notifications</b> &mdash; searchable history, All / Messages / Calls filters, a colour bar per app</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <a href="images/media_v2.png"><img src="images/media_v2.png" alt="Media page" width="100%"></a>
      <br><sub><b>Media</b> &mdash; now playing, source chip, transport, volume and LRCLIB synced lyrics</sub>
    </td>
    <td width="50%">
      <a href="images/device-info_v2.png"><img src="images/device-info_v2.png" alt="Device Info page" width="100%"></a>
      <br><sub><b>Device Info</b> &mdash; what the phone reports, and an activity log showing what the rules did</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <a href="images/settings_v2.png"><img src="images/settings_v2.png" alt="Settings page" width="100%"></a>
      <br><sub><b>Settings</b> &mdash; connection, notification rules, devices, appearance and Spotify</sub>
    </td>
    <td width="50%">
      <a href="images/toasts-stack.png"><img src="images/toasts-stack.png" alt="Four toast variants stacked" width="100%"></a>
      <br><sub><b>Toasts</b> &mdash; incoming call, one-time code, message and missed call, stacked live</sub>
    </td>
  </tr>
</table>

Click any image for full size, or browse [`images/`](images/).

*The dashboard shots are from a real phone, so notification text, contact
names, the Bluetooth address and the Spotify client id are blurred. Toasts
are from the tray's **Simulate** menu, so no real contact appears in them.*

## What's new in 2.1

A full visual pass over every page, working from mockups rather than
tweaking in place.

**A new palette.** Deep navy surfaces with a cyan-leaning accent, sampled
from the mockups instead of being guessed at. Light mode is derived from its
own mockup rather than inverted from dark, so it is warm-neutral with a
darker accent that holds contrast against white. Banners stay dark in both.

**Device Info** gains a hero card, a two-column tile grid, and an activity
log on a timeline. Notifications a rule silenced are dimmed in place and
tagged, never hidden - the log exists to explain what the rules did, so
hiding their effects would defeat it. That needed a schema change: each row
now records the verdict that was applied to it.

**Notifications** gains All / Messages / Calls filters and a per-app colour
bar down the left of each row, keyed off the bundle id so an app keeps its
colour between restarts.

**Calls** gains a Current Call card, search that composes with the filters,
and a decorative waveform. **Messages** states the read-only limitation in
place, on the page where you would otherwise look for a reply box.
**Media** gains a source chip naming the player, since the transport acts on
whatever is playing rather than on a chosen app. **Overview** puts six tiles
beside the phone - three facts, three actions - and **Settings** moves to two
columns.

Not built, and deliberately: "Find iPhone" and "Open Camera" appear in the
mockups but no protocol offers them, so shipping the buttons would have been
a lie. See *Out of scope* below.

### Fixes this pass turned up

- Label font sizes were ignored app-wide. Setting a stylesheet on a widget
  makes Qt resolve its font from QSS, where the global `font-size` rule beat
  `setFont()` - every label had been 13px whatever was asked for.
- Colours were baked in at construction, so switching theme left much of the
  dark UI unreadable. Labels now carry a palette role and re-tint.
- A long notification body set a minimum width that propagated up and pushed
  the Calls card off the Overview row entirely.
- An empty allow-list silenced every notification from every app. That is a
  half-finished setting, not an instruction, and is now treated as off.
- App badges were rendered at 42px and upscaled, which is what made them
  look pixelated. Tiles are 128px now, so every consumer scales down.

## What's new in 2.0

**Notification rules.** Settings has a Notification rules card that decides
what actually raises a banner:

- **App filter** \u2014 silence the apps you pick, or allow only the apps you
  pick. The list is built from apps this phone has actually sent, so you
  never type a bundle id.
- **Priority apps** \u2014 these ignore quiet hours.
- **Quiet hours** \u2014 a nightly window; handles the overnight wrap.
- **Word rules** \u2014 plain words, not patterns. "sale" silences anything
  containing it; first matching rule wins.

Filtered notifications are still recorded, they just do not raise a banner,
so nothing disappears. **Calls are never filtered** \u2014 no rule, block-list
entry or quiet window can hide a ringing phone.

**History that survives a restart.** The feed is kept in SQLite
(`feed.db`), capped at the most recent 10,000 notifications, with a search
box on the Notifications page that queries the whole store rather than
what happens to be on screen. Turn it off with **Save notification
history** in Settings; that stops new writes and leaves existing rows
alone.

**One-time codes.** A code in an SMS gets a copy button on the banner and
on the dashboard row. Detection is deliberately conservative: a number only
counts when an OTP-ish word is near it, and it is rejected when a money or
reference label sits in front, so a bank balance never lands on your
clipboard.

**Light theme.** Settings \u203a Appearance \u203a Theme, applied live. Banners
stay dark in both modes, because they sit over other windows rather than
over the app.

**Toasts and window.** Right-click a banner to snooze it or clear it on the
phone. Notification bodies use a second line when they need one. Banners
follow the screen your cursor is on. The window resizes from all four
edges and corners.

**Smaller things.** Shuffle and repeat are gone from Media \u2014 AMS advances
them blind, with no way to read the state back, so the buttons could never
show what they were doing. App badges render at 128px instead of being
upscaled from 42. The Settings toggle animates.

## How it works

Three services on the phone do the work:

| Service | UUID | What it gives us |
|---|---|---|
| ANCS | `7905F431-…` | notifications, attributes, action labels, perform-action |
| AMS | `89D3502B-…` | player, track, elapsed, volume, remote commands |
| Battery | `0x180F` | level, with notify |

`probe.py` dumps the full GATT database and logs raw ANCS/AMS traffic — it is
how every protocol detail here was established rather than guessed.

## Why this is not Phone Link

The obvious question: Phone Link shows contacts, dials numbers and carries
call audio with no app on the phone either. It does that over **Bluetooth
Classic profiles**, not BLE:

| Profile | Gives | Why we cannot use it |
|---|---|---|
| HFP (Hands-Free) | call audio, dial, answer, hang up, DTMF, mute | Classic/RFCOMM, and Windows itself owns the audio-gateway role |
| PBAP (Phone Book Access) | contacts, recent calls | Classic; no GATT equivalent |
| MAP (Message Access) | reading **and sending** SMS | Classic; why Phone Link can reply and this cannot |

`bleak` wraps `Windows.Devices.Bluetooth.GenericAttributeProfile` — GATT only.
The useful Classic profiles are claimed by the Windows Bluetooth stack, and a
profile takes one client at a time. That is also why the two apps fight over
the phone: both want to be the connected peer.

It cuts the other way too. Phone Link cannot do what this does — per-app
notification artwork, AMS media state, and iOS's own localised action labels
are all GATT. **Phone Link is the telephony client; this is the notification
client.** Complementary, unfortunately mutually exclusive.

### What is not possible

- **Call duration** is not transmitted. It is derived from the Active Call
  notification appearing and being removed, which matches a stopwatch to well
  under a second.
- **Mute state** is not exposed anywhere — not even in HFP's indicator set.
- **Locking the phone** cannot be done. Remote lock is a Find My / MDM
  function, through Apple's cloud or iAP2 with an MFi chip.
- **Sending a reply** is not possible. ANCS is read-only.
- **Call audio** stays on the phone.
- **Lyrics** do not come from Spotify — there is no public lyrics endpoint.
  They come from [LRCLIB](https://lrclib.net), free and key-less.

## Requirements

- Windows 10/11, built-in or USB Bluetooth LE
- Python 3.11+ (developed on 3.14)
- An iPhone **bonded once** through Windows Bluetooth settings

## Setup

Follow these in order. Step 2 must happen **before** the first run — the app
cannot see the notification service on a phone Windows has not bonded with,
and a failed first attempt gets cached (see the note at the end of step 2).

### 1. Install Python

Python **3.11 or newer**, from [python.org](https://www.python.org/downloads/).
Tick **"Add python.exe to PATH"** in the installer.

Prefer the python.org build over the Microsoft Store one, which sandboxes
file writes and can put `%LOCALAPPDATA%` somewhere the app does not expect.

Check it worked — open a **new** terminal (PATH changes need one) and run:

```bat
python --version
```

You should see `Python 3.11.x` or higher. If you get "Python was not found",
PATH was not set; re-run the installer and tick the box.

### 2. Bond the iPhone to Windows

ANCS characteristics require an encrypted link, and iOS will not even list
the service to an unbonded peer — which surfaces as "characteristic not
found" rather than as a permission error.

1. iPhone → Settings → Bluetooth → (i) next to the PC → **Forget This Device**
2. Windows → Settings → Bluetooth & devices → remove any existing iPhone entry
3. Windows → **Add device** → **Bluetooth** → pick the iPhone
4. Confirm the pairing code on **both** screens
5. On the iPhone, when it asks, **Allow** notifications to be shared

Steps 1–2 are cache invalidation, not superstition. Windows caches a device's
GATT service list, and an empty ANCS list from an unbonded attempt survives a
later successful bond — so a phone that was paired before you read this needs
forgetting and re-pairing.

### 3. Disable Phone Link autostart

Task Manager → **Startup apps** → **Phone Link** → Disable. Then quit it if
it is running.

This matters more than it looks. A Bluetooth profile serves one client at a
time, and Phone Link holds the link. It is the single most common cause of a
connection that will not hold. See "Why this is not Phone Link" above for why
the two cannot coexist.

### 4. Get the code

```bat
git clone https://github.com/<you>/iphone-companion.git
cd iphone-companion
```

No git? Download the ZIP from GitHub and extract it, then `cd` into it.

### 5. Create a virtual environment

```bat
python -m venv .venv
```

Activate it. **The command differs by terminal:**

```bat
.venv\Scripts\activate.bat
```

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell refuses with *"running scripts is disabled on this system"*,
either use Command Prompt instead, or allow local scripts once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Your prompt should now start with `(.venv)`.

### 6. Install the dependencies

```bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Use `python -m pip`, not a bare `pip`. On Windows the two frequently resolve
to different interpreters, which is how packages end up installed somewhere
the app cannot import them from.

This pulls PySide6 (~100 MB), bleak, Pillow, pystray and windows-toasts.

### 7. Run it

```bat
python qt_main.py
```

The dashboard opens and the tray icon appears. The sidebar footer shows
**Connected** with the phone's name once the link is up; the first connection
can take up to a minute while Windows resolves the rotating BLE address.

### 8. Check it works without the phone

Right-click the tray icon → **Simulate** → **All toasts**. Every banner
variant appears — incoming call, missed call, message, OTP message and a
bank alert. This exercises the UI end to end and needs no phone at all, so
it is the fastest way to confirm the install is sound.

You can also verify the one-time-code detector on its own:

```bat
python otp.py
```

It should print `23/23 passed`.

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Python was not found` | PATH not set. Re-run the python.org installer with "Add python.exe to PATH", then open a new terminal. |
| `running scripts is disabled on this system` | PowerShell execution policy. Use `activate.bat` in Command Prompt, or run the `Set-ExecutionPolicy` line in step 5. |
| `ModuleNotFoundError: No module named 'PySide6'` | The venv is not active, or packages went to a different interpreter. Re-activate and reinstall with `python -m pip`. |
| Connects, then drops within seconds | Phone Link. Disable its autostart and quit it (step 3). |
| "characteristic not found", or no notifications ever arrive | The phone is not bonded, or a pre-bond service list is cached. Redo step 2 in full, including the Forget on both sides. |
| Connects but no notifications from one app | iOS mirrors Notification Centre. If the app is set to Deliver Quietly or is off in Settings → Notifications, nothing is sent. |
| Window opens blank or the tray icon is missing | Another instance is already running. Quit it from the tray first. |
| No Bluetooth adapter found | The PC needs Bluetooth **LE** (4.0+). Check Device Manager → Bluetooth. A USB BLE dongle works. |

Set `ANCS_DEBUG=1` before running for verbose protocol logs — `set ANCS_DEBUG=1`
in Command Prompt, `$env:ANCS_DEBUG=1` in PowerShell. The log also goes to
`ancs_notifier.log` beside the scripts.

### Optional: replace the icon

The repo ships `assets/app_icon.png` and `assets/app.ico`, so **you do not
need this to run the app**. Only if you want your own artwork:

```bat
python make_icon.py "path\to\your-icon.png"
```

## Running

```bat
python qt_main.py             console visible, for debugging
pythonw qt_main.py            no console
python app_ble.py             headless, Tkinter banners only
python probe.py --listen 180  protocol reconnaissance
```

Quit from the tray, `Ctrl+Q` in the window, or `Ctrl+C` in the console.
`set ANCS_DEBUG=1` (cmd) or `$env:ANCS_DEBUG=1` (PowerShell) for verbose logs.

The tray's **Simulate** submenu raises any toast variant — incoming call,
missed call, message, OTP message, bank alert, or all of them — without
touching the phone.

## Optional: Spotify

AMS gives no album art and no absolute volume. Spotify's Web API gives both.

1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Add `http://127.0.0.1:8899/callback` as a redirect URI
3. Paste the Client ID into Settings → Spotify → Connect

Auth is Authorization Code with **PKCE**, so no client secret is stored — only
a refresh token, in `%LOCALAPPDATA%\ANCSNotifier\spotify.json`. Absolute volume
requires Spotify Premium; the API returns 403 otherwise.

## Building

Check it starts first. `smoke.py` builds a real `Application` in both
themes and renders every page — importing `qt_main` only runs the module
body, so a missing import inside the constructor passes an import check and
still fails on launch:

```bat
python smoke.py dark
python smoke.py light
python otp.py
python rules.py
```

All four should end in `FAILURES: 0` or `N/N passed`. Then:

```bat
python -m pip install pyinstaller
python build.py --installer
```

Produces `dist\iPhoneCompanion\` and, with
[Inno Setup 6](https://jrsoftware.org/isdl.php), a per-user setup exe in
`dist\installer\`. No admin rights needed — Bluetooth does not require
elevation. Expect SmartScreen to flag an unsigned binary on first run.

The version comes from `paths.APP_VERSION` and `build.py` injects it into
the installer, so that constant is the only place to change it.

A frozen build keeps its data in `%LOCALAPPDATA%\ANCSNotifier\`, separate
from a source run, so the installed app starts with its own settings and
history rather than inheriting the ones beside the scripts.

## Layout

| File | Role |
|---|---|
| `ancs.py` | ANCS protocol: packets, attributes, actions, reassembly |
| `ams.py` | Apple Media Service: now playing and remote commands |
| `app_ble.py` | connect, subscribe, stay connected |
| `calls.py` | reconstructs call state and duration from ANCS events |
| `qt_main.py` | entry point: tray, threads, signal bridging |
| `dashboard.py` | the window and its seven pages |
| `qt_toast.py` | desktop toasts — four variants, one component |
| `otp.py` | finds a one-time code in a notification, for the Copy pill |
| `rules.py` | decides show / silence / discard for every notification |
| `feeddb.py` | SQLite persistence and search for the feed |
| `theme.py` | palette, plus the toast QSS and its scale factors |
| `widgets.py` `vicons.py` | dashboard building blocks, vector icons |
| `store.py` `status.py` `applog.py` `prefs.py` | shared state, logging, settings |
| `spotify.py` `lyrics.py` | optional artwork, volume and lyrics |
| `icons.py` `appicon.py` | app artwork, and the tray/application icon |
| `startup.py` `desktop.py` `shortcuts.py` | run-at-login, desktop shortcut, and the actions that work |
| `simulate.py` | fake phone events for testing the UI |
| `smoke.py` | builds a real Application in both themes; run before a release |
| `probe.py` | GATT dump and raw traffic log |
| `build.py` `installer.iss` | packaging |
| `make_icon.py` | regenerates the icon assets — not needed to run or build |

`macos_toast.py` and `tray_app.py` are the superseded Tkinter/pystray
implementation, kept as a fallback for running `app_ble.py` bare.

## Runtime data

Everything writable lives in `%LOCALAPPDATA%\ANCSNotifier\` when frozen, or
beside the scripts from source: `config.json` (cached address), `spotify.json`
(refresh token — **not** for committing), `prefs.json`, `lyrics.json`,
`icon_cache\`, `art\`, `ancs_notifier.log`.


`feed.db` holds the notification history (SQLite, newest 10,000). Delete it
to wipe history, or turn off **Save notification history** in Settings to stop
writing to it. `prefs.json` holds every setting; both live beside the scripts
when running from source, and in `%LOCALAPPDATA%\ANCSNotifier\` when installed.

## Notes for anyone extending this

- Action-label attributes (`6`, `7`), `AppIdentifier` and `Date` take **no**
  length parameter. Appending one makes iOS read the length bytes as two more
  attribute requests and corrupts the whole response.
- Control Point writes must be **sequential**. Concurrent writes get dropped —
  that is what made the volume slider look dead.
- Answered vs missed is detectable because Incoming-Call-removed and
  Active-Call-added arrive in the same millisecond.
- iPhones rotate their BLE address; the cached one self-heals after three
  consecutive failures.
- Qt cannot round a translucent top-level window's corners, so every toast is
  a transparent window wrapping a styled child `QFrame`.
- `QGraphicsDropShadowEffect` on a child of such a window can render blank —
  see `USE_SHADOW` in `qt_toast.py`.

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with or endorsed by Apple. ANCS and AMS are Apple
specifications; this is an independent client for them.
