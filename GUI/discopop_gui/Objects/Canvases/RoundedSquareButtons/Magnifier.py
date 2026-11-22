# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from PySide6.QtGui import QColor, QPainter, QPen

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton

class Magnifier(RoundedSquareButton):
    def _paint_icon(self, painter: QPainter) -> None:
        color = "black"

        painter.setPen(QPen(QColor(color), 2))
        painter.drawEllipse(9, 8, 14, 14)
        painter.setPen(QPen(QColor(color), 3))
        painter.drawLine(21, 20, 29, 28)
