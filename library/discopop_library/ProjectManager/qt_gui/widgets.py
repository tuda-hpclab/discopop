# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The shared look and the building blocks of the Qt panels.

The counterpart of ``gui/widgets.py``: one place for colors, fonts, buttons, the log console, the code and script
editors and the thread selector, so components of the same kind look the same in every panel.
"""

import logging
import time
from typing import Callable, Dict, Iterable, Optional, Tuple, Union

from PySide6.QtCore import QObject, QRect, QRegularExpression, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPalette,
    QRegularExpressionValidator,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QMenu,
    QPlainTextEdit,
    QProxyStyle,
    QPushButton,
    QStyle,
    QStyleOption,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.qt_gui.threads import assert_main_thread

# --- palette (Catppuccin Mocha for the consoles, as in the Tk GUI) ---
CATPPUCCIN_BG = "#1e1e2e"
CATPPUCCIN_OUTPUT_BG = "#45475a"
CATPPUCCIN_FG = "#cdd6f4"
CATPPUCCIN_BLUE = "#89b4fa"
CATPPUCCIN_CYAN = "#89dceb"
CATPPUCCIN_GREEN = "#a6e3a1"
CATPPUCCIN_YELLOW = "#f9e2af"
CATPPUCCIN_PEACH = "#fab387"
CATPPUCCIN_RED = "#f38ba8"
CATPPUCCIN_CRITICAL_BG = "#3b3052"

CONSOLE_BG = CATPPUCCIN_OUTPUT_BG
CONSOLE_FG = CATPPUCCIN_FG

# --- semantic status colors (status line, result marks) ---
STATUS_IDLE = "gray"
# the color of hint texts in a style sheet (captions, empty views, idle status lines): the palette's placeholder
# color, which the themes set dark enough to read on the window and on a card; labels set to STATUS_IDLE get it
HINT_COLOR = "palette(placeholder-text)"
STATUS_BUSY = "#1e66f5"
STATUS_OK = "#2e7d32"
STATUS_FAIL = "#c62828"
STATUS_STOP = "#e65100"

LINK_FG = "#6699cc"
PLACEHOLDER_FG = "#999999"
TREE_EVEN_ROW = "#d9e8f5"

# --- button variants: the objectName the style sheet selects on ---
VARIANT_DEFAULT = "default"
VARIANT_PRIMARY = "primary"
VARIANT_SUCCESS = "success"
VARIANT_DANGER = "danger"
# a destructive action that is not the page's main one: red text and frame, filled red while hovered
VARIANT_DANGER_OUTLINE = "dangerOutline"

_VARIANT_COLORS = {
    VARIANT_PRIMARY: ("#1e66f5", "#1a57d1"),
    VARIANT_SUCCESS: ("#2e7d32", "#256628"),
    VARIANT_DANGER: ("#c62828", "#a52222"),
}

THREAD_AUTO = "auto"
THREAD_VALUES = [THREAD_AUTO, "1", "2", "4", "8", "16"]
LOG_LEVEL_VALUES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# colors of the tags a console line can carry (log levels, plus the marks the panels write)
CONSOLE_TAG_COLORS: Dict[str, str] = {
    "DEBUG": CATPPUCCIN_BLUE,
    "INFO": CATPPUCCIN_CYAN,
    "WARNING": CATPPUCCIN_YELLOW,
    "ERROR": CATPPUCCIN_RED,
    "CRITICAL": CATPPUCCIN_RED,
    "SUCCESS": CATPPUCCIN_GREEN,
    "timestamp": CATPPUCCIN_PEACH,
}


# The style sheet names palette roles (``palette(button)``, ``palette(mid)``, ...) instead of fixed colors, so the
# application follows the light or dark color scheme of the desktop; only the accent colors of the button variants
# and the status chips are fixed (they carry white text and read on both).


def button_colors(palette: QPalette) -> Tuple[QColor, QColor, QColor, QColor]:
    """Background, border, hover and pressed color of a default button, derived from the window color.

    The palette's own button color often equals the window color and its "mid" border is faint, which left a plain
    button ("Help") barely visible; these stand out from the window, a card and the page of a tab in both themes.
    """
    window = palette.color(QPalette.ColorRole.Window)
    if is_dark(palette):
        return window.lighter(150), window.lighter(230), window.lighter(185), window.lighter(120)
    return window.lighter(112), window.darker(145), window.darker(106), window.darker(115)


def _button_rules(palette: Optional[QPalette] = None) -> str:
    if palette is not None:
        background, border, hover, pressed = (color.name() for color in button_colors(palette))
        disabled_text = _secondary_text(palette)
    else:
        background, border, hover, pressed = "palette(button)", "palette(mid)", "palette(midlight)", "palette(mid)"
        disabled_text = "palette(mid)"
    rules = [
        # the default look: a framed button that stands out from the window (a border radius without a border would
        # draw a bare label)
        f"QPushButton {{ padding: 5px 14px; border-radius: 6px; border: 1px solid {border};"
        f" background-color: {background}; color: palette(button-text); }}",
        f"QPushButton:hover {{ background-color: {hover}; }}",
        f"QPushButton:pressed {{ background-color: {pressed}; }}",
        # disabled: still a framed button (it says what could be done), with its text grayed out
        f"QPushButton:disabled {{ color: {disabled_text}; border: 1px dashed {border};"
        " background-color: palette(window); }",
        # a compact button: framed like the default one, with less padding, for slim bars (the output pane's Clear)
        f"QPushButton#{COMPACT_NAME} {{ padding: 2px 10px; }}",
        # a flat button: the "⋯" overflow menus, the toggles of collapsible sections
        "QPushButton#flat, QToolButton#flat { border: none; background: transparent; padding: 3px 6px; }",
        "QPushButton#flat:hover, QToolButton#flat:hover { background-color: palette(midlight); }",
        "QToolButton#flat::menu-indicator { image: none; }",
    ]
    for variant, (color, hover) in _VARIANT_COLORS.items():
        rules.append(
            f"QPushButton#{variant} {{ background-color: {color}; color: white; border: 1px solid {color};"
            " font-weight: bold; }"
        )
        rules.append(f"QPushButton#{variant}:hover {{ background-color: {hover}; }}")
        # disabled: the accent faded towards the window, so the primary action stays recognizable where it is
        faded = _faded(QColor(color), palette)
        rules.append(
            f"QPushButton#{variant}:disabled {{ background-color: {faded}; color: {_faded_text(palette)};"
            f" border: 1px solid {faded}; }}"
        )
    danger_color = _VARIANT_COLORS[VARIANT_DANGER][0]
    danger_text = "#ef6c6c" if palette is not None and is_dark(palette) else danger_color
    rules += [
        f"QPushButton#{VARIANT_DANGER_OUTLINE} {{ color: {danger_text}; border: 1px solid {danger_text}; }}",
        f"QPushButton#{VARIANT_DANGER_OUTLINE}:hover, QPushButton#{VARIANT_DANGER_OUTLINE}:pressed"
        f" {{ background-color: {danger_color}; border-color: {danger_color}; color: white; }}",
        f"QPushButton#{VARIANT_DANGER_OUTLINE}:disabled {{ color: {disabled_text}; border: 1px dashed {border};"
        " background-color: palette(window); }",
        # a card of destructive actions: framed in red
        f"QFrame#{DANGER_ZONE_NAME} {{ border: 1px solid {danger_text}; border-radius: 8px; }}",
        f"QLabel#{DANGER_TITLE_NAME} {{ color: {danger_text}; }}",
    ]
    return "\n".join(rules)


def _mix(color: QColor, other: QColor, share: float) -> str:
    """``share`` of ``color``, the rest of ``other``."""
    return QColor(
        round(color.red() * share + other.red() * (1 - share)),
        round(color.green() * share + other.green() * (1 - share)),
        round(color.blue() * share + other.blue() * (1 - share)),
    ).name()


def _faded(accent: QColor, palette: Optional[QPalette]) -> str:
    """The accent of a disabled button: halfway to the window color (further on a dark window, on which a dark
    accent still reads as active)."""
    window = palette.color(QPalette.ColorRole.Window) if palette is not None else QColor("#efefef")
    return _mix(accent, window, 0.3 if palette is not None and is_dark(palette) else 0.45)


def _faded_text(palette: Optional[QPalette]) -> str:
    """The text on a faded accent: white, a little transparent towards the accent."""
    return "#f0f0f0" if palette is None or not is_dark(palette) else "#9a9a9a"


def chrome_color(palette: QPalette) -> QColor:
    """The background of the window's frame (header bar, sidebar, status line): a shade darker than the pages, so
    that the navigation and the page content read as separate areas, in a light and in a dark palette."""
    window = palette.color(QPalette.ColorRole.Window)
    return window.darker(140) if is_dark(palette) else window.darker(112)


def _chrome_rules(palette: Optional[QPalette]) -> str:
    """The frame of the main window: header bar and sidebar in the chrome color, with a line towards the page."""
    background = chrome_color(palette).name() if palette is not None else "palette(window)"
    hover = chrome_color(palette).darker(112).name() if palette is not None else "palette(midlight)"
    return "\n".join(
        [
            f"QFrame#{HEADER_NAME} {{ background-color: {background}; border-bottom: 1px solid palette(mid); }}",
            f"QFrame#{SIDEBAR_NAME} {{ background-color: {background}; border-right: 1px solid palette(mid); }}",
            f"QStatusBar#{STATUS_BAR_NAME} {{ background-color: {background}; border-top: 1px solid palette(mid); }}",
            # the configurations in the header bar: the selected one filled in the highlight color, as the selected
            # stage of the sidebar; the others as plain text, shaded while hovered
            # the selector of the configuration matters on every stage: tabs taller than the buttons of a page, and
            # at least as wide as a short name, so that "A" and "B" are no narrower targets than "large_input"
            f"QTabBar#{CONFIG_TABS_NAME}::tab {{ background: transparent; border: none; border-radius: 6px;"
            f" padding: 8px 14px; margin: 2px 2px; min-width: {CONFIG_TAB_MIN_WIDTH}px;"
            " color: palette(window-text); }",
            f"QTabBar#{CONFIG_TABS_NAME}::tab:hover {{ background-color: {hover}; }}",
            f"QTabBar#{CONFIG_TABS_NAME}::tab:selected {{ background-color: palette(highlight);"
            " color: palette(highlighted-text); }",
            # its scroll arrows (while the tabs do not fit) in the color of the header bar, covering the tabs below
            f"QTabBar#{CONFIG_TABS_NAME} QToolButton {{ background-color: {background}; border: none;"
            " border-radius: 4px; width: 18px; }",
            f"QTabBar#{CONFIG_TABS_NAME} QToolButton:hover {{ background-color: palette(midlight); }}",
            f"QLabel#{CAPTION_NAME} {{ color: {_secondary_text(palette)}; }}",
        ]
    )


def _secondary_text(palette: Optional[QPalette]) -> str:
    """A text color between the text and the window color: captions next to normal text."""
    if palette is None:
        return "gray"
    text = palette.color(QPalette.ColorRole.WindowText)
    window = palette.color(QPalette.ColorRole.Window)
    mixed = QColor(
        (text.red() * 3 + window.red() * 2) // 5,
        (text.green() * 3 + window.green() * 2) // 5,
        (text.blue() * 3 + window.blue() * 2) // 5,
    )
    return mixed.name()


def card_color(palette: QPalette) -> QColor:
    """The background of a card in a light palette: between the window and the input fields, so that the card stands
    out from the page and its input fields from the card (no white areas on a gray page)."""
    return QColor(_mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Window), 0.55))


def _component_rules(palette: Optional[QPalette] = None) -> str:
    # a card: the framed section of a form (FormSection). Light, it is lifted towards the color of the input fields;
    # dark, input fields and the indicators of check boxes are drawn in that color too and would vanish in it, so the
    # card keeps the window color and only its frame sets it apart (as in a dialog)
    if palette is None:
        card_background = "palette(base)"
    else:
        card_background = "palette(window)" if is_dark(palette) else card_color(palette).name()
    rules = [
        f"QFrame#{CARD_NAME} {{ border: 1px solid palette(midlight); border-radius: 8px;"
        f" background-color: {card_background}; }}",
        # a status chip: a rounded, colored pill (StatusChip)
        f"QLabel#{CHIP_NAME} {{ border-radius: 9px; padding: 2px 10px; font-weight: bold; }}",
    ]
    return "\n".join(rules)


# objectNames the style sheet selects on
CARD_NAME = "card"
CHIP_NAME = "chip"
FLAT_NAME = "flat"
COMPACT_NAME = "compact"
BANNER_NAME = "warningBanner"
DANGER_ZONE_NAME = "dangerZone"
DANGER_TITLE_NAME = "dangerTitle"
# the frame of the main window (see _chrome_rules)
HEADER_NAME = "appHeader"
SIDEBAR_NAME = "appSidebar"
STATUS_BAR_NAME = "appStatusBar"
CONFIG_TABS_NAME = "configTabs"
# the least width of the text of a configuration tab (its padding comes on top)
CONFIG_TAB_MIN_WIDTH = 56
CAPTION_NAME = "caption"

APP_STYLE_SHEET = _button_rules() + "\n" + _component_rules()


def app_style_sheet(palette: QPalette) -> str:
    """The style sheet of the application for ``palette`` (light or dark, see :func:`is_dark`)."""
    return _button_rules(palette) + "\n" + _component_rules(palette) + "\n" + _chrome_rules(palette)


def is_dark(palette: QPalette) -> bool:
    """Whether ``palette`` is a dark one: its window color is darker than its text."""
    return (
        palette.color(QPalette.ColorRole.Window).lightness() < palette.color(QPalette.ColorRole.WindowText).lightness()
    )


# how much taller than the font a tab title may draw (see TabTextRoomStyle)
TAB_TEXT_EXTRA_PX = 2


class TabTextRoomStyle(QProxyStyle):
    """The application style, with room for the underscores of tab titles.

    Fusion clips a tab's title to the height of its font, and the underscore of some fonts (Ubuntu, the default on
    Ubuntu desktops) lies below that: "compile_validate.sh" read as "compile validate.sh".
    """

    def subElementRect(  # noqa: N802 (Qt's name)
        self, element: QStyle.SubElement, option: QStyleOption, widget: Optional[QWidget] = None
    ) -> QRect:
        # the stubs of QProxyStyle (widget required) and QCommonStyle (optional) disagree; Qt passes None as well
        rect = super().subElementRect(element, option, widget)  # type: ignore[arg-type]
        if element == QStyle.SubElement.SE_TabBarTabText:
            rect.adjust(0, -TAB_TEXT_EXTRA_PX, 0, TAB_TEXT_EXTRA_PX)
        return rect


def monospace_font(point_size: int = 11) -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    return font


# --- labels ---


def heading_label(text: str, *, title: bool = False) -> QLabel:
    """A bold section header (``title=True`` for the slightly larger panel title)."""
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    font.setPointSize(font.pointSize() + (2 if title else 1))
    label.setFont(font)
    return label


def empty_state_label(text: str) -> QLabel:
    """The text of an empty view (a table, a chart, a detail area) saying what to do: centered, gray, in the normal
    font size, the same on every page."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(f"color: {HINT_COLOR};")
    return label


