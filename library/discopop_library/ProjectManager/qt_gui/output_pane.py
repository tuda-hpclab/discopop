# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The output pane below the panels: one console per panel, collapsible to a one-line header.

The panels used to give a third of their width to a console of their own, which was empty most of the time. The
consoles now live here, one tab each; collapsed, the header shows the last line written to any of them, so a running
job stays visible without taking space.
"""

from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QLabel, QTabWidget, QToolButton, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import widgets

# the longest last line the collapsed header shows
_LAST_LINE_MAX_CHARS = 300


class OutputPane(QWidget):
    """The consoles of the panels as tabs under a header with a collapse toggle and the last line of output."""

    expanded_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.toggle = QToolButton()
        self.toggle.setObjectName(widgets.FLAT_NAME)
        self.toggle.setCheckable(True)
        self.toggle.setToolTip("Show or hide the output of the jobs")
        self.toggle.toggled.connect(self._on_toggled)
        self.last_line = QLabel()
        self.last_line.setTextFormat(Qt.TextFormat.PlainText)
        widgets.set_label_color(self.last_line, widgets.STATUS_IDLE)
        self.last_line.setMinimumWidth(50)
        self.clear_button = widgets.create_button("Clear", self.clear_current, tooltip="Clear the shown console")
        # framed: a flat "Clear" read as a label
        self.clear_button.setObjectName(widgets.COMPACT_NAME)
        self.header = QWidget()
        header_layout = widgets.hbox(self.toggle, self.last_line, None, self.clear_button, margins=0)
        # the last line takes the width while collapsed; expanded (it is hidden) the stretch keeps Clear at the right
        header_layout.setStretch(1, 1)
        self.header.setLayout(header_layout)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout = self._layout = QVBoxLayout(self)
        # in line with the content of the page above it
        page_left, _top, page_right, _bottom = widgets.PAGE_MARGINS
        layout.setContentsMargins(page_left, 2, page_right, 4)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.tabs, 1)
        self._titles: Dict[widgets.OutputConsole, str] = {}
        # the recent output of each console, to find its last complete line
        self._tails: Dict[widgets.OutputConsole, str] = {}
        self._last_line_of: Optional[widgets.OutputConsole] = None
        self._expanded = True
        self.set_expanded(False)

    # --- consoles ---

    def add_console(self, title: str, console: widgets.OutputConsole) -> None:
        """Show ``console`` as tab ``title``; its output updates the last line of the header."""
        self._titles[console] = title
        self.tabs.addTab(console, title)
        console.show()
        console.text_appended.connect(lambda text, c=console: self._on_text(c, text))
        console.cleared.connect(lambda c=console: self._on_cleared(c))

    def remove_console(self, console: widgets.OutputConsole) -> None:
        """Take the tab of ``console`` out of the pane (its panel was replaced)."""
        index = self.tabs.indexOf(console)
        if index >= 0:
            self.tabs.removeTab(index)
        self._titles.pop(console, None)
        self._tails.pop(console, None)
        if self._last_line_of is console:
            self._last_line_of = None
            self.last_line.setText("")

    def consoles(self) -> List[widgets.OutputConsole]:
        return list(self._titles)

    def show_console(self, console: widgets.OutputConsole) -> None:
        """Bring the tab of ``console`` to the front and expand the pane."""
        index = self.tabs.indexOf(console)
        if index >= 0:
            self.tabs.setCurrentIndex(index)
        self.set_expanded(True)

    def current_console(self) -> Optional[widgets.OutputConsole]:
        current = self.tabs.currentWidget()
        return current if isinstance(current, widgets.OutputConsole) else None

    def clear_current(self) -> None:
        console = self.current_console()
        if console is not None:
            console.clear()

    # --- collapsing ---

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)  # re-enters through toggled
            return
        changed = expanded != self._expanded
        self._expanded = expanded
        self.toggle.setText(("▾" if expanded else "▸") + " Output")
        self.tabs.setVisible(expanded)
        self.clear_button.setVisible(expanded)
        self.last_line.setVisible(not expanded)
        self.setMaximumHeight(16_777_215 if expanded else self.collapsed_height())
        if changed:
            self.expanded_changed.emit(expanded)

    def collapsed_height(self) -> int:
        margins = self._layout.contentsMargins()
        return self.header.sizeHint().height() + margins.top() + margins.bottom()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        # the header's height is only final once the style polished it
        if not self._expanded:
            self.setMaximumHeight(self.collapsed_height())

    def _on_toggled(self, checked: bool) -> None:
        self.set_expanded(checked)

    # --- the last line ---

    def last_line_text(self) -> str:
        return self.last_line.text()

    def _on_cleared(self, console: widgets.OutputConsole) -> None:
        self._tails.pop(console, None)
        if self._last_line_of is console:
            self._last_line_of = None
            self.last_line.setText("")
            self.last_line.setToolTip("")

    def _on_text(self, console: widgets.OutputConsole, text: str) -> None:
        if console not in self._titles:
            return  # removed from the pane
        tail = (self._tails.get(console, "") + text)[-4 * _LAST_LINE_MAX_CHARS :]
        self._tails[console] = tail
        lines = [line for line in tail.splitlines() if line.strip()]
        if not lines:
            return
        line = lines[-1].strip()[:_LAST_LINE_MAX_CHARS]
        self._last_line_of = console
        self.last_line.setText(f"{self._titles.get(console, '')}: {line}")
        self.last_line.setToolTip(line)
