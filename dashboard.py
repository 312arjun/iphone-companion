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

import ctypes
import time

try:                          # Windows only; the app does not run elsewhere,
    import ctypes.wintypes    # but an import error here must not be fatal
    _WINTYPES = True
except (ImportError, ValueError):
    _WINTYPES = False

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QPushButton, QScrollArea, QSizeGrip, QSlider,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

import ams
import appicon
import applog
import calls
import desktop
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
from widgets import (ActivityRow, Artwork, BatteryPill, Card,
                     DecorArt, EmptyState,
                     FeedRow, FilterTabs, InfoBanner, InfoRow, InfoTile,
                     LyricsView,
                     Meter, NavButton, PageHeader, PhoneMock, SectionHeader,
                     SettingRow,
                     SaveNotice, SourceChip, Sparkline, StackRow, StatusPill,
                     Switch,
                     Waveform,
                     TileButton, ghost_button, icon_label, label, restyle_images,
                     restyle_labels)

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
        # Sentinel, so the first refresh always builds the activity rows.
        self._activity_signature = object()
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

    # Windows sends WM_NCHITTEST to ask "what part of the window is this
    # point?". A frameless window answers HTCLIENT everywhere, which is why
    # the edges are dead. Answering with the edge codes hands resizing back
    # to the OS, so it gets the correct cursors, snapping and DPI behaviour
    # for free rather than reimplementing drag-resize in Python.
    _WM_NCHITTEST = 0x0084
    _HT = {                       # (left, top, right, bottom) -> code
        (True, True, False, False): 13,    # HTTOPLEFT
        (False, True, True, False): 14,    # HTTOPRIGHT
        (True, False, False, True): 16,    # HTBOTTOMLEFT
        (False, False, True, True): 17,    # HTBOTTOMRIGHT
        (True, False, False, False): 10,   # HTLEFT
        (False, False, True, False): 11,   # HTRIGHT
        (False, True, False, False): 12,   # HTTOP
        (False, False, False, True): 15,   # HTBOTTOM
    }
    RESIZE_BORDER = 6             # px of grab area inside each edge

    def nativeEvent(self, event_type, message):
        if (not _WINTYPES or event_type != "windows_generic_MSG"
                or self.isMaximized()):
            return super().nativeEvent(event_type, message)
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return super().nativeEvent(event_type, message)
        if msg.message != self._WM_NCHITTEST:
            return super().nativeEvent(event_type, message)

        # lParam packs screen coords as two signed 16-bit halves; masking
        # without sign-extending breaks on a monitor left of the primary,
        # where x is negative.
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        local = self.mapFromGlobal(QPoint(x, y))
        border = self.RESIZE_BORDER
        edges = (local.x() <= border,
                 local.y() <= border,
                 local.x() >= self.width() - border,
                 local.y() >= self.height() - border)
        code = self._HT.get(edges)
        if code is not None:
            return True, code
        return super().nativeEvent(event_type, message)

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
        # Styled by object name rather than inline, so switching palette
        # repaints it. An inline setStyleSheet(f"...{theme.BG}") bakes in
        # whichever mode was active when the window was built.
        bar.setObjectName("titlebar")
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
        return self._scroll(page)

    def _card_messages(self) -> Card:
        card = Card("Messages", image="message")
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
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self.device_title = label("iPhone", 23, QFont.DemiBold)
        title_row.addWidget(self.device_title, 0, Qt.AlignVCenter)
        # Its own pill beside the name, as the mockup has it. The titlebar
        # pill is still there, but on this card the state belongs next to
        # the device it describes.
        self.hero_pill_state = StatusPill()
        title_row.addWidget(self.hero_pill_state, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        details.addLayout(title_row)
        self.device_sub = label("", 12, QFont.Normal, theme.TEXT_DIM)
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

        # Six tiles in a 3x2 grid: the three facts about the phone on top,
        # the three actions that actually work beneath. The Shortcuts card
        # that used to hold them is gone - the actions belong next to the
        # device they act on, and the hero had dead space below the facts.
        #
        # "Lock iPhone" is dropped rather than shown disabled. A button that
        # explains why it cannot work is still a button that cannot work,
        # and it was the only greyed tile on the page.
        facts = QGridLayout()
        facts.setHorizontalSpacing(10)
        facts.setVerticalSpacing(10)
        self.hero_rows = {
            "manufacturer": StackRow("apple", "\u2014", "Manufacturer"),
            "model": StackRow("device", "\u2014", "Model"),
            "bluetooth": StackRow("bluetooth", "\u2014", "", theme.ACCENT),
        }
        for index, stack in enumerate(self.hero_rows.values()):
            stack.setObjectName("factTile")
            stack.setMinimumHeight(58)
            stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            facts.addWidget(stack, 0, index)

        actions = (
            ("lock", "Lock PC", "Lock this computer", theme.ACCENT,
             shortcuts.lock_pc),
            ("bluetooth", "Bluetooth", "Windows settings", theme.ACCENT,
             shortcuts.open_bluetooth_settings),
            ("signal", "Reconnect", "Re-establish the link", theme.GREEN,
             self._reconnect),
        )
        for index, (glyph, title, caption, colour, action) in enumerate(actions):
            tile = StackRow(glyph, title, caption, colour)
            tile.setObjectName("actionTile")
            tile.setMinimumHeight(58)
            tile.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            tile.setCursor(Qt.PointingHandCursor)
            # StackRow is a QFrame, so it has no clicked signal - the press
            # is taken on mouseReleaseEvent instead of wrapping every tile
            # in a button and restyling it back to look like a tile.
            tile.mouseReleaseEvent = (
                lambda _e, fn=action: fn())
            facts.addWidget(tile, 1, index)

        for column in range(3):
            facts.setColumnStretch(column, 1)
        # Both rows stretch and the tiles expand vertically, so the six of
        # them fill the card down to the bottom of the phone render instead
        # of sitting in a band with dead space beneath. The old
        # details.addStretch() is gone - it was what created that gap by
        # absorbing all the spare height itself.
        facts.setRowStretch(0, 1)
        facts.setRowStretch(1, 1)
        details.addLayout(facts, 1)
        row.addLayout(details, 1)
        card.body.addLayout(row)
        return card

    def _card_now_playing(self) -> Card:
        """
        Transport is prev / play / next only - shuffle, repeat and like were
        dropped because Spotify never advertised them in the AMS command list,
        so they were decoration. Volume lives here now.
        """
        card = Card("Now Playing", image="wave-sound")
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
        self.np_play.setIcon(vicons.icon("play", 22, theme.ACCENT))
        # 54, matching the Media page: theme.py rounds #round with a
        # 27px radius, and a radius over half the widget makes Qt
        # draw a square instead of a circle.
        self.np_play.setFixedSize(54, 54)
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
        card = Card("Recent Notifications", image="notification-bell")
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
        card = Card("Calls", image="phone-call")
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
        card = Card("Battery History", image="usage-history")
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

        playing = Card("Now Playing", bar=True)
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
        # AMS reports the player name, so the chip is real information, not a
        # guess. It matters because the transport acts on whatever is
        # playing rather than on a chosen app.
        self.media_source = SourceChip()
        column.addWidget(self.media_source, 0, Qt.AlignLeft)
        column.addStretch(1)
        row.addLayout(column, 1)
        # Decorative, and only while something is playing - see the Waveform
        # docstring. There is no audio stream over BLE to measure.
        self.media_wave = Waveform(300, 72)
        row.addWidget(self.media_wave, 0, Qt.AlignVCenter)
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
        # Previous / play / next only. Shuffle and repeat were removed
        # deliberately: AMS advances them blind, with no way to read back
        # the resulting state, so the buttons could never show whether
        # shuffle was on. A control that cannot report its own state is
        # worse than no control.
        previous = ghost_button("previous", 21, theme.TEXT, 44)
        previous.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_PREVIOUS))
        transport.addWidget(previous)

        self.media_play = QPushButton()
        self.media_play.setObjectName("round")
        self.media_play.setIcon(vicons.icon("play", 22, theme.ACCENT))
        self.media_play.setFixedSize(54, 54)
        self.media_play.setCursor(Qt.PointingHandCursor)
        self.media_play.clicked.connect(
            lambda: self.media_command.emit(ams.CMD_TOGGLE))
        transport.addWidget(self.media_play)

        nxt = ghost_button("next", 21, theme.TEXT, 44)
        nxt.clicked.connect(lambda: self.media_command.emit(ams.CMD_NEXT))
        transport.addWidget(nxt)
        transport.addStretch(1)
        playing.body.addLayout(transport)

        playing.body.addWidget(SettingRow(
            "output", "Output", "iPhone - audio stays on the phone over BLE"))
        layout.addWidget(playing)

        volume = Card("Volume", bar=True)
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

        words = Card("Lyrics", bar=True)
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
        clear = QPushButton("  Clear All")
        clear.setObjectName("pill")
        clear.setCursor(Qt.PointingHandCursor)
        clear.setIcon(vicons.icon("trash", 15, theme.TEXT_DIM))
        clear.clicked.connect(self._clear_feed)
        head.addWidget(clear, 0, Qt.AlignBottom)
        layout.addLayout(head)

        # Search runs against the database, not the 120-item deque, so it
        # reaches the whole retained history rather than just what is on
        # screen. An empty box falls back to the live feed.
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search notifications\u2026")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        layout.addWidget(self.search_box)

        # All / Messages / Calls, rather than the mockup's Apps/Social/
        # Shopping. Those would need a bundle-to-category table invented and
        # maintained by hand as apps are installed; these three map to data
        # the phone already gives us - MESSAGE_APPS and the call style.
        self.notif_filter = "All"
        tabs = FilterTabs(["All", "Messages", "Calls"])
        tabs.changed.connect(self._set_notif_filter)
        layout.addWidget(tabs)

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

    def _set_notif_filter(self, name: str) -> None:
        self.notif_filter = name
        self._fill_all_list()

    @staticmethod
    def _matches_notif_filter(item, name: str) -> bool:
        if name == "Messages":
            return item.bundle_id in MESSAGE_APPS
        if name == "Calls":
            # style is set for call toasts; category covers the ANCS values
            # for rows restored from history, where style may be absent.
            return (item.style == "call"
                    or "call" in (item.category or "").lower())
        return True

    def _page_calls(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("Calls",
                                    "View recent calls from your iPhone"))

        current = Card()
        row = QHBoxLayout()
        row.setSpacing(18)
        self.call_art = Artwork(60, 0.5)
        row.addWidget(self.call_art, 0, Qt.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.call_who = label("No active call", 18, QFont.DemiBold)
        # Doubles as the explanatory note when idle and as live call state
        # when one is running. A SectionHeader above this said the same
        # thing twice, which is why there isn't one.
        self.call_state = label("Calls appear here while they are running",
                                12, QFont.Normal, theme.TEXT_DIM)
        column.addWidget(self.call_who)
        column.addWidget(self.call_state)
        row.addLayout(column, 1)
        # Decorative only - see the Waveform docstring. There is no audio
        # stream over BLE to measure.
        self.call_wave = Waveform(240, 54)
        row.addWidget(self.call_wave, 0, Qt.AlignVCenter)
        self.call_timer = label("", 32, QFont.Light, theme.GREEN)
        row.addWidget(self.call_timer, 0, Qt.AlignVCenter)
        row.addWidget(DecorArt("phone", 150, 104), 0, Qt.AlignVCenter)
        current.body.addLayout(row)
        layout.addWidget(current)

        filters = QHBoxLayout()
        filters.setSpacing(12)
        self.call_tabs = FilterTabs(["All", "Missed", "Incoming", "Outgoing"])
        self.call_tabs.changed.connect(self._set_call_filter)
        filters.addWidget(self.call_tabs, 1)
        self.call_search = QLineEdit()
        self.call_search.setObjectName("searchBox")
        self.call_search.setPlaceholderText("Search calls\u2026")
        self.call_search.setClearButtonEnabled(True)
        self.call_search.setFixedWidth(280)
        self.call_search.textChanged.connect(self._on_call_search)
        filters.addWidget(self.call_search, 0)
        layout.addLayout(filters)

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

    def _on_call_search(self, _text: str = "") -> None:
        self._call_signature = None
        self.refresh()

    def _matches_call_search(self, call) -> bool:
        query = ""
        if getattr(self, "call_search", None) is not None:
            query = (self.call_search.text() or "").strip().lower()
        if not query:
            return True
        # Name and number both, because a call from an unknown number has no
        # name to match and searching a number is the obvious thing to try.
        return query in (call.label() or "").lower()

    def _page_messages(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(PageHeader("Messages",
                                  "Message notifications from your iPhone"))
        head.addStretch(1)
        self.msg_search = QLineEdit()
        self.msg_search.setObjectName("searchBox")
        self.msg_search.setPlaceholderText("Search messages\u2026")
        self.msg_search.setClearButtonEnabled(True)
        self.msg_search.setFixedWidth(300)
        self.msg_search.textChanged.connect(self._on_msg_search)
        head.addWidget(self.msg_search, 0, Qt.AlignBottom)
        layout.addLayout(head)

        # Stated on the page where someone would otherwise go hunting for a
        # reply box, rather than buried in the README.
        layout.addWidget(InfoBanner(
            "info",
            "Messages are read-only. The phone pushes notifications but "
            "accepts no replies, so messages can be read here and not sent.",
            "Sending would need iAP2, which requires an Apple MFi chip.",
            decor="messages"))

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

    def _on_msg_search(self, _text: str = "") -> None:
        self._feed_signature = None          # force the list to rebuild
        self._refresh_lists()

    def _matches_msg_search(self, item) -> bool:
        query = ""
        if getattr(self, "msg_search", None) is not None:
            query = (self.msg_search.text() or "").strip().lower()
        if not query:
            return True
        # Sender and body both: you search for either who sent it or what
        # it said, and there is no way to know which the user meant.
        return (query in (item.title or "").lower()
                or query in (item.body or "").lower())

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

        # --- hero: phone render, name, and the info grid beside it ------ #
        hero = Card()
        top = QHBoxLayout()
        top.setSpacing(22)
        # Its own instance, not the Overview one - a QWidget can only have
        # one parent, so sharing it would move it off the Overview page.
        self.device_phone = PhoneMock()
        top.addWidget(self.device_phone, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(12)
        title_row = QHBoxLayout()
        # Matches the mockup: the device name is the hero of this card,
        # so it outranks the card and tile text around it.
        self.device_title = label("iPhone", 26, QFont.Bold)
        title_row.addWidget(self.device_title, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        self.device_seen = label("", 11, QFont.Normal, theme.TEXT_FAINT)
        title_row.addWidget(self.device_seen, 0, Qt.AlignVCenter)
        right.addLayout(title_row)
        self.device_model = label("", 12, QFont.Normal, theme.TEXT_DIM)
        right.addWidget(self.device_model)

        # Two columns, as the mockup has it. A grid rather than two nested
        # VBoxes so the rows stay aligned across columns when one value
        # wraps or an icon is a different size.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.device_rows = {
            "name": InfoTile("device", "Device Name"),
            "model": InfoTile("device", "Model"),
            "manufacturer": InfoTile("apple", "Manufacturer"),
            "address": InfoTile("bluetooth", "Bluetooth Address"),
            "battery": InfoTile("battery", "Battery Level", glyph_colour=theme.GREEN),
            "state": InfoTile("signal", "Connection", glyph_colour=theme.GREEN),
            "seen": InfoTile("clock", "Last Seen"),
            "count": InfoTile("bell", "Notifications this session",
                              glyph_colour=theme.AMBER),
        }
        order = ["name", "model", "manufacturer", "address",
                 "battery", "state", "seen", "count"]
        for index, key in enumerate(order):
            grid.addWidget(self.device_rows[key], index % 4, index // 4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        right.addLayout(grid)
        top.addLayout(right, 1)
        hero.body.addLayout(top)
        layout.addWidget(hero)

        # --- activity log ----------------------------------------------- #
        activity = Card()
        clear = QPushButton("  Clear")
        clear.setObjectName("pill")
        clear.setCursor(Qt.PointingHandCursor)
        clear.setIcon(vicons.icon("trash", 15, theme.TEXT_DIM))
        clear.setToolTip("Clear notification history")
        clear.clicked.connect(self._clear_feed)
        activity.body.addWidget(SectionHeader(
            "info", "Activity",
            "Live log from your iPhone over Bluetooth. Silenced entries are "
            "dimmed, not hidden.", clear))
        self.activity_box = QVBoxLayout()
        self.activity_box.setSpacing(0)
        activity.body.addLayout(self.activity_box)
        self.activity_empty = EmptyState(
            "bell", "Nothing yet", "Notifications appear here as they arrive.")
        activity.body.addWidget(self.activity_empty)
        activity.body.addStretch(1)
        layout.addWidget(activity, 1)
        return self._scroll(page)

    def _fill_activity(self) -> None:
        """Newest first, capped: the log is for glancing, not scrolling."""
        items = FEED.recent(40)[:18]
        self.activity_empty.setVisible(not items)
        while self.activity_box.count():
            old = self.activity_box.takeAt(0).widget()
            if old is not None:
                old.deleteLater()
        for index, item in enumerate(items):
            self.activity_box.addWidget(ActivityRow(
                item, _pixmap_for(item.bundle_id, item.app),
                first=index == 0, last=index == len(items) - 1))

    def _page_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 0, 26, 24)
        layout.setSpacing(16)
        head = QHBoxLayout()
        head.addWidget(PageHeader(
            "Settings", "Customize your iPhone Connect experience"))
        head.addStretch(1)
        # Where the mockup put a Save Changes button. Settings apply
        # instantly, so the space is better spent confirming the write than
        # asking for it.
        self.save_notice = SaveNotice()
        head.addWidget(self.save_notice, 0, Qt.AlignBottom)
        layout.addLayout(head)

        connection = Card("Connection", "bluetooth")
        self.switch_startup = Switch()
        self.switch_startup.setChecked(startup.is_enabled())
        self.switch_startup.toggled.connect(self._toggle_startup)
        connection.body.addWidget(SettingRow(
            "check", "Start with Windows",
            "Launch automatically when you sign in", self.switch_startup))

        self.switch_desktop = Switch()
        self.switch_desktop.setChecked(desktop.exists())
        self.switch_desktop.toggled.connect(self._toggle_desktop)
        self.desktop_row = SettingRow(
            "device", "Desktop shortcut",
            "Put a shortcut to this app on your desktop",
            self.switch_desktop)
        connection.body.addWidget(self.desktop_row)

        connection.body.addWidget(SettingRow(
            "bluetooth", "Paired device",
            "Pairing is managed in Windows Bluetooth settings",
            label("Windows", 12, QFont.DemiBold, theme.TEXT_DIM)))

        notifications = Card("Notifications", image="notification-bell")
        self.switch_banners = Switch()
        self.switch_banners.setChecked(True)
        self.switch_banners.toggled.connect(self._toggle_banners)
        notifications.body.addWidget(SettingRow(
            "bell", "Show notifications from iPhone",
            "Desktop banners when this window is closed", self.switch_banners))

        # Connection and Notifications share the first row.
        first = QHBoxLayout()
        first.setSpacing(16)
        first.addWidget(connection, 1)
        first.addWidget(notifications, 1)
        layout.addLayout(first)

        # Two columns, as the mockup has it. Settings had grown to seven
        # stacked cards, which meant scrolling past Connection every time to
        # reach Spotify. Paired left-to-right by weight so the columns end
        # up roughly level: the tall Notification rules card sits opposite
        # the three short ones.
        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        left.addWidget(self._card_rules())
        right.addWidget(self._card_devices())
        right.addWidget(self._card_appearance())
        right.addWidget(self._card_spotify())
        left.addStretch(1)
        right.addStretch(1)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)

        about = Card("About", "info")
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

    def _card_rules(self) -> Card:
        """
        Which notifications get through, and when.

        The engine lives in rules.py; this only reads and writes prefs. App
        pickers are built from FEED.apps(), the bundles actually seen on this
        phone, because nobody can be asked to type "net.whatsapp.WhatsApp"
        from memory.
        """
        card = Card("Notification rules", "check")

        note = label(
            "Filtered notifications are still recorded - they just do not "
            "raise a banner. Calls are never filtered.",
            11, QFont.Normal, theme.TEXT_DIM)
        note.setWordWrap(True)
        card.body.addWidget(note)

        # --- history -------------------------------------------------- #
        self.switch_history = Switch()
        self.switch_history.setChecked(bool(prefs.get("save_history")))
        self.switch_history.toggled.connect(
            lambda on: self._save("save_history", bool(on)))
        card.body.addWidget(SettingRow(
            "clock", "Save notification history",
            "Keep the last 10,000 notifications between restarts",
            self.switch_history))

        # --- quiet hours ---------------------------------------------- #
        self.switch_quiet = Switch()
        self.switch_quiet.setChecked(bool(prefs.get("quiet_enabled")))
        self.switch_quiet.toggled.connect(
            lambda on: self._save("quiet_enabled", bool(on)))
        card.body.addWidget(SettingRow(
            "bell", "Quiet hours",
            "Silence banners overnight - priority apps still get through",
            self.switch_quiet))

        times = QHBoxLayout()
        times.setSpacing(8)
        times.addWidget(label("From", 12, QFont.Normal, theme.TEXT_DIM))
        self.quiet_start = self._time_box("quiet_start")
        times.addWidget(self.quiet_start)
        times.addWidget(label("to", 12, QFont.Normal, theme.TEXT_DIM))
        self.quiet_end = self._time_box("quiet_end")
        times.addWidget(self.quiet_end)
        times.addStretch(1)
        card.body.addLayout(times)

        return self._rules_filters(card)

    def _time_box(self, key: str) -> QComboBox:
        """Half-hour picker. A combo, not free text, so the stored value is
        always parseable and rules.py never has to fall back."""
        box = QComboBox()
        box.setObjectName("pill")
        box.setCursor(Qt.PointingHandCursor)
        choices = ["%02d:%02d" % (h, m)
                   for h in range(24) for m in (0, 30)]
        box.addItems(choices)
        current = prefs.get(key) or ("22:00" if "start" in key else "07:00")
        if current in choices:
            box.setCurrentText(current)
        box.currentTextChanged.connect(
            lambda text: self._save(key, text))
        return box

    def _rules_filters(self, card: Card) -> Card:
        """App filter, priority apps and keyword rules. Split out of
        _card_rules purely to keep either method readable."""
        # --- app filter mode ------------------------------------------ #
        self.filter_mode = QComboBox()
        self.filter_mode.setObjectName("pill")
        self.filter_mode.setCursor(Qt.PointingHandCursor)
        self._filter_modes = ["off", "blocklist", "allowlist"]
        self.filter_mode.addItems(["Show all apps",
                                   "Silence the apps I pick",
                                   "Only the apps I pick"])
        mode = prefs.get("app_filter_mode") or "off"
        if mode in self._filter_modes:
            self.filter_mode.setCurrentIndex(self._filter_modes.index(mode))
        self.filter_mode.currentIndexChanged.connect(self._set_filter_mode)
        card.body.addWidget(SettingRow(
            "bell", "App filter", "Which apps may raise a banner",
            self.filter_mode))

        self.app_picker = self._app_list(self._filter_key(), "app_picker")
        card.body.addWidget(self.app_picker)

        # --- priority apps -------------------------------------------- #
        card.body.addWidget(label(
            "Priority apps  \u00b7  these ignore quiet hours",
            12, QFont.DemiBold, theme.TEXT))
        self.priority_picker = self._app_list("priority_apps",
                                              "priority_picker")
        card.body.addWidget(self.priority_picker)

        # --- keyword rules -------------------------------------------- #
        card.body.addWidget(label(
            "Word rules  \u00b7  first match wins",
            12, QFont.DemiBold, theme.TEXT))
        hint = label(
            "Matches anywhere in the title or body, ignoring case. Plain "
            "words, not patterns.", 11, QFont.Normal, theme.TEXT_DIM)
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        entry = QHBoxLayout()
        entry.setSpacing(8)
        self.rule_word = QLineEdit()
        self.rule_word.setPlaceholderText("word or phrase, e.g. sale")
        entry.addWidget(self.rule_word, 1)
        self.rule_action = QComboBox()
        self.rule_action.setObjectName("pill")
        self._rule_actions = ["silent", "drop", "show"]
        self.rule_action.addItems(["Silence it", "Discard it", "Always show"])
        entry.addWidget(self.rule_action)
        add = QPushButton("Add")
        add.setObjectName("pill")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._add_rule)
        entry.addWidget(add)
        card.body.addLayout(entry)

        self.rule_list = QListWidget()
        self.rule_list.setObjectName("ruleList")
        self.rule_list.setMaximumHeight(120)
        self.rule_list.itemDoubleClicked.connect(self._remove_rule)
        card.body.addWidget(self.rule_list)
        card.body.addWidget(label(
            "Double-click a rule to remove it.",
            11, QFont.Normal, theme.TEXT_FAINT))
        self._refresh_rules()
        return card

    def _filter_key(self) -> str:
        mode = prefs.get("app_filter_mode") or "off"
        return "app_allowlist" if mode == "allowlist" else "app_blocklist"

    def _app_list(self, key: str, name: str) -> QListWidget:
        """
        A checkable list of apps actually seen on this phone.

        Built from FEED.apps() rather than a hand-typed bundle id. Any
        bundle already stored in the pref but not yet seen is added too, so
        a setting made before history existed is never silently discarded.
        """
        widget = QListWidget()
        widget.setObjectName(name)
        widget.setMaximumHeight(130)
        seen = FEED.apps()
        chosen = list(prefs.get(key) or [])
        known = {entry["bundle_id"] for entry in seen}
        for bundle in chosen:
            if bundle and bundle not in known:
                seen.append({"bundle_id": bundle, "app": bundle, "count": 0})
        if not seen:
            widget.addItem(QListWidgetItem(
                "No apps seen yet - notifications will populate this"))
            widget.setEnabled(False)
            return widget
        for entry in seen:
            text = entry["app"] or entry["bundle_id"]
            if entry.get("count"):
                text += "   (%d)" % entry["count"]
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, entry["bundle_id"])
            item.setCheckState(Qt.Checked if entry["bundle_id"] in chosen
                               else Qt.Unchecked)
            widget.addItem(item)
        widget.itemChanged.connect(lambda _i, k=key, w=widget:
                                   self._save_app_list(k, w))
        # Recorded so _set_filter_mode knows there is something to
        # disconnect. Only the app_picker is ever re-pointed; the priority
        # list keeps its original key for life.
        if name == "app_picker":
            self._picker_connected = True
        return widget

    def _save_app_list(self, key: str, widget: QListWidget) -> None:
        chosen = []
        for row in range(widget.count()):
            item = widget.item(row)
            if item.checkState() == Qt.Checked:
                chosen.append(item.data(Qt.UserRole))
        self._save(key, [b for b in chosen if b])

    def _set_filter_mode(self, index: int) -> None:
        """
        Switching mode also repoints the picker at the other list.

        Allow-list and block-list are stored separately on purpose: flipping
        between them should not silently reinterpret "apps I silenced" as
        "the only apps allowed", which would be the opposite of the intent.
        """
        mode = self._filter_modes[index] if 0 <= index < 3 else "off"
        self._save("app_filter_mode", mode)
        key = self._filter_key()
        chosen = set(prefs.get(key) or [])
        self.app_picker.blockSignals(True)
        for row in range(self.app_picker.count()):
            item = self.app_picker.item(row)
            bundle = item.data(Qt.UserRole)
            if bundle is None:
                continue
            item.setCheckState(Qt.Checked if bundle in chosen
                               else Qt.Unchecked)
        self.app_picker.blockSignals(False)
        # Tracked rather than guarded by try/except: libpyside emits a
        # RuntimeWarning for a disconnect with nothing attached instead of
        # raising, so the exception handler never fired and the warning
        # still reached the log on every mode change.
        if getattr(self, "_picker_connected", False):
            self.app_picker.itemChanged.disconnect()
            self._picker_connected = False
        usable = (self.app_picker.count() > 0
                  and self.app_picker.item(0).data(Qt.UserRole) is not None)
        if usable:
            self.app_picker.itemChanged.connect(
                lambda _i, k=key, w=self.app_picker: self._save_app_list(k, w))
            self._picker_connected = True
        self.app_picker.setEnabled(mode != "off" and usable)

    def _add_rule(self) -> None:
        word = (self.rule_word.text() or "").strip()
        if not word:
            return
        action = self._rule_actions[max(0, self.rule_action.currentIndex())]
        rules_list = list(prefs.get("keyword_rules") or [])
        rules_list.append({"pattern": word, "action": action})
        self._save("keyword_rules", rules_list)
        self.rule_word.clear()
        self._refresh_rules()

    def _remove_rule(self, item: QListWidgetItem) -> None:
        index = self.rule_list.row(item)
        rules_list = list(prefs.get("keyword_rules") or [])
        if 0 <= index < len(rules_list):
            rules_list.pop(index)
            self._save("keyword_rules", rules_list)
            self._refresh_rules()

    def _refresh_rules(self) -> None:
        wording = {"silent": "silence", "drop": "discard", "show": "show"}
        self.rule_list.clear()
        for rule in prefs.get("keyword_rules") or []:
            if not isinstance(rule, dict):
                continue
            self.rule_list.addItem(QListWidgetItem(
                '"%s"   \u2192   %s' % (rule.get("pattern", ""),
                                        wording.get(rule.get("action"),
                                                    rule.get("action", "")))))

    def _card_devices(self) -> Card:
        """
        Pick which phone to bridge.

        Pairing itself stays in Windows Bluetooth settings - ANCS needs a
        persistent bond and we deliberately never call pair(). This only
        chooses which bonded device to connect to, which matters if you have
        more than one iPhone, or after iOS rotates its address.
        """
        card = Card("Devices", image="mobile")
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
        card = Card("Appearance", "settings")
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

        self.theme_box = QComboBox()
        self.theme_box.setObjectName("pill")
        self.theme_box.setCursor(Qt.PointingHandCursor)
        self._theme_modes = ["dark", "light"]
        self.theme_box.addItems(["Dark", "Light"])
        current = (prefs.get("theme_mode") or "dark").lower()
        if current in self._theme_modes:
            self.theme_box.setCurrentIndex(self._theme_modes.index(current))
        self.theme_box.currentIndexChanged.connect(self._set_theme)
        card.body.addWidget(SettingRow(
            "settings", "Theme",
            "Banners stay dark in both - they sit over other windows",
            self.theme_box))
        return card

    def _save(self, key: str, value) -> bool:
        """
        Write one preference and confirm it on screen.

        Every Settings control goes through here rather than calling
        prefs.set directly, so the confirmation cannot drift out of step
        with what was actually written - and so a failed write is reported
        instead of looking identical to a successful one.
        """
        saved = prefs.set(key, value)
        notice = getattr(self, "save_notice", None)
        if notice is not None:
            notice.flash(saved)
        if not saved:
            applog.log(f"could not save {key!r}", "ui")
        return saved

    def _set_theme(self, index: int) -> None:
        """
        Switch palette live.

        Re-applying the app stylesheet repaints everything QSS drives. Rows
        built with an inline setStyleSheet (the feed and call lists) captured
        their hover colour at construction, so the cached signatures are
        cleared to force a rebuild on the next refresh tick rather than
        leaving half the window in the old palette until something changes.
        """
        mode = self._theme_modes[index] if 0 <= index < 2 else "dark"
        self._save("theme_mode", mode)
        theme.apply_mode(mode)

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.sheet())
        # Labels carry their colour in their own stylesheet, so the app
        # sheet alone does not reach them - without this, every label keeps
        # the previous palette's colour and half of them go invisible.
        restyle_labels()
        restyle_images()
        self._feed_signature = None
        self._call_signature = None
        self._refresh_lists()
        self.refresh()
        applog.log("theme switched to %s" % mode, "app")

    def _set_opacity(self, value: int) -> None:
        self._save("toast_opacity", value / 100)
        from qt_toast import MANAGER
        MANAGER.apply_opacity()

    def _card_spotify(self) -> Card:
        """
        AMS gives no artwork and no absolute volume. Spotify's Web API gives
        both, so linking an account is optional polish rather than a
        requirement - everything still works over Bluetooth alone.
        """
        card = Card("Spotify", "music", theme.GREEN)
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

    def _toggle_desktop(self, checked: bool) -> None:
        """
        Same honesty as _toggle_startup: if the shortcut could not be
        written - a locked Desktop, or OneDrive mid-sync - the switch snaps
        back rather than claiming something that is not there.
        """
        actual = desktop.set_enabled(checked)
        if actual != checked:
            self.switch_desktop.blockSignals(True)
            self.switch_desktop.setChecked(actual)
            self.switch_desktop.blockSignals(False)
            self.desktop_row.set_caption(
                "Could not write to %s" % desktop.folder())
        else:
            self.desktop_row.set_caption(
                "Shortcut is on your desktop" if actual
                else "Put a shortcut to this app on your desktop")

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
        self.hero_pill_state.set_state(
            connected, "Connected" if connected else "Disconnected")
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

        self.device_title.setText(device["name"] or "iPhone")
        self.device_model.setText(device["model"] or "")
        self.device_seen.setText(
            "Last seen %s" % ago(device["last_seen"])
            if device["last_seen"] else "")

        # The activity log is rebuilt only when the feed actually changed,
        # since it recreates its rows and refresh() runs every second.
        if self._activity_signature != self._feed_signature:
            self._activity_signature = self._feed_signature
            self._fill_activity()

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

        # The chip names the player; the waveform runs only while playing.
        self.media_source.set_source(media.get("player") or "")
        self.media_wave.set_active(bool(media["playing"]))

        glyph = "pause" if media["playing"] else "play"
        self.np_play.setIcon(vicons.icon(glyph, 22, theme.ACCENT))
        self.media_play.setIcon(vicons.icon(glyph, 22, theme.ACCENT))

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
        live = call["state"] in ("active", "ringing")
        # The waveform animates only while a call is live; see its docstring
        # for why it is decorative rather than a level meter.
        self.call_wave.set_active(live)
        if live:
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

    def _on_search(self, _text: str = "") -> None:
        """Re-run immediately; SQLite over 10k short rows is well inside a
        frame, so debouncing would only add latency."""
        self._fill_all_list()

    def _fill_all_list(self) -> None:
        """
        The Notifications page list.

        With an empty box this mirrors the live feed. With a query it goes
        to the database instead, so results reach the whole retained
        history rather than the 120 items the deque happens to hold.
        """
        query = ""
        if getattr(self, "search_box", None) is not None:
            query = (self.search_box.text() or "").strip()
        name = getattr(self, "notif_filter", "All")

        if query:
            items = FEED.search(query=query, limit=200)
        else:
            items = FEED.recent(120)
        items = [i for i in items if self._matches_notif_filter(i, name)][:40]

        self.all_empty.setVisible(not items)
        if query:
            self.all_empty.set_text(
                "No matches", 'Nothing in history matches "%s".' % query)
        elif name != "All":
            self.all_empty.set_text(
                "Nothing here", "No %s yet." % name.lower())
        else:
            self.all_empty.set_text(
                "Nothing yet", "Notifications from the phone land here.")
        # accent=True only on this page: a long unbroken list is where a
        # per-app colour helps, unlike the three-row Overview cards.
        self._fill(self.all_box, items, accent=True)

    def _refresh_lists(self) -> None:
        """Rebuilt only on change - a full teardown every second flickered."""
        items = FEED.recent(40)
        signature = (FEED.count(), items[0].at if items else 0,
                     self.msg_search.text()
                     if getattr(self, "msg_search", None) else "")
        if signature != self._feed_signature:
            self._feed_signature = signature
            messages = [i for i in items if i.bundle_id in MESSAGE_APPS]
            # The Messages page filters further; the Overview card does not,
            # because a search on one page should not empty a summary on
            # another.
            searched = [i for i in messages
                        if self._matches_msg_search(i)][:14]
            messages = messages[:14]
            self.feed_empty.setVisible(not items)
            self.messages_empty.setVisible(not searched)
            self.messages_dash_empty.setVisible(not messages)
            self._fill(self.feed_box, items[:3])
            self._fill(self.messages_box, searched)
            self._fill(self.messages_dash_box, messages[:3])
            # The Notifications page has its own source, because a search
            # must not be wiped out by the next arriving notification.
            self._fill_all_list()

        history = calls.TRACKER.recent(20)
        if self._call_filter == "Missed":
            history = [c for c in history if c.state == "missed"]
        elif self._call_filter == "Incoming":
            history = [c for c in history if c.direction == "incoming"]
        elif self._call_filter == "Outgoing":
            history = [c for c in history if c.direction == "outgoing"]
        # Search applies after the filter, so "Missed" plus a name narrows
        # rather than replacing one with the other.
        history = [c for c in history if self._matches_call_search(c)]

        call_signature = (self._call_filter,
                          (self.call_search.text()
                           if getattr(self, "call_search", None) else ""),
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

    def _fill(self, box, items, accent: bool = False) -> None:
        self._clear(box)
        for item in items:
            box.addWidget(FeedRow(item, _pixmap_for(item.bundle_id, item.app),
                                  accent=accent))

    def _call_row(self, call) -> QFrame:
        row = QFrame()
        row.setFixedHeight(58)
        # Object name, not an inline stylesheet: inline bakes the palette in
        # at construction and survives a theme switch unchanged.
        row.setObjectName("callRow")
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
