"""
dashboard.py - the main window.

Seven pages, built to the reference mock: Overview, Media, Notifications,
Calls, Messages, Device Info, Settings. Frameless, with its own window
controls, and a sidebar that always reflects the page on screen.

Two layout rules learned the hard way:

  * Navigation always goes through goto(), which sets the page AND checks the
    matching sidebar button. Calling setCurrentIndex() directly left the
    sidebar highlighting the wrong item.
  * The Overview has to fit a 1080p screen without scrolling, so card padding,
    the phone render and the tile heights are sized against that budget, and
    the lower rows carry the stretch instead of a trailing spacer.

While this window is visible, notifications route into the Recent
Notifications card instead of appearing as desktop banners.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QPushButton,
                               QScrollArea, QSizeGrip, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

import ams
import appicon
import applog
import calls
import icons
import lyrics
import paths
import prefs
import shortcuts
import spotify
import startup
import theme
import vicons
from store import DEVICE, FEED, MEDIA, ago
from widgets import (Artwork, BatteryPill, Card, EmptyState, FeedRow,
                     FilterTabs, InfoRow, LyricsView, Meter, NavButton,
                     PageHeader, PhoneMock, SettingRow, ShortcutTile,
                     Sparkline, StackRow, StatusPill, Switch, TileButton,
                     ghost_button, icon_label, label)

NAV = [
    ("Overview", "home"),
    ("Media", "music"),
    ("Notifications", "bell"),
    ("Calls", "phone"),
    ("Messages", "chat"),
    ("Device Info", "device"),
]
PAGE_OVERVIEW, PAGE_MEDIA, PAGE_NOTIFICATIONS = 0, 1, 2
PAGE_CALLS, PAGE_MESSAGES, PAGE_DEVICE, PAGE_SETTINGS = 3, 4, 5, 6

MESSAGE_APPS = ("net.whatsapp.WhatsApp", "com.apple.MobileSMS",
                "ph.telegra.Telegraph")

_ART_CACHE: dict[str, QPixmap] = {}


def _pixmap_for(bundle_id: str, app: str = "") -> QPixmap | None:
    """
    Artwork for a notification row.

    icons.resolve() already covers cached App Store artwork, drawn tiles for
    Apple's own apps, and a monogram fallback. Reading PNGs off disk alone
    missed the system apps, which is why Phone showed a bare letter.
    Cached per bundle id because refresh() runs every second.
    """
    key = (bundle_id or app or "?").strip()
    if key in _ART_CACHE:
        return _ART_CACHE[key]
    try:
        tile = icons.resolve(bundle_id, app).convert("RGBA")
        image = QImage(tile.tobytes("raw", "RGBA"), tile.width, tile.height,
                       QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(image.copy())
    except Exception:
        pixmap = None
    _ART_CACHE[key] = pixmap
    return pixmap


def _mmss(seconds: float) -> str:
    seconds = int(max(0, seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


class Dashboard(QMainWindow):
    media_command = Signal(int)
    volume_set = Signal(int)
    scan_requested = Signal()
    device_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("iPhone Connect")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(1440, 960)
        self.setMinimumSize(1120, 720)
        self._drag = None
        self._battery_history: list[int] = []
        self._battery_sampled = 0.0
        self._first_battery: tuple[float, int] | None = None
        self._toast_rows: list[QFrame] = []
        self._call_filter = "All"
        self._feed_signature = None
        self._call_signature = None

        shell = QWidget()
        self.setCentralWidget(shell)
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._sidebar())

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._titlebar())

        self.pages = QStackedWidget()
        for builder in (self._page_overview, self._page_media,
                        self._page_notifications, self._page_calls,
                        self._page_messages, self._page_device,
                        self._page_settings):
            self.pages.addWidget(builder())
        column.addWidget(self.pages, 1)
        row.addLayout(column, 1)

        # A QSizeGrip parented straight to the window is not in any layout,
        # so it keeps Qt's default 100x30 geometry at (0, 0) rather than its
        # 17x17 sizeHint - a rectangle of canvas colour sitting over the
        # top-left of the sidebar. It also hides itself while the window is
        # maximized, which is why the patch appeared and vanished with the
        # window state. Size it properly, park it bottom-right where a grip
        # belongs, and keep it there through resizes.
        self.grip = QSizeGrip(self)
        self.grip.setObjectName("sizeGrip")
        self.grip.resize(self.grip.sizeHint())
        self._place_grip()
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.refresh)
        self.clock.start(1000)
        self.refresh()

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #

    def _place_grip(self) -> None:
        """Bottom-right corner, inside the window. Called on every resize."""
        size = self.grip.size()
        self.grip.move(self.width() - size.width(),
                       self.height() - size.height())
        self.grip.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_grip()

    def goto(self, index: int) -> None:
        """The only way pages change, so the sidebar can never drift."""
        self.pages.setCurrentIndex(index)
        button = self.nav_group.button(index)
        if button is not None:
            button.setChecked(True)

    def _link(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("link")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self.goto(index))
        return button

    # ------------------------------------------------------------------ #
    # chrome
    # ------------------------------------------------------------------ #

    def _titlebar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"background: {theme.BG}; border: none;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 9, 14, 5)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.pill = StatusPill()
        layout.addWidget(self.pill, 0, Qt.AlignVCenter)

        more = ghost_button("dots", 18, theme.TEXT_DIM, 32)
        more.clicked.connect(lambda: self.goto(PAGE_SETTINGS))
        layout.addWidget(more)
        layout.addSpacing(6)

        for glyph, slot, name in (("minimise", self.showMinimized, "chrome"),
                                  ("maximise", self._toggle_max, "chrome"),
                                  ("close", self.hide, "chromeClose")):
            button = QPushButton()
            button.setObjectName(name)
            button.setIcon(vicons.icon(glyph, 15, theme.TEXT_DIM))
            button.setFixedSize(40, 30)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            layout.addWidget(button)

        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        bar.mouseReleaseEvent = self._bar_release
        bar.mouseDoubleClickEvent = lambda _e: self._toggle_max()
        return bar

    def _bar_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = (event.globalPosition().toPoint()
                          - self.frameGeometry().topLeft())

    def _bar_move(self, event):
        if self._drag is not None and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self._drag)

    def _bar_release(self, _event):
        self._drag = None

    def _toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(244)
        # The brand band runs edge to edge, so it cannot sit inside the padded
        # column the nav and footer use. The frame holds an unpadded outer
        # layout instead, and the padding everything else expects moves onto a
        # body widget underneath the band.
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget()
        body.setObjectName("sidebarBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        # Its own padding, since it no longer inherits the body's.
        brand.setContentsMargins(16, 16, 16, 16)
        brand.setSpacing(11)
        mark = QLabel()
        mark.setFixedSize(40, 40)
        try:
            art = appicon.plain(40).convert("RGBA")
            image = QImage(art.tobytes("raw", "RGBA"), art.width, art.height,
                           QImage.Format_RGBA8888)
            mark.setPixmap(QPixmap.fromImage(image.copy()))
            # Fill behind the artwork in its own tile colour, so its rounded
            # corners do not show the sidebar through and read as an overlay.
            mark.setStyleSheet(
                f"background: {appicon.background_colour()};"
                f"border: none; border-radius: 10px;")
        except Exception:
            mark.setStyleSheet(
                f"background: {theme.ACCENT}; border-radius: 10px;")
        brand.addWidget(mark, 0, Qt.AlignVCenter)

        # A QVBoxLayout will shrink a QLabel below its sizeHint when the
        # column runs short of room, which clipped the tops off these two.
        # Minimum heights stop that. The subtitle is a size smaller than the
        # title because at 11px "Connected via Bluetooth" ran past the
        # sidebar and was cut mid-word.
        titles = QVBoxLayout()
        titles.setSpacing(1)
        brand_name = label("iPhone Companion", 13, QFont.DemiBold)
        brand_name.setMinimumHeight(20)
        self.brand_sub = label("Connected via Bluetooth", 10, QFont.Normal,
                               theme.TEXT_FAINT)
        self.brand_sub.setMinimumHeight(15)
        titles.addWidget(brand_name)
        titles.addWidget(self.brand_sub)
        brand.addLayout(titles, 1)

        brand_row = QWidget()
        # Without an object name this picks up the global "QWidget {
        # background: BG }" rule and paints the near-black canvas colour.
        # Named, it gets the band colour from theme.sheet() instead.
        brand_row.setObjectName("brandRow")
        brand_row.setLayout(brand)
        brand_row.setMinimumHeight(48)
        outer.addWidget(brand_row, 0)
        outer.addWidget(body, 1)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (text, glyph) in enumerate(NAV):
            button = NavButton(text, glyph)
            button.clicked.connect(lambda _c, i=index: self.goto(i))
            self.nav_group.addButton(button, index)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        layout.addStretch(1)
        settings = NavButton("Settings", "settings")
        settings.clicked.connect(lambda: self.goto(PAGE_SETTINGS))
        self.nav_group.addButton(settings, PAGE_SETTINGS)
        layout.addWidget(settings)
        layout.addSpacing(14)

        footer = QHBoxLayout()
        footer.setSpacing(11)
        self.footer_dot = QLabel()
        self.footer_dot.setFixedSize(10, 10)
        footer.addWidget(self.footer_dot, 0, Qt.AlignTop)
        footer_column = QVBoxLayout()
        footer_column.setSpacing(1)
        self.footer_state = label("Connecting", 12, QFont.DemiBold)
        self.footer_name = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        self.footer_address = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        for widget in (self.footer_state, self.footer_name,
                       self.footer_address):
            footer_column.addWidget(widget)
        footer.addLayout(footer_column)
        footer.addStretch(1)
        layout.addLayout(footer)
        return bar

    def _scroll(self, inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return area

    # ------------------------------------------------------------------ #
    # overview
    # ------------------------------------------------------------------ #

    def _page_overview(self) -> QWidget:
        """
        Grouped by subject: the phone and its notifications up top, then media
        beside the two communication cards, then battery, then the actions.
        """
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 0, 24, 20)
        outer.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(self._card_hero(), 6)
        top.addWidget(self._card_feed(), 5)
        outer.addLayout(top, 0)

        middle = QHBoxLayout()
        middle.setSpacing(16)
        middle.addWidget(self._card_now_playing(), 5)
        middle.addWidget(self._card_messages(), 4)
        middle.addWidget(self._card_calls_summary(), 4)
        outer.addLayout(middle, 1)

        outer.addWidget(self._card_battery(), 0)
        outer.addWidget(self._card_shortcuts(), 0)
        return self._scroll(page)

    def _card_messages(self) -> Card:
        card = Card("Messages")
        card.body.setContentsMargins(18, 16, 18, 14)
        card.header.addWidget(self._link("See All", PAGE_MESSAGES))
        self.messages_dash_box = QVBoxLayout()
        self.messages_dash_box.setSpacing(0)
        card.body.addLayout(self.messages_dash_box)
        self.messages_dash_empty = EmptyState(
            "chat", "No recent messages",
            "WhatsApp and Messages land here.")
        card.body.addWidget(self.messages_dash_empty)
        card.body.addStretch(1)
        return card

    def _card_shortcuts(self) -> Card:
        """
        Only actions that genuinely work. Locking the iPhone is not one of
        them - see shortcuts.PHONE_LOCK_REASON - so it is shown disabled with
        an explanation rather than as a button that silently does nothing.
        """
        card = Card("Shortcuts")
        card.body.setContentsMargins(18, 16, 18, 14)
        grid = QGridLayout()
        grid.setSpacing(11)

        entries = (
            ("lock", "Lock PC", theme.ACCENT, shortcuts.lock_pc, True),
            ("bluetooth", "Bluetooth", "#3A4250",
             shortcuts.open_bluetooth_settings, True),
            ("signal", "Reconnect", theme.GREEN, self._reconnect, True),
            ("device", "Lock iPhone", "#3A4250", None, False),
        )
        for index, (glyph, caption, colour, action, enabled) in enumerate(entries):
            tile = ShortcutTile(glyph, caption, colour)
            tile.setMinimumHeight(96)
            if enabled and action is not None:
                tile.clicked.connect(lambda _c, fn=action: fn())
            else:
                tile.setEnabled(False)
                tile.setToolTip(shortcuts.PHONE_LOCK_REASON)
            grid.addWidget(tile, 0, index)
        card.body.addLayout(grid)
        return card

    def _reconnect(self) -> None:
        import app_ble
        app_ble.drop_link()

    def _card_hero(self) -> Card:
        card = Card()
        card.body.setContentsMargins(18, 16, 18, 16)
        row = QHBoxLayout()
        row.setSpacing(24)

        self.phone = PhoneMock()
        row.addWidget(self.phone, 0, Qt.AlignTop)

        details = QVBoxLayout()
        details.setSpacing(2)
        details.setContentsMargins(0, 4, 0, 0)
        self.device_title = label("iPhone", 23, QFont.DemiBold)
        self.device_sub = label("", 12, QFont.Normal, theme.TEXT_DIM)
        details.addWidget(self.device_title)
        details.addWidget(self.device_sub)
        details.addSpacing(14)

        battery_row = QHBoxLayout()
        battery_row.setSpacing(12)
        self.hero_pill = BatteryPill(56, 27)
        battery_row.addWidget(self.hero_pill, 0, Qt.AlignVCenter)
        self.hero_pct = label("\u2014", 20, QFont.DemiBold)
        battery_row.addWidget(self.hero_pct, 0, Qt.AlignVCenter)
        battery_column = QVBoxLayout()
        battery_column.setSpacing(4)
        self.hero_meter = Meter(6)
        battery_column.addWidget(self.hero_meter)
        self.hero_estimate = label("", 11, QFont.Normal, theme.TEXT_DIM)
        battery_column.addWidget(self.hero_estimate)
        battery_row.addLayout(battery_column, 1)
        details.addLayout(battery_row)
        details.addSpacing(14)

        self.hero_rows = {
            "manufacturer": StackRow("apple", "\u2014", "Manufacturer"),
            "model": StackRow("device", "\u2014", "Model"),
            "bluetooth": StackRow("bluetooth", "\u2014", "", theme.ACCENT),
        }
        for stack in self.hero_rows.values():
            details.addWidget(stack)
        details.addStretch(1)
        row.addLayout(details, 1)
        card.body.addLayout(row)
        return card

    def _card_now_playing(self) -> Card:
        """
        Transport is prev / play / next only - shuffle, repeat and like were
        dropped because Spotify never advertised them in the AMS command list,
        so they were decoration. Volume lives here now.
        """
        card = Card("Now Playing")
        card.body.setContentsMargins(18, 16, 18, 16)
        card.header.addWidget(self._link("See All", PAGE_MEDIA))

        row = QHBoxLayout()
        row.setSpacing(14)
        self.np_art = Artwork(76, 0.2)
        row.addWidget(self.np_art, 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.np_title = label("Nothing playing", 15, QFont.DemiBold)
        self.np_artist = label("", 12, QFont.Normal, theme.TEXT_DIM)
        self.np_album = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        for widget in (self.np_title, self.np_artist, self.np_album):
            column.addWidget(widget)
        row.addLayout(column, 1)
        card.body.addLayout(row)

        self.np_meter = Meter(6, theme.ACCENT)
        card.body.addWidget(self.np_meter)

        times = QHBoxLayout()
        self.np_elapsed = label("0:00", 11, QFont.Normal, theme.TEXT_DIM)
        self.np_total = label("0:00", 11, QFont.Normal, theme.TEXT_DIM)
        times.addWidget(self.np_elapsed)
        times.addStretch(1)
        times.addWidget(self.np_total)
        card.body.addLayout(times)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        transport.addStretch(1)

        quieter = ghost_button("mute", 22, theme.TEXT, 44)
        quieter.setToolTip("Volume down")
        quieter.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_VOLUME_DOWN))
        transport.addWidget(quieter)

        previous = ghost_button("previous", 24, theme.TEXT, 46)
        previous.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_PREVIOUS))
        transport.addWidget(previous)

        self.np_play = QPushButton()
        self.np_play.setObjectName("round")
        self.np_play.setIcon(vicons.icon("play", 22, theme.BG))
        self.np_play.setFixedSize(52, 52)
        self.np_play.setCursor(Qt.PointingHandCursor)
        self.np_play.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_TOGGLE))
        transport.addWidget(self.np_play)

        following = ghost_button("next", 24, theme.TEXT, 46)
        following.clicked.connect(lambda: self.media_command.emit(ams.CMD_NEXT))
        transport.addWidget(following)

        louder = ghost_button("volume", 22, theme.TEXT, 44)
        louder.setToolTip("Volume up")
        louder.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_VOLUME_UP))
        transport.addWidget(louder)
        transport.addStretch(1)
        card.body.addLayout(transport)

        self.np_hint = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        self.np_hint.setAlignment(Qt.AlignHCenter)
        card.body.addWidget(self.np_hint)
        card.body.addStretch(1)
        return card

    def _card_feed(self) -> Card:
        """Recent notifications, with live arrivals pinned above them."""
        card = Card("Recent Notifications")
        card.body.setContentsMargins(18, 16, 18, 14)
        card.header.addWidget(self._link("View All", PAGE_NOTIFICATIONS))

        self.toast_box = QVBoxLayout()
        self.toast_box.setSpacing(8)
        card.body.addLayout(self.toast_box)

        self.feed_box = QVBoxLayout()
        self.feed_box.setSpacing(0)
        card.body.addLayout(self.feed_box)
        self.feed_empty = EmptyState("bell", "No notifications yet",
                                     "They appear here as they arrive.")
        card.body.addWidget(self.feed_empty)
        card.body.addStretch(1)
        return card

    def _card_calls_summary(self) -> Card:
        card = Card("Calls")
        card.body.setContentsMargins(18, 16, 18, 14)
        card.header.addWidget(self._link("See All", PAGE_CALLS))
        self.calls_summary_box = QVBoxLayout()
        self.calls_summary_box.setSpacing(0)
        card.body.addLayout(self.calls_summary_box)
        self.calls_summary_empty = EmptyState(
            "phone", "No recent calls", "Calls from your iPhone appear here.")
        card.body.addWidget(self.calls_summary_empty)
        card.body.addStretch(1)
        return card

    def _card_battery(self) -> Card:
        card = Card("Battery")
        card.body.setContentsMargins(18, 16, 18, 14)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.batt_pill = BatteryPill(62, 30)
        row.addWidget(self.batt_pill, 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(0)
        self.batt_pct = label("\u2014", 22, QFont.DemiBold)
        self.batt_note = label("Waiting for the phone", 11, QFont.Normal,
                               theme.TEXT_DIM)
        column.addWidget(self.batt_pct)
        column.addWidget(self.batt_note)
        row.addLayout(column, 1)
        card.body.addLayout(row)

        self.batt_spark = Sparkline()
        card.body.addWidget(self.batt_spark, 1)
        legend = QHBoxLayout()
        legend.addWidget(label("Session start", 10, QFont.Normal,
                               theme.TEXT_FAINT))
        legend.addStretch(1)
        legend.addWidget(label("Now", 10, QFont.Normal, theme.TEXT_FAINT))
        card.body.addLayout(legend)
        return card

    # ------------------------------------------------------------------ #
    # media
    # ------------------------------------------------------------------ #

    def _page_media(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(18)
        layout.addWidget(PageHeader(
            "Media", "Control music and media playback on your iPhone"))

        playing = Card("Now Playing")
        row = QHBoxLayout()
        row.setSpacing(18)
        self.media_art = Artwork(108, 0.16)
        row.addWidget(self.media_art, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(3)
        self.media_title = label("No media playing", 16, QFont.DemiBold)
        self.media_artist = label("Play something on your iPhone to see it "
                                  "here.", 12, QFont.Normal, theme.TEXT_DIM)
        self.media_album = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        for widget in (self.media_title, self.media_artist, self.media_album):
            column.addWidget(widget)
        column.addStretch(1)
        row.addLayout(column, 1)
        playing.body.addLayout(row)

        self.media_meter = Meter(6, theme.ACCENT)
        playing.body.addWidget(self.media_meter)
        times = QHBoxLayout()
        self.media_elapsed = label("0:00", 11, QFont.Normal, theme.TEXT_DIM)
        self.media_total = label("0:00", 11, QFont.Normal, theme.TEXT_DIM)
        times.addWidget(self.media_elapsed)
        times.addStretch(1)
        times.addWidget(self.media_total)
        playing.body.addLayout(times)

        transport = QHBoxLayout()
        transport.setSpacing(10)
        transport.addStretch(1)
        for glyph, command in (("shuffle", ams.CMD_ADVANCE_SHUFFLE),
                               ("previous", ams.CMD_PREVIOUS)):
            button = ghost_button(glyph, 21, theme.TEXT, 44)
            button.clicked.connect(
                lambda _c, cmd=command: self.media_command.emit(cmd))
            transport.addWidget(button)
        self.media_play = QPushButton()
        self.media_play.setObjectName("round")
        self.media_play.setIcon(vicons.icon("play", 22, theme.BG))
        self.media_play.setFixedSize(54, 54)
        self.media_play.setCursor(Qt.PointingHandCursor)
        self.media_play.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_TOGGLE))
        transport.addWidget(self.media_play)
        for glyph, command in (("next", ams.CMD_NEXT),
                               ("repeat", ams.CMD_ADVANCE_REPEAT)):
            button = ghost_button(glyph, 21, theme.TEXT, 44)
            button.clicked.connect(
                lambda _c, cmd=command: self.media_command.emit(cmd))
            transport.addWidget(button)
        transport.addStretch(1)
        playing.body.addLayout(transport)

        playing.body.addWidget(SettingRow(
            "output", "Output", "iPhone - audio stays on the phone over BLE"))
        layout.addWidget(playing)

        volume = Card("Volume")
        self.volume_meter = Meter(7, theme.ACCENT)
        volume.body.addWidget(self.volume_meter)
        self.volume_text = label("\u2014", 12, QFont.Normal, theme.TEXT_DIM)
        volume.body.addWidget(self.volume_text)
        buttons = QHBoxLayout()
        buttons.setSpacing(11)
        for glyph, caption, command in (
            ("mute", "Volume Down", ams.CMD_VOLUME_DOWN),
            ("volume", "Volume Up", ams.CMD_VOLUME_UP),
            ("play", "Play", ams.CMD_PLAY),
            ("pause", "Pause", ams.CMD_PAUSE),
        ):
            tile = TileButton(glyph, caption)
            tile.setMinimumHeight(80)
            tile.clicked.connect(
                lambda _c, cmd=command: self.media_command.emit(cmd))
            buttons.addWidget(tile)
        volume.body.addLayout(buttons)
        layout.addWidget(volume)

        words = Card("Lyrics")
        self.lyrics_source = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        words.header.addWidget(self.lyrics_source)
        self.lyrics_view = LyricsView()
        words.body.addWidget(self.lyrics_view)
        layout.addWidget(words)
        layout.addStretch(1)
        return self._scroll(page)

    # ------------------------------------------------------------------ #
    # notifications / calls / messages
    # ------------------------------------------------------------------ #

    def _page_notifications(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)

        head = QHBoxLayout()
        head.addWidget(PageHeader("Notifications",
                                  "View iPhone notifications in real time"))
        head.addStretch(1)
        clear = QPushButton("Clear list")
        clear.setObjectName("pill")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear_feed)
        head.addWidget(clear, 0, Qt.AlignBottom)
        layout.addLayout(head)

        card = Card()
        self.all_box = QVBoxLayout()
        self.all_box.setSpacing(0)
        card.body.addLayout(self.all_box)
        self.all_empty = EmptyState("bell", "Nothing yet",
                                    "Notifications from the phone land here.")
        card.body.addWidget(self.all_empty)
        card.body.addStretch(1)
        layout.addWidget(card, 1)
        return self._scroll(page)

    def _page_calls(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Calls",
                                    "View recent calls from your iPhone"))

        current = Card("Current Call")
        row = QHBoxLayout()
        row.setSpacing(18)
        self.call_art = Artwork(60, 0.5)
        row.addWidget(self.call_art, 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.call_who = label("No active call", 18, QFont.DemiBold)
        self.call_state = label("Calls appear here while they are running",
                                12, QFont.Normal, theme.TEXT_DIM)
        column.addWidget(self.call_who)
        column.addWidget(self.call_state)
        row.addLayout(column, 1)
        self.call_timer = label("", 32, QFont.Light, theme.GREEN)
        row.addWidget(self.call_timer, 0, Qt.AlignVCenter)
        current.body.addLayout(row)
        layout.addWidget(current)

        self.call_tabs = FilterTabs(["All", "Missed", "Incoming", "Outgoing"])
        self.call_tabs.changed.connect(self._set_call_filter)
        layout.addWidget(self.call_tabs)

        history = Card()
        self.calls_box = QVBoxLayout()
        self.calls_box.setSpacing(0)
        history.body.addLayout(self.calls_box)
        self.calls_empty = EmptyState("phone", "No recent calls",
                                      "Answered and missed calls land here.")
        history.body.addWidget(self.calls_empty)
        history.body.addStretch(1)
        layout.addWidget(history, 1)
        return self._scroll(page)

    def _set_call_filter(self, text: str) -> None:
        self._call_filter = text
        self._call_signature = None          # force a rebuild
        self.refresh()

    def _page_messages(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Messages",
                                    "Message notifications from your iPhone"))

        note = Card()
        line = label(
            "ANCS is read-only: the phone pushes notifications but accepts no "
            "replies, so messages can be read here and not sent. Sending would "
            "need iAP2, which requires an Apple MFi chip.",
            12, QFont.Normal, theme.TEXT_DIM)
        line.setWordWrap(True)
        note.body.addWidget(line)
        layout.addWidget(note)

        card = Card()
        self.messages_box = QVBoxLayout()
        self.messages_box.setSpacing(0)
        card.body.addLayout(self.messages_box)
        self.messages_empty = EmptyState(
            "chat", "No recent messages",
            "WhatsApp, Messages and Telegram notifications appear here.")
        card.body.addWidget(self.messages_empty)
        card.body.addStretch(1)
        layout.addWidget(card, 1)
        return self._scroll(page)

    # ------------------------------------------------------------------ #
    # device / settings
    # ------------------------------------------------------------------ #

    def _page_device(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Device Info",
                                    "What the phone reports over Bluetooth"))

        card = Card("Device")
        self.device_rows = {
            "name": InfoRow("device", "Device Name"),
            "model": InfoRow("device", "Model"),
            "manufacturer": InfoRow("apple", "Manufacturer"),
            "address": InfoRow("bluetooth", "Bluetooth Address"),
            "battery": InfoRow("battery", "Battery Level"),
            "state": InfoRow("signal", "Connection"),
            "seen": InfoRow("clock", "Last Seen"),
            "count": InfoRow("bell", "Notifications this session"),
        }
        for row in self.device_rows.values():
            card.body.addWidget(row)
        layout.addWidget(card)

        activity = Card("Activity")
        self.log_label = QLabel("")
        self.log_label.setFont(QFont("Consolas", 9))
        self.log_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self.log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        activity.body.addWidget(self.log_label)
        layout.addWidget(activity, 1)
        return self._scroll(page)

    def _page_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(PageHeader(
            "Settings", "Customize your iPhone Connect experience"))

        connection = Card("Connection")
        self.switch_startup = Switch()
        self.switch_startup.setChecked(startup.is_enabled())
        self.switch_startup.toggled.connect(self._toggle_startup)
        connection.body.addWidget(SettingRow(
            "check", "Start with Windows",
            "Launch automatically when you sign in", self.switch_startup))
        connection.body.addWidget(SettingRow(
            "bluetooth", "Paired device",
            "Pairing is managed in Windows Bluetooth settings",
            label("Windows", 12, QFont.DemiBold, theme.TEXT_DIM)))
        layout.addWidget(connection)

        notifications = Card("Notifications")
        self.switch_banners = Switch()
        self.switch_banners.setChecked(True)
        self.switch_banners.toggled.connect(self._toggle_banners)
        notifications.body.addWidget(SettingRow(
            "bell", "Show notifications from iPhone",
            "Desktop banners when this window is closed", self.switch_banners))
        layout.addWidget(notifications)

        layout.addWidget(self._card_devices())
        layout.addWidget(self._card_appearance())
        layout.addWidget(self._card_spotify())

        about = Card("About")
        self.about_rows = {
            "version": InfoRow("info", "App version", paths.APP_VERSION),
            "bluetooth": InfoRow("bluetooth", "Bluetooth", "Built-in (Windows)"),
            "paired": InfoRow("device", "Paired device"),
        }
        for row in self.about_rows.values():
            about.body.addWidget(row)
        layout.addWidget(about)
        layout.addStretch(1)
        return self._scroll(page)

    def _card_devices(self) -> Card:
        """
        Pick which phone to bridge.

        Pairing itself stays in Windows Bluetooth settings - ANCS needs a
        persistent bond and we deliberately never call pair(). This only
        chooses which bonded device to connect to, which matters if you have
        more than one iPhone, or after iOS rotates its address.
        """
        card = Card("Devices")
        note = label(
            "Pair the phone in Windows Bluetooth settings first, then scan "
            "here and pick it. Scanning briefly shares the radio, so the "
            "current link may blip.",
            11, QFont.Normal, theme.TEXT_DIM)
        note.setWordWrap(True)
        card.body.addWidget(note)

        self.device_current = InfoRow("bluetooth", "Using", "\u2014")
        card.body.addWidget(self.device_current)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.scan_button = QPushButton("Scan for devices")
        self.scan_button.setObjectName("pill")
        self.scan_button.setCursor(Qt.PointingHandCursor)
        self.scan_button.clicked.connect(self._start_scan)
        row.addWidget(self.scan_button)

        pair = QPushButton("Open Bluetooth settings")
        pair.setObjectName("pill")
        pair.setCursor(Qt.PointingHandCursor)
        pair.clicked.connect(shortcuts.open_bluetooth_settings)
        row.addWidget(pair)
        row.addStretch(1)
        card.body.addLayout(row)

        self.scan_box = QVBoxLayout()
        self.scan_box.setSpacing(8)
        card.body.addLayout(self.scan_box)
        return card

    def _start_scan(self) -> None:
        self.scan_button.setText("Scanning\u2026")
        self.scan_button.setEnabled(False)
        self._clear(self.scan_box)
        self.scan_requested.emit()

    def show_scan_results(self, results) -> None:
        """Called back on the Qt thread with whatever the scan found."""
        self.scan_button.setText("Scan for devices")
        self.scan_button.setEnabled(True)
        self._clear(self.scan_box)

        if not results:
            self.scan_box.addWidget(label(
                "Nothing found. Unlock the phone and keep its Bluetooth "
                "screen open, then scan again.", 11, QFont.Normal,
                theme.TEXT_FAINT))
            return

        current = (DEVICE.snapshot().get("address") or "").lower()
        for entry in results:
            use = QPushButton("In use" if entry["address"].lower() == current
                              else "Use")
            use.setObjectName("pill")
            use.setCursor(Qt.PointingHandCursor)
            use.setEnabled(entry["address"].lower() != current)
            use.clicked.connect(
                lambda _c, address=entry["address"]: self._use_device(address))
            self.scan_box.addWidget(SettingRow(
                "device", entry["name"],
                f"{entry['address']}  \u00b7  {entry['rssi']} dBm", use))

    def _use_device(self, address: str) -> None:
        applog.log(f"switching to {address}", "ui")
        self.device_selected.emit(address)
        self._clear(self.scan_box)
        self.scan_box.addWidget(label(
            f"Reconnecting to {address}\u2026", 11, QFont.Normal,
            theme.TEXT_DIM))

    def _card_appearance(self) -> Card:
        card = Card("Appearance")
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setFixedWidth(200)
        self.opacity_slider.setCursor(Qt.PointingHandCursor)
        self.opacity_slider.setValue(
            int(round(float(prefs.get("toast_opacity") or 1.0) * 100)))
        self.opacity_slider.valueChanged.connect(self._set_opacity)

        self.opacity_row = SettingRow(
            "settings", "Banner opacity",
            "How solid desktop banners look", self.opacity_slider)
        card.body.addWidget(self.opacity_row)

        theme_row = SettingRow(
            "settings", "Theme", "Dark only for now",
            label("Dark", 12, QFont.DemiBold, theme.TEXT_DIM))
        card.body.addWidget(theme_row)
        return card

    def _set_opacity(self, value: int) -> None:
        prefs.set("toast_opacity", value / 100)
        from qt_toast import MANAGER
        MANAGER.apply_opacity()

    def _card_spotify(self) -> Card:
        """
        AMS gives no artwork and no absolute volume. Spotify's Web API gives
        both, so linking an account is optional polish rather than a
        requirement - everything still works over Bluetooth alone.
        """
        card = Card("Spotify")
        card.header.insertWidget(0, icon_label("spotify", 18, theme.GREEN))

        note = label(
            "Optional. Adds album artwork and a working volume slider. "
            "Create an app at developer.spotify.com/dashboard, add "
            f"{spotify.REDIRECT_URI} as a redirect URI, and paste the Client "
            "ID below. Authorisation uses PKCE, so no client secret is stored.",
            11, QFont.Normal, theme.TEXT_DIM)
        note.setWordWrap(True)
        card.body.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.spotify_id = QLineEdit(spotify.CLIENT.client_id)
        self.spotify_id.setPlaceholderText("Spotify Client ID")
        self.spotify_id.setMinimumWidth(320)
        row.addWidget(self.spotify_id, 1)

        self.spotify_connect = QPushButton("Connect")
        self.spotify_connect.setObjectName("pill")
        self.spotify_connect.setCursor(Qt.PointingHandCursor)
        self.spotify_connect.clicked.connect(self._connect_spotify)
        row.addWidget(self.spotify_connect)

        disconnect = QPushButton("Disconnect")
        disconnect.setObjectName("pill")
        disconnect.setCursor(Qt.PointingHandCursor)
        disconnect.clicked.connect(self._disconnect_spotify)
        row.addWidget(disconnect)
        card.body.addLayout(row)

        self.spotify_status = InfoRow("info", "Status",
                                      spotify.CLIENT.status)
        card.body.addWidget(self.spotify_status)
        return card

    def _connect_spotify(self) -> None:
        spotify.CLIENT.set_client_id(self.spotify_id.text())
        self.spotify_connect.setText("Connecting\u2026")
        spotify.CLIENT.authorise(on_done=self._spotify_done)

    def _spotify_done(self, ok: bool, status: str) -> None:
        # Called from the auth thread; only touch state the timer reads.
        applog.log(f"Spotify: {status}", "spot")
        if ok:
            spotify.CLIENT.start()

    def _disconnect_spotify(self) -> None:
        spotify.CLIENT.disconnect()

    def _toggle_startup(self, checked: bool) -> None:
        actual = startup.set_enabled(checked)
        if actual != checked:
            self.switch_startup.blockSignals(True)
            self.switch_startup.setChecked(actual)
            self.switch_startup.blockSignals(False)

    def _toggle_banners(self, checked: bool) -> None:
        from status import STATUS
        STATUS.paused = not checked
        applog.log(f"banners {'on' if checked else 'off'}", "ui")

    def _clear_feed(self) -> None:
        FEED.clear()
        self._feed_signature = None
        self.refresh()

    # ------------------------------------------------------------------ #
    # in-window toasts
    # ------------------------------------------------------------------ #

    def push_toast(self, item: dict) -> None:
        row = QFrame()
        row.setObjectName("sunk")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        art = Artwork(38, 0.28)
        art.set_art(_pixmap_for(item.get("bundle_id", ""),
                                item.get("app", "")), "bell",
                    item.get("app", "?"), theme.CARD_HOVER)
        layout.addWidget(art, 0, Qt.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(label(item.get("title") or item.get("app", ""), 12,
                               QFont.DemiBold))
        if item.get("body"):
            body = label(item["body"], 11, QFont.Normal, theme.TEXT_DIM)
            body.setWordWrap(True)
            column.addWidget(body)
        layout.addLayout(column, 1)

        actions = item.get("actions") or []
        if actions:
            buttons = QVBoxLayout()
            buttons.setSpacing(6)
            for action in actions:
                kind = action[2] if len(action) > 2 else "neutral"
                colour = theme.ACTION_COLOURS.get(kind, theme.ACCENT)
                button = QPushButton(action[0])
                button.setCursor(Qt.PointingHandCursor)
                button.setFixedHeight(28)
                button.setStyleSheet(
                    f"QPushButton {{ background: {colour}; color: #FFFFFF;"
                    f" border: none; border-radius: 14px; padding: 0 16px;"
                    f" font-size: 11px; font-weight: 600; }}")
                callback = action[1] if len(action) > 1 else None
                button.clicked.connect(
                    lambda _c, cb=callback, r=row: self._toast_action(cb, r))
                buttons.addWidget(button)
            layout.addLayout(buttons, 0)

        self.toast_box.addWidget(row)
        self._toast_rows.append(row)
        while len(self._toast_rows) > 2:
            self._toast_rows.pop(0).setParent(None)
        QTimer.singleShot(item.get("hold_ms") or 9000,
                          lambda: self._drop_toast(row))

    def _toast_action(self, callback, row) -> None:
        self._drop_toast(row)
        if callback:
            try:
                callback()
            except Exception:
                pass

    def _drop_toast(self, row) -> None:
        if row in self._toast_rows:
            self._toast_rows.remove(row)
            row.setParent(None)

    # ------------------------------------------------------------------ #
    # refresh
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        device = DEVICE.snapshot()
        media = MEDIA.snapshot()
        call = calls.TRACKER.snapshot()

        connected = device["connected"]
        state_text = "Connected" if connected else device["state"]
        self.pill.set_state(connected, state_text)
        self.footer_dot.setStyleSheet(
            f"background: {theme.GREEN if connected else theme.AMBER};"
            f"border-radius: 5px;")
        self.footer_state.setText(state_text)
        self.footer_name.setText(f"{device['name']}'s iPhone")
        self.footer_address.setText(device["address"] or "")
        self.brand_sub.setText("Connected via Bluetooth" if connected
                               else "Waiting for the phone")

        self.device_title.setText(f"{device['name']}'s iPhone")
        self.device_sub.setText(device["model"] or "\u2014")
        self.phone.set_clock(time.strftime("%H:%M"),
                             time.strftime("%A, %d %B"))

        battery = device["battery"]
        pct_text = f"{battery}%" if battery is not None else "\u2014"
        self.hero_pill.set_level(battery)
        self.batt_pill.set_level(battery)
        self.hero_pct.setText(pct_text)
        self.batt_pct.setText(pct_text)
        self.hero_meter.set_fraction((battery or 0) / 100)
        self._sample_battery(battery)
        estimate = self._battery_estimate(battery)
        self.hero_estimate.setText(estimate)
        self.batt_note.setText(estimate)
        self.batt_spark.set_samples(self._battery_history)

        self.hero_rows["manufacturer"].set_value(device["manufacturer"])
        self.hero_rows["model"].set_value(device["model"])
        self.hero_rows["bluetooth"].value.setText(
            "Connected" if connected else "Disconnected")
        self.hero_rows["bluetooth"].caption.setText(device["address"] or "")

        for key, value in (("name", device["name"]), ("model", device["model"]),
                           ("manufacturer", device["manufacturer"]),
                           ("address", device["address"]),
                           ("battery", pct_text), ("state", state_text),
                           ("seen", ago(device["last_seen"])),
                           ("count", str(FEED.count()))):
            self.device_rows[key].set_value(value)

        self.about_rows["paired"].set_value(
            f"{device['name']} ({device['address']})" if device["address"]
            else device["name"])
        self.device_current.set_value(device["address"] or "not chosen yet")

        self.log_label.setText("\n".join(
            f"{time.strftime('%H:%M:%S', time.localtime(at))}  {tag:<5} {msg}"
            for at, tag, msg in applog.recent(16)))

        self._refresh_media(media)
        self._refresh_call(call)
        self._refresh_lists()

    def _sample_battery(self, battery) -> None:
        """
        Every five minutes, not every minute. The chart covers a session, and
        minute-resolution samples of a value that moves 1% an hour only make a
        flat line with more points in it.
        """
        if battery is None:
            return
        now = time.time()
        if self._first_battery is None:
            self._first_battery = (now, int(battery))
        if not self._battery_history or now - self._battery_sampled > 300:
            self._battery_history.append(int(battery))
            self._battery_sampled = now
            del self._battery_history[:-72]

    def _battery_estimate(self, battery) -> str:
        if battery is None:
            return "Waiting for the phone"
        if self._first_battery is None:
            return f"{battery}% now"
        start_at, start_level = self._first_battery
        hours = (time.time() - start_at) / 3600
        drop = start_level - int(battery)
        if hours < 0.25 or drop <= 0:
            return "Charging or steady"
        remaining = battery / (drop / hours)
        if remaining >= 24:
            return "More than a day remaining"
        return (f"About {int(remaining)}h {int((remaining % 1) * 60)}m "
                "remaining")

    def _refresh_media(self, media) -> None:
        playing = media["has_track"]
        title = (media["title"] or "Unknown track") if playing else "Nothing playing"
        artist = media["artist"] if playing else "Use the controls to play music"
        self.np_title.setText(title)
        self.np_artist.setText(artist)
        self.np_album.setText(media["album"] if playing else "")
        self.media_title.setText(title if playing else "No media playing")
        self.media_artist.setText(
            artist if playing
            else "Play something on your iPhone to see it here.")
        self.media_album.setText(media["album"] if playing else "")

        fraction = (media["elapsed"] / media["duration"]
                    if media["duration"] else 0)
        for meter in (self.np_meter, self.media_meter):
            meter.set_fraction(fraction)
        for widget in (self.np_elapsed, self.media_elapsed):
            widget.setText(_mmss(media["elapsed"]) if playing else "0:00")
        for widget in (self.np_total, self.media_total):
            widget.setText(_mmss(media["duration"]) if playing else "0:00")

        glyph = "pause" if media["playing"] else "play"
        self.np_play.setIcon(vicons.icon(glyph, 22, theme.BG))
        self.media_play.setIcon(vicons.icon(glyph, 22, theme.BG))

        # album art, which only Spotify can give us
        art = QPixmap(media["art_path"]) if media["art_path"] else None
        if art is not None and art.isNull():
            art = None
        self.np_art.set_art(art, "music")
        self.media_art.set_art(art, "music")

        volume = media["volume"]
        self.volume_meter.set_fraction(volume or 0)
        self.volume_text.setText(
            f"{media['player'] or 'Player'} \u00b7 {int((volume or 0) * 100)}%"
            if volume is not None
            else "Volume unknown until the phone reports it")
        if volume is None:
            self.np_hint.setText("")
        else:
            source = ("Spotify" if media["source"] == "spotify"
                      else "Bluetooth")
            self.np_hint.setText(f"Volume {int(volume * 100)}% \u00b7 {source}")

        self._refresh_lyrics(media)
        self.spotify_status.set_value(spotify.CLIENT.status)
        self.spotify_connect.setText(
            "Reconnect" if spotify.CLIENT.connected else "Connect")

    def _refresh_lyrics(self, media) -> None:
        """
        Spotify has no public lyrics endpoint, so these come from LRCLIB -
        free, key-less, and usually time-synced.
        """
        if not media["has_track"]:
            self.lyrics_view.show_message("Nothing playing")
            self.lyrics_source.setText("")
            return

        found = lyrics.request(media["title"], media["artist"],
                               media["album"], media["duration"])
        if found is None:
            self.lyrics_view.show_message("Looking for lyrics\u2026")
            self.lyrics_source.setText("")
            return
        if not found["found"]:
            self.lyrics_view.show_message("No lyrics found for this track")
            self.lyrics_source.setText("LRCLIB")
            return
        if found["synced"]:
            self.lyrics_view.show_synced(found["synced"], media["elapsed"])
            self.lyrics_source.setText("LRCLIB \u00b7 synced")
        else:
            self.lyrics_view.show_plain(found["plain"])
            self.lyrics_source.setText("LRCLIB \u00b7 unsynced")

    def _refresh_call(self, call) -> None:
        if call["state"] in ("active", "ringing"):
            self.call_who.setText(call["who"])
            self.call_art.set_art(None, "phone", call["who"], theme.GREEN)
            if call["state"] == "active":
                self.call_timer.setText(call["duration_text"])
                self.call_state.setText(
                    f"{call['direction'].title()} \u00b7 {call['app']}")
            else:
                self.call_timer.setText("")
                self.call_state.setText("Ringing\u2026")
        else:
            self.call_who.setText("No active call")
            self.call_timer.setText("")
            self.call_state.setText("Calls appear here while they are running")
            self.call_art.set_art(None, "phone")

    def _refresh_lists(self) -> None:
        """Rebuilt only on change - a full teardown every second flickered."""
        items = FEED.recent(40)
        signature = (FEED.count(), items[0].at if items else 0)
        if signature != self._feed_signature:
            self._feed_signature = signature
            messages = [i for i in items if i.bundle_id in MESSAGE_APPS][:14]
            self.feed_empty.setVisible(not items)
            self.all_empty.setVisible(not items)
            self.messages_empty.setVisible(not messages)
            self.messages_dash_empty.setVisible(not messages)
            self._fill(self.feed_box, items[:3])
            self._fill(self.all_box, items[:24])
            self._fill(self.messages_box, messages)
            self._fill(self.messages_dash_box, messages[:3])

        history = calls.TRACKER.recent(20)
        if self._call_filter == "Missed":
            history = [c for c in history if c.state == "missed"]
        elif self._call_filter == "Incoming":
            history = [c for c in history if c.direction == "incoming"]
        elif self._call_filter == "Outgoing":
            history = [c for c in history if c.direction == "outgoing"]

        call_signature = (self._call_filter,
                          tuple((c.uid, c.state, int(c.duration))
                                for c in history))
        if call_signature != self._call_signature:
            self._call_signature = call_signature
            self.calls_empty.setVisible(not history)
            self.calls_summary_empty.setVisible(not history)
            self._clear(self.calls_box)
            self._clear(self.calls_summary_box)
            for entry in history[:12]:
                self.calls_box.addWidget(self._call_row(entry))
            for entry in history[:3]:
                self.calls_summary_box.addWidget(self._call_row(entry))

    def _clear(self, box) -> None:
        while box.count():
            child = box.takeAt(0)
            if child.widget():
                child.widget().setParent(None)

    def _fill(self, box, items) -> None:
        self._clear(box)
        for item in items:
            box.addWidget(FeedRow(item, _pixmap_for(item.bundle_id, item.app)))

    def _call_row(self, call) -> QFrame:
        row = QFrame()
        row.setFixedHeight(58)
        row.setStyleSheet(
            "QFrame { background: transparent; border-radius: 10px; }"
            f"QFrame:hover {{ background: {theme.CARD_HOVER}; }}")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 10, 6)
        layout.setSpacing(13)

        missed = call.state == "missed"
        colour = theme.RED if missed else theme.GREEN
        avatar = Artwork(38, 0.5)
        avatar.set_art(None, "phone", call.label(), colour)
        layout.addWidget(avatar, 0, Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(label(call.label(), 12, QFont.DemiBold))
        line = QHBoxLayout()
        line.setSpacing(7)
        line.addWidget(icon_label("phone_missed" if missed else "phone", 13,
                                  colour), 0, Qt.AlignVCenter)
        detail = "Missed" if missed else call.direction.title()
        line.addWidget(label(
            f"{detail} \u00b7 {ago(call.ended_at or call.ringing_at)}",
            11, QFont.Normal, theme.TEXT_DIM))
        line.addStretch(1)
        column.addLayout(line)
        layout.addLayout(column, 1)

        if not missed and call.started_at:
            layout.addWidget(label(call.duration_text, 12, QFont.DemiBold,
                                   theme.TEXT_DIM), 0, Qt.AlignVCenter)
        return row
