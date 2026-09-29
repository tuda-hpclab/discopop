# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (center) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton

class Mouse(RoundedSquareButton):
    def draw(self) -> None:
        super().draw()
        self._draw_mouse()

    def _draw_mouse(self) -> None:
        color = "black"

        points = [
            0.30 * self._size, 0.20 * self._size,
            0.30 * self._size, 0.75 * self._size,
            0.43 * self._size, 0.62 * self._size,
            0.56 * self._size, 0.88 * self._size,
            0.66 * self._size, 0.82 * self._size,
            0.52 * self._size, 0.56 * self._size,
            0.78 * self._size, 0.56 * self._size
        ]

        self.create_polygon(
            points,
            outline = color,
            fill = "",
            width = max(1, int(self._size * 0.06))
        )