def caption_label(text: str) -> QLabel:
    """A small, gray hint label that wraps."""
    label = QLabel(text)
    label.setWordWrap(True)
    font = label.font()
    font.setPointSize(max(font.pointSize() - 1, 7))
    label.setFont(font)
    label.setStyleSheet(f"color: {HINT_COLOR};")
    return label


def error_label(text: str) -> QLabel:
    """A red error / warning label that wraps."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {STATUS_FAIL};")
    return label


def set_label_color(label: QLabel, color: str) -> None:
    """``color`` as the text color of ``label``; :data:`STATUS_IDLE` is drawn in the hint color of the palette."""
    label.setStyleSheet(f"color: {HINT_COLOR if color == STATUS_IDLE else color};")


# --- buttons ---


def create_button(
    text: str,
    on_click: Optional[Callable[[], None]] = None,
    *,
    variant: str = VARIANT_DEFAULT,
    tooltip: Optional[str] = None,
) -> QPushButton:
    """A push button; ``variant`` (default / primary / success / danger) selects its look in the style sheet."""
    button = QPushButton(text)
    if variant != VARIANT_DEFAULT:
        button.setObjectName(variant)
    if on_click is not None:
        # the lambda drops the ``checked`` argument of ``clicked``
        button.clicked.connect(lambda _checked=False: on_click())
    if tooltip:
        button.setToolTip(tooltip)
    return button


def primary_button(text: str, on_click: Optional[Callable[[], None]] = None, **kwargs: Optional[str]) -> QPushButton:
    """A primary / affirmative action button (Run, Save, Next, ...)."""
    return create_button(text, on_click, variant=VARIANT_PRIMARY, tooltip=kwargs.get("tooltip"))


def success_button(text: str, on_click: Optional[Callable[[], None]] = None, **kwargs: Optional[str]) -> QPushButton:
    """A button showing a completed state (green)."""
    return create_button(text, on_click, variant=VARIANT_SUCCESS, tooltip=kwargs.get("tooltip"))


def danger_outline_button(
    text: str, on_click: Optional[Callable[[], None]] = None, **kwargs: Optional[str]
) -> QPushButton:
    """A destructive action beside others: outlined in red (:data:`VARIANT_DANGER_OUTLINE`)."""
    return create_button(text, on_click, variant=VARIANT_DANGER_OUTLINE, tooltip=kwargs.get("tooltip"))


def danger_button(text: str, on_click: Optional[Callable[[], None]] = None, **kwargs: Optional[str]) -> QPushButton:
    """A destructive or interrupting action (Reset, Delete, Stop), red."""
    return create_button(text, on_click, variant=VARIANT_DANGER, tooltip=kwargs.get("tooltip"))


def set_button_variant(button: QPushButton, variant: str) -> None:
    """Switch the look of an existing button (e.g. Run -> Stop); the style sheet is re-applied."""
    button.setObjectName("" if variant == VARIANT_DEFAULT else variant)
    button.style().unpolish(button)
    button.style().polish(button)


# --- layouts ---


def hbox(*items: Union[QWidget, QLayout, int, None], margins: int = 0, spacing: int = 6) -> QHBoxLayout:
    """A horizontal layout of ``items``; an int adds that much space, ``None`` a stretch."""
    layout = QHBoxLayout()
    _fill(layout, items, margins, spacing)
    return layout


def vbox(*items: Union[QWidget, QLayout, int, None], margins: int = 0, spacing: int = 6) -> QVBoxLayout:
    """A vertical layout of ``items``; an int adds that much space, ``None`` a stretch."""
    layout = QVBoxLayout()
    _fill(layout, items, margins, spacing)
    return layout


def _fill(
    layout: Union[QHBoxLayout, QVBoxLayout],
    items: Iterable[Union[QWidget, QLayout, int, None]],
    margins: int,
    spacing: int,
) -> None:
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    for item in items:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)


def group_box(title: str, layout: QLayout) -> QGroupBox:
    """A titled frame around ``layout`` (the ttk.LabelFrame of the Tk GUI)."""
    # "&" marks a keyboard mnemonic in a Qt title; the titles are plain text
    box = QGroupBox(title.replace("&", "&&"))
    box.setLayout(layout)
    return box


# --- text surfaces ---


class OutputConsole(QPlainTextEdit):
    """The dark, read-only log / output console of the panels.

    ``append_text`` adds text as it comes (no newline is added), optionally colored by a tag of
    :data:`CONSOLE_TAG_COLORS`. The view follows the end unless the user scrolled up to read. ``text_appended``
    carries every appended piece (the output dock shows the last line of a collapsed console).
    """

    text_appended = Signal(str)
    cleared = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *, wrap: bool = True, editable: bool = False) -> None:
        super().__init__(parent)
        self.setPlaceholderText("No output yet.")
        self.setReadOnly(not editable)
        self.setFont(monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if wrap else QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(f"QPlainTextEdit {{ background-color: {CONSOLE_BG}; color: {CONSOLE_FG}; border: none; }}")
        self._formats: Dict[str, QTextCharFormat] = {}
        for tag, color in CONSOLE_TAG_COLORS.items():
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            if tag == "CRITICAL":
                text_format.setBackground(QColor(CATPPUCCIN_CRITICAL_BG))
            self._formats[tag] = text_format
        self._plain_format = QTextCharFormat()
        self._plain_format.setForeground(QColor(CONSOLE_FG))

    def append_text(self, text: str, tag: Optional[str] = None) -> None:
        assert_main_thread()
        scrollbar = self.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 2
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, self._formats.get(tag or "", self._plain_format))
        if follow:
            scrollbar.setValue(scrollbar.maximum())
        self.text_appended.emit(text)

    def clear(self) -> None:
        super().clear()
        self.cleared.emit()

    def set_text(self, text: str) -> None:
        """Replace the whole content."""
        self.clear()
        self.append_text(text)

    def text(self) -> str:
        return self.toPlainText()


class _LogRecordRelay(QObject):
    """Carries formatted log records from any thread to the console.

    The relay lives on the main thread; a signal emitted on a worker thread reaches its slot through the main
    thread's event loop (an automatic connection between threads is a queued one).
    """

    record = Signal(str, str)

    def __init__(self, console: OutputConsole) -> None:
        super().__init__()
        self._console = console
        self.record.connect(self._append)

    @Slot(str, str)
    def _append(self, message: str, level_name: str) -> None:
        try:
            self._console.append_text(message + "\n", level_name)
        except RuntimeError:
            # the console was deleted while the record was waiting
            pass


class ConsoleLogHandler(logging.Handler):
    """A logging handler writing to an :class:`OutputConsole`; records may come from any thread.

    Create it on the main thread.
    """

    def __init__(self, console: OutputConsole) -> None:
        super().__init__()
        assert_main_thread()
        self._relay = _LogRecordRelay(console)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._relay.record.emit(self.format(record), record.levelname)
        except Exception:
            self.handleError(record)


def redirect_logging_to_console(console: OutputConsole, level: Union[int, str]) -> Callable[[], None]:
    """Show the records of the root logger in ``console``; return the function that undoes it.

    While redirected, the console is the only handler of the root logger. The previous handlers and level are
    restored by the returned function, so nothing stays installed after the run.
    """
    root_logger = logging.getLogger()
    saved_handlers = root_logger.handlers[:]
    saved_level = root_logger.level
    for handler in saved_handlers:
        root_logger.removeHandler(handler)
    root_logger.setLevel(level)
    console_handler = ConsoleLogHandler(console)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    root_logger.addHandler(console_handler)

    def restore() -> None:
        root_logger.removeHandler(console_handler)
        for handler in saved_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(saved_level)

    return restore


class _DiffHighlighter(QSyntaxHighlighter):
    """Colors the lines of a unified diff."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._formats: Dict[str, QTextCharFormat] = {}
        for name, color in (
            ("header", CATPPUCCIN_BLUE),
            ("add", CATPPUCCIN_GREEN),
            ("remove", CATPPUCCIN_RED),
            ("hunk", CATPPUCCIN_YELLOW),
        ):
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            self._formats[name] = text_format
        self.enabled = False

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt's name)
        if not self.enabled:
            return
        # the ---/+++ file headers are checked first: they also start with -/+
        if text.startswith("+++") or text.startswith("---"):
            kind = "header"
        elif text.startswith("+"):
            kind = "add"
        elif text.startswith("-"):
            kind = "remove"
        elif text.startswith("@@"):
            kind = "hunk"
        else:
            return
        self.setFormat(0, len(text), self._formats[kind])


