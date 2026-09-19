# Handover — where v1 ended, where v2 starts

## v1.0.0 state

Working: ANCS notifications with per-app artwork, Apple-style desktop toasts
(notification / missed call / incoming call / active call), call tracking with
live duration, answer / decline / dial over `PerformNotificationAction`, AMS
media control, battery, Spotify link (PKCE) for album art and absolute volume,
LRCLIB synced lyrics, seven-page Qt dashboard, device picker, banner opacity,
run-at-login, tray simulation of every toast.

Read `README.md` first — it has the protocol table, the Phone Link comparison
and the "what is not possible" list. The code's docstrings carry the reasoning
for anything that looks arbitrary.

## Loose ends

- `USE_SHADOW = False` in `qt_toast.py`. `QGraphicsDropShadowEffect` on a child
  of a translucent frameless window can render blank. To get the shadow back,
  pre-render it as a pixmap behind the card rather than using the effect.
- Long notification bodies are elided to one line. Two lines would need a
  taller fixed height for the notification variant only.
- `.gitignore` has a duplicated block near the end. Harmless, untidy.
- `macos_toast.py` / `tray_app.py` are the superseded Tkinter path, kept only
  so `python app_ble.py` works bare. Delete if that is not wanted.
- Dashboard nav colours (`CARD_HOVER`, `#1C222C`) were tuned against the old
  sidebar colour, before it became `#0E1823`.

## v2 candidates

- Pre-rendered shadow, so toasts float properly.
- Toast action for media (play/pause from the banner).
- Notification filtering per app — the data is all in `store.FEED`.
- Message send: impossible over BLE. Would need MAP over Bluetooth Classic,
  which Windows owns. See the README table before attempting.
- Multi-monitor: the toast stack uses `primaryScreen()`.
- Light theme: the palette is centralised in `theme.py`, the toast QSS is not
  parameterised by mode.

## Hard-won facts worth not re-learning

- Attributes 6, 7, `AppIdentifier` and `Date` take NO length parameter.
- Control Point writes must be sequential; concurrent writes get dropped.
- Phone Link holds the BLE link. Its autostart must be off.
- Answered vs missed: Incoming-removed and Active-added land in the same ms.
- Mute state, phone lock and replies are not in the protocol. Not a bug.
- `QAction.triggered` passes `checked` as the first argument — connect lambdas.
- QSS cannot round a top-level translucent window; style a child frame.
