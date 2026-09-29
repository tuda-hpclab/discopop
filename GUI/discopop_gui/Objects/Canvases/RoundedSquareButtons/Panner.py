# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (center) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton

class Panner(RoundedSquareButton):
    def draw(self) -> None:
        super().draw()
        self._draw_panner()

    def _draw_panner(self) -> None:
        center = self._size / 2
        color = "black"

        self.create_line(center, 9, center, self._size - 9, fill = color, width = 2)
        self.create_line(9, center, self._size - 9, center, fill = color, width = 2)

        self.create_line(center, 9, center - 3, 12, fill = color, width = 2)
        self.create_line(center, 9, center + 3, 12, fill = color, width = 2)

        self.create_line(center, self._size - 9, center - 3, self._size - 12, fill = color, width = 2)
        self.create_line(center, self._size - 9, center + 3, self._size - 12, fill = color, width = 2)

        self.create_line(9, center, 12, center - 3, fill = color, width = 2)
        self.create_line(9, center, 12, center + 3, fill = color, width = 2)

        self.create_line(self._size - 9, center, self._size - 12, center - 3, fill = color, width = 2)
        self.create_line(self._size - 9, center, self._size - 12, center + 3, fill = color, width = 2)