class CodeView(QPlainTextEdit):
    """A read-only, dark code / patch viewer; :meth:`set_diff` colors a unified diff."""

    def __init__(self, parent: Optional[QWidget] = None, *, wrap: bool = False) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if wrap else QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(f"QPlainTextEdit {{ background-color: {CONSOLE_BG}; color: {CONSOLE_FG}; border: none; }}")
        self._highlighter = _DiffHighlighter(self.document())

    def set_code(self, text: str) -> None:
        self._highlighter.enabled = False
        self.setPlainText(text)

    def set_diff(self, text: str) -> None:
        self._highlighter.enabled = True
        self.setPlainText(text)
        self._highlighter.rehighlight()


class ScriptEditor(QPlainTextEdit):
    """An editable script / settings editor (execute.sh, compile.sh, JSON settings)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFont(monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Replace the content without marking the editor as modified."""
        self.setPlainText(text)
        self.document().setModified(False)


# --- thread selector ---


def is_valid_thread_value(value: str) -> bool:
    """True for the values a thread selector may hold: ``auto`` or a positive integer."""
    return value == THREAD_AUTO or (value.isdigit() and int(value) > 0)


class ThreadSelector(QComboBox):
    """Pick one of the preset thread counts, or type a positive integer; anything else reads as ``auto``."""

    def __init__(self, parent: Optional[QWidget] = None, initial: str = THREAD_AUTO) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.addItems(THREAD_VALUES)
        self.setValidator(QRegularExpressionValidator(QRegularExpression("^(a|au|aut|auto|[0-9]*)$"), self))
        self.setCurrentText(initial)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.editingFinished.connect(self._normalize)

    def _normalize(self) -> None:
        self.setCurrentText(self.value())

    def value(self) -> str:
        value = self.currentText().strip()
        return value if is_valid_thread_value(value) else THREAD_AUTO


def log_level_selector(initial: str = "WARNING") -> QComboBox:
    combo = QComboBox()
    combo.addItems(LOG_LEVEL_VALUES)
    combo.setCurrentText(initial)
    return combo


# --- run / stop ---

# clicks this soon after a RunStopButton switched between run and stop are ignored (the second click of a double click)
SWITCH_GUARD_S = 0.5


class RunStopButton(QPushButton):
    """One button that starts a job and, while it runs, stops it (instead of a Run and a mostly disabled Stop).

    Idle it shows ``run_text`` in the primary color and calls ``on_run``; after :meth:`set_running` (True) it shows
    ``stop_text`` in the danger color, stays enabled and calls ``on_stop``.

    ``setEnabled`` always means "can a run be started": while running it is only remembered (so code disabling all
    controls during a job does not disable Stop) and applied when the run ends. :meth:`set_stop_enabled` (False)
    while running means "cannot be stopped now" (a phase that must not be interrupted); :meth:`set_stopping` shows
    that a stop was requested and blocks a second click.
    """

    def __init__(
        self,
        run_text: str,
        on_run: Callable[[], None],
        on_stop: Callable[[], None],
        *,
        stop_text: str = "■ Stop",
        tooltip: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(run_text, parent)
        self._run_text = run_text
        self._stop_text = stop_text
        self._on_run = on_run
        self._on_stop = on_stop
        self._running = False
        self._can_run = True
        self._switched_at = -SWITCH_GUARD_S
        self.setObjectName(VARIANT_PRIMARY)
        if tooltip:
            self.setToolTip(tooltip)
        self.clicked.connect(lambda _checked=False: self._clicked())

    def _clicked(self) -> None:
        # the second click of a double click lands on the button that has just switched: it must neither stop the
        # job it started nor start one right after a stop
        if time.monotonic() - self._switched_at < SWITCH_GUARD_S:
            return
        if self._running:
            self._on_stop()
        else:
            self._on_run()

    def is_running(self) -> bool:
        return self._running

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (Qt's name)
        self._can_run = enabled
        if not self._running:
            super().setEnabled(enabled)

    def can_run(self) -> bool:
        return self._can_run

    def set_running(self, running: bool, *, enabled_after: Optional[bool] = None) -> None:
        """Switch between the run and the stop look.

        ``enabled_after``: whether Run is offered once it ended; by default what ``setEnabled`` said last.
        """
        if running != self._running:
            self._switched_at = time.monotonic()
        self._running = running
        if enabled_after is not None:
            self._can_run = enabled_after
        self.setText(self._stop_text if running else self._run_text)
        set_button_variant(self, VARIANT_DANGER if running else VARIANT_PRIMARY)
        super().setEnabled(True if running else self._can_run)

    def set_stopping(self, text: str = "Stopping…") -> None:
        """A stop was requested: say so and ignore further clicks until :meth:`set_running` (False)."""
        if self._running:
            self.setText(text)
            super().setEnabled(False)

    def set_run_text(self, text: str) -> None:
        """Change the idle text (e.g. "Run Analysis" -> "Re-run Analysis")."""
        self._run_text = text
        if not self._running:
            self.setText(text)

    def set_stop_enabled(self, enabled: bool) -> None:
        if self._running:
            super().setEnabled(enabled)


# --- forms ---


class FormSection(QFrame):
    """A titled card holding a form: label | field rows, a hint below its field instead of beside it.

    ``add_row`` puts a plain, right-aligned label and the field side by side and an optional gray hint in the next
    line below the field; ``add_widget`` adds a full-width row (a check box, a list). The same look in every panel.
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(CARD_NAME)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 12)
        outer.setSpacing(8)
        self.title_label: Optional[QLabel] = None
        if title:
            self.title_label = heading_label(title)
            outer.addWidget(self.title_label)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        outer.addLayout(self.form)

    def add_row(
        self,
        label: str,
        field: Union[QWidget, QLayout],
        hint: str = "",
        *,
        stretch_field: bool = False,
    ) -> Optional[QLabel]:
        """A ``label: field`` row; ``hint`` goes into a caption under the field. Returns the hint label (or None).

        A narrow field (spin box, combo box) keeps its natural width unless ``stretch_field``.
        """
        if isinstance(field, QWidget) and not stretch_field:
            field = hbox(field, None)
        hint_label: Optional[QLabel] = None
        if hint:
            hint_label = caption_label(hint)
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(2)
            if isinstance(field, QLayout):
                column.addLayout(field)
            else:
                column.addWidget(field)
            column.addWidget(hint_label)
            self.form.addRow(label, column)
        elif isinstance(field, QLayout):
            self.form.addRow(label, field)
        else:
            self.form.addRow(label, field)
        return hint_label

    def set_row_visible(self, field: Union[QWidget, QLayout], visible: bool) -> None:
        """Show or hide the row holding ``field`` (as passed to :meth:`add_row` / :meth:`add_widget`)."""
        for row in range(self.form.rowCount()):
            for role in (QFormLayout.ItemRole.FieldRole, QFormLayout.ItemRole.SpanningRole):
                item = self.form.itemAt(row, role)
                if item is not None and _layout_item_holds(item, field):
                    self.form.setRowVisible(row, visible)
                    return

    def add_widget(self, widget: Union[QWidget, QLayout], hint: str = "") -> Optional[QLabel]:
        """A full-width row; ``hint`` goes into a caption below it."""
        if isinstance(widget, QLayout):
            self.form.addRow(widget)
        else:
            self.form.addRow(widget)
        if hint:
            hint_label = caption_label(hint)
            self.form.addRow(hint_label)
            return hint_label
        return None


def _layout_item_holds(item: QLayoutItem, field: Union[QWidget, QLayout]) -> bool:
    """Whether ``item`` is ``field`` or a layout containing it (add_row wraps fields into layouts)."""
    if item.widget() is field or item.layout() is field:
        return True
    layout = item.layout()
    if layout is None:
        return False
    for index in range(layout.count()):
        child = layout.itemAt(index)
        if child is not None and _layout_item_holds(child, field):
            return True
    return False


class CollapsibleSection(QWidget):
    """A "▸ title" toggle that shows / hides its content; for advanced settings that are rarely changed."""

    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        content: QWidget,
        *,
        expanded: bool = False,
        summary: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._title = title
        # what is inside, shown while collapsed ("timeouts, log level"), so the settings can be found
        self._summary = summary
        self.content = content
        self.toggle = QToolButton()
        self.toggle.setObjectName(FLAT_NAME)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self.set_expanded)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(content)
        self._expanded = not expanded  # so the first set_expanded applies the state
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)  # re-enters through toggled
            return
        changed = expanded != self._expanded
        self._expanded = expanded
        text = ("▾ " if expanded else "▸ ") + self._title
        if self._summary and not expanded:
            text += f" — {self._summary}"
        self.toggle.setText(text)
        self.content.setVisible(expanded)
        if changed:
            self.expanded_changed.emit(expanded)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()


# --- status chips ---

CHIP_OK = "ok"
CHIP_WARN = "warn"
CHIP_ERROR = "error"
CHIP_BUSY = "busy"
CHIP_IDLE = "idle"

CHIP_COLORS: Dict[str, str] = {
    CHIP_OK: STATUS_OK,
    CHIP_WARN: STATUS_STOP,
    CHIP_ERROR: STATUS_FAIL,
    CHIP_BUSY: STATUS_BUSY,
    CHIP_IDLE: "#7a7a7a",
}


class WarningBanner(QFrame):
    """A tinted warning box across the page: a bold title, the explanation and the actions that resolve it.

    For a stage whose prerequisites are not met: it opens, and says on the page what is missing and where to get it
    (instead of a disabled entry whose reason is only a tooltip).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(BANNER_NAME)
        color = QColor(CHIP_COLORS[CHIP_WARN])
        rgb = f"{color.red()}, {color.green()}, {color.blue()}"
        self.setStyleSheet(
            f"QFrame#{BANNER_NAME} {{ background-color: rgba({rgb}, 30); border: 1px solid rgba({rgb}, 140);"
            " border-radius: 8px; }"
        )
        self.title_label = heading_label("")
        set_label_color(self.title_label, color.name())
        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        self.actions_layout = hbox(margins=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        layout.addWidget(self.title_label)
        layout.addWidget(self.text_label)
        layout.addLayout(self.actions_layout)
        self.actions_layout.addStretch(1)

    def set_message(self, title: str, text: str) -> None:
        self.title_label.setText("⚠ " + title)
        self.text_label.setText(text)

    def add_action(self, button: QWidget) -> None:
        """A button below the text, left-aligned (before the stretch)."""
        self.actions_layout.insertWidget(self.actions_layout.count() - 1, button)

    def title(self) -> str:
        return self.title_label.text()

    def text(self) -> str:
        return self.text_label.text()


class StatusChip(QWidget):
    """A one-line colored status pill; the long explanation is behind a "Details" toggle, not on the page.

    ``set_status(CHIP_WARN, "Build stale", "Sources changed since ...")``; without a detail the toggle is hidden.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.chip = QLabel()
        self.chip.setObjectName(CHIP_NAME)
        self.details_button = QToolButton()
        self.details_button.setObjectName(FLAT_NAME)
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        self.detail_label = caption_label("")
        self.detail_label.setVisible(False)
        self.details_button.toggled.connect(self.detail_label.setVisible)
        # The row keeps its height when the chip is empty or has no "Details": every page header is equally tall, so
        # the content of all stages starts at the same height and does not jump when a stage's status appears.
        self.row = QWidget()
        self.row.setLayout(hbox(self.chip, self.details_button, None, margins=0))
        # the style sheet (padding of the pill) decides the heights: polish before asking
        self.chip.ensurePolished()
        self.details_button.ensurePolished()
        row_height = max(self.chip.sizeHint().height(), self.details_button.sizeHint().height())
        self.row.setFixedHeight(row_height)
        self.chip.setFixedHeight(row_height)
        self.details_button.setFixedHeight(row_height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.row)
        layout.addWidget(self.detail_label)
        self.level = CHIP_IDLE
        self.set_status(CHIP_IDLE, "")

    def set_status(self, level: str, text: str, detail: str = "") -> None:
        self.level = level
        self.chip.setText(text)
        self.chip.setVisible(bool(text))
        color = QColor(CHIP_COLORS.get(level, CHIP_COLORS[CHIP_IDLE]))
        # a tint of the color behind text in the color: reads on light and dark windows, and is quieter than a
        # solid fill, which made a warning louder than the primary action
        self.chip.setStyleSheet(
            f"color: {color.name()}; background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 38);"
            f" border: 1px solid rgba({color.red()}, {color.green()}, {color.blue()}, 90);"
        )
        self.chip.setToolTip(detail)
        self.detail_label.setText(detail)
        self.details_button.setVisible(bool(detail))
        if not detail:
            self.details_button.setChecked(False)

    def text(self) -> str:
        return self.chip.text()

    def detail(self) -> str:
        return self.detail_label.text()


# --- overflow menu ---


def overflow_button(actions: Iterable[Tuple[str, Callable[[], None]]], *, tooltip: str = "More actions") -> QToolButton:
    """A flat "⋯" button opening a menu of ``(text, callback)``; for rare or destructive actions."""
    button = QToolButton()
    button.setObjectName(FLAT_NAME)
    button.setText("⋯")
    button.setToolTip(tooltip)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(button)
    for text, callback in actions:
        action = menu.addAction(text)
        action.triggered.connect(lambda _checked=False, cb=callback: cb())
    button.setMenu(menu)
    return button


# --- panel header ---

# the width of the slot of the "⋯" button at the right end of a panel header
OVERFLOW_SLOT_WIDTH = 32
# the margins of every panel's page (the main window applies them), so that the stages line up
PAGE_MARGINS = (16, 12, 16, 8)


class PanelHeader(QWidget):
    """The top row of a panel: title and one-line description on the left, a status chip below them, and the
    panel's actions on the right (the primary one -- usually a :class:`RunStopButton` -- last, then a "⋯" menu).

    The primary action sits in the same place in every panel and stays visible while the settings below scroll.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        actions: Iterable[QWidget] = (),
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.title_label = heading_label(title, title=True)
        self.description_label = caption_label(description)
        self.description_label.setVisible(bool(description))
        self.chip = StatusChip()
        self.actions_layout = hbox()
        # the "⋯" menu has a slot of its own at the right end, empty in panels without one, so that the primary
        # action is in the same place in every panel
        self.overflow_slot = QWidget()
        self.overflow_slot.setFixedWidth(OVERFLOW_SLOT_WIDTH)
        self._overflow_layout = hbox(margins=0)
        self.overflow_slot.setLayout(self._overflow_layout)
        self.actions_layout.addWidget(self.overflow_slot, 0, Qt.AlignmentFlag.AlignTop)
        for action in actions:
            self.add_action(action)
        text_column = vbox(self.title_label, self.description_label, self.chip, spacing=4)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(12)
        layout.addLayout(text_column, 1)
        layout.addLayout(self.actions_layout, 0)
        self.actions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def add_action(self, widget: QWidget) -> None:
        """Add an action left of the "⋯" slot; an :func:`overflow_button` goes into the slot."""
        if isinstance(widget, QToolButton) and widget.objectName() == FLAT_NAME and widget.menu() is not None:
            self._overflow_layout.addWidget(widget)
        else:
            self.actions_layout.insertWidget(self.actions_layout.count() - 1, widget)


def align_top(widget: QWidget) -> QWidget:
    """Wrap ``widget`` so it keeps its natural height at the top of a stretched area."""
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
    layout.addStretch(1)
    return wrapper
