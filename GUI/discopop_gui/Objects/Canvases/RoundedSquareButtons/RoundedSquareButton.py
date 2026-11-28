# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RoundedSquareButton(QWidget):
    clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None,
        command: Callable[[], None],
        size: int = 36,
        radius: int = 8,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent, *args, **kwargs)

        self._command = command
        self._size = size
        self._radius = radius
        self._selected = False
        self.setFixedSize(size, size)
        self.clicked.connect(self._command)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, _: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill = QColor("#cfe8ff" if self._selected else "#f2f2f2")
        outline = QColor("#2f80ed" if self._selected else "#999999")
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(outline, 2))
        painter.drawRoundedRect(
            2,
            2,
            self._size - 4,
            self._size - 4,
            self._radius,
            self._radius,
        )

        self._paint_icon(painter)

    def _paint_icon(self, painter: QPainter) -> None:
        return

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

        super().mousePressEvent(event)
