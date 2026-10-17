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
from typing import Callable, Dict, Iterable, Optional, Union

from PySide6.QtCore import QObject, QRegularExpression, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QRegularExpressionValidator,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
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


def _button_rules() -> str:
    rules = [
        "QPushButton { padding: 5px 14px; border-radius: 6px; }",
    ]
    for variant, (color, hover) in _VARIANT_COLORS.items():
        rules.append(
            f"QPushButton#{variant} {{ background-color: {color}; color: white; border: none; font-weight: bold; }}"
        )
        rules.append(f"QPushButton#{variant}:hover {{ background-color: {hover}; }}")
        rules.append(f"QPushButton#{variant}:disabled {{ background-color: #d0d0d0; color: #7a7a7a; }}")
    return "\n".join(rules)


APP_STYLE_SHEET = _button_rules()


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


def caption_label(text: str) -> QLabel:
    """A small, gray hint label that wraps."""
    label = QLabel(text)
    label.setWordWrap(True)
    font = label.font()
    font.setPointSize(max(font.pointSize() - 1, 7))
    label.setFont(font)
    label.setStyleSheet(f"color: {STATUS_IDLE};")
    return label


def error_label(text: str) -> QLabel:
    """A red error / warning label that wraps."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {STATUS_FAIL};")
    return label


def set_label_color(label: QLabel, color: str) -> None:
    label.setStyleSheet(f"color: {color};")


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
    box = QGroupBox(title)
    box.setLayout(layout)
    return box


# --- text surfaces ---


class OutputConsole(QPlainTextEdit):
    """The dark, read-only log / output console of the panels.

    ``append_text`` adds text as it comes (no newline is added), optionally colored by a tag of
    :data:`CONSOLE_TAG_COLORS`. The view follows the end unless the user scrolled up to read.
    """

    def __init__(self, parent: Optional[QWidget] = None, *, wrap: bool = True, editable: bool = False) -> None:
        super().__init__(parent)
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


def align_top(widget: QWidget) -> QWidget:
    """Wrap ``widget`` so it keeps its natural height at the top of a stretched area."""
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
    layout.addStretch(1)
    return wrapper
