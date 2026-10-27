# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""An always-visible "Selection Details" side bar for the results panels.

Charts and tables report whatever the user last clicked into one of these, rather than opening a popup, so the view
stays stable while clicking around. Used by the Report tab (execution records) and the Hotspot Detection tab (code
regions). Fields are stacked label above value, so both stay readable as the bar is dragged narrower, and the field
list scrolls.
"""

from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from discopop_library.ProjectManager.qt_gui import widgets

DEFAULT_TITLE = "Selection Details"
DEFAULT_PLACEHOLDER = "Click a point, line, or bar\nto see its details here."


class DetailBar(QWidget):
    """A scrollable, always-visible detail panel filled from a selection."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        title: str = DEFAULT_TITLE,
        placeholder: str = DEFAULT_PLACEHOLDER,
    ) -> None:
        super().__init__(parent)
        self._placeholder_text = placeholder
        self._actions: List[Tuple[QPushButton, Callable[[], bool]]] = []
        self.fields: List[Tuple[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(widgets.heading_label(title))
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll, 1)
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._body)

        # actions at the bottom keep their height however long the field list grows
        self._actions_layout = QVBoxLayout()
        layout.addLayout(self._actions_layout)
        self.show_placeholder()

    # -- content ------------------------------------------------------------

    def show_placeholder(self) -> None:
        """Reset to the "nothing selected yet" state."""
        self._clear_body()
        self.fields = []
        self._body_layout.addWidget(widgets.caption_label(self._placeholder_text))
        self._body_layout.addStretch(1)
        self._update_actions()

    def show_fields(self, fields: Sequence[Tuple[str, str]]) -> None:
        """Replace the contents with ``(label, value)`` rows."""
        self._clear_body()
        self.fields = list(fields)
        for label, value in fields:
            caption = widgets.caption_label(label)
            self._body_layout.addWidget(caption)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._body_layout.addWidget(value_label)
        self._body_layout.addStretch(1)
        self._update_actions()

    def add_action(self, text: str, command: Callable[[], None], *, enabled: Callable[[], bool]) -> QPushButton:
        """Add a button below the fields, enabled according to ``enabled()``.

        ``enabled`` is re-evaluated whenever the contents change, so an action that needs a selection disables
        itself while the placeholder is showing.
        """
        button = widgets.create_button(text, command)
        button.setEnabled(False)
        self._actions_layout.addWidget(button)
        self._actions.append((button, enabled))
        return button

    # -- internals ----------------------------------------------------------

    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _update_actions(self) -> None:
        for button, is_enabled in self._actions:
            button.setEnabled(is_enabled())
