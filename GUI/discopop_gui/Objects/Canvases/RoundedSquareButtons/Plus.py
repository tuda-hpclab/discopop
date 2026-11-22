# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton


class Plus(RoundedSquareButton):
    def __init__(
        self,
        parent: QWidget | None,
        command: Any,
        colour: str = "green",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._colour = colour
        super().__init__(parent, command, *args, **kwargs)

    def _paint_icon(self, painter: QPainter) -> None:
        margin = 0.28 * self._size
        width = max(1, int(self._size * 0.08))
        painter.setPen(QPen(QColor(self._colour), width))
        painter.drawLine(
            int(self._size / 2),
            int(margin),
            int(self._size / 2),
            int(self._size - margin),
        )
        painter.drawLine(
            int(margin),
            int(self._size / 2),
            int(self._size - margin),
            int(self._size / 2),
        )
