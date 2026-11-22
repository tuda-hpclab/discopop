# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QWidget


class Popup(QFrame):
    def __init__(self, parent: QWidget, minimum_width: int = 150) -> None:
        super().__init__(parent)
        self._minimum_width = minimum_width
        self._button_height = 30
        self._buttons: dict[str, QPushButton] = {}

        self.setFrameShape(QFrame.Shape.Box)

        self.setStyleSheet(
            "QFrame { background: #f2f2f2; border: 1px solid #999999; }"
            "QPushButton { background: #ffffff; border: 0px; text-align: left; padding: 0 8px; }"
            "QPushButton:hover { background: #cfe8ff; }"
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)
        self.hide()

    def _update_layout(self) -> None:
        for button in self._buttons.values():
            button.setFixedHeight(self._button_height)

        self.setMinimumWidth(self._minimum_width)
        self.adjustSize()

    def add_button(self, button_id: str, callback: Callable[[], None]) -> None:
        button = QPushButton(button_id, self)

        def on_click() -> None:
            if self.isVisible():
                self.hide()
                callback()

        button.clicked.connect(on_click)
        self._layout.addWidget(button)
        self._buttons[button_id] = button
        self._update_layout()

    def remove_button(self, button_id: str) -> None:
        button = self._buttons.pop(button_id, None)

        if button is not None:
            self._layout.removeWidget(button)
            button.deleteLater()
            self._update_layout()

    def clear_buttons(self) -> None:
        for button_id in list(self._buttons):
            self.remove_button(button_id)

    def show_at(self, position: QPoint) -> None:
        self._update_layout()
        self.move(position)
        self.raise_()
        self.show()
