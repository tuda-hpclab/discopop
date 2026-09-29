# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
from typing import Any, Callable

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton

class Cross(RoundedSquareButton):
    def __init__(
        self,
        parent : tk.Misc,
        command : Callable[[], None],
        colour : str = "red",
        *args : Any,
        **kwargs : Any,
    ) -> None:
        self._colour = colour
        super().__init__(parent, command, *args, **kwargs)

    def draw(self) -> None:
        super().draw()
        self._draw_cross()

    def _draw_cross(self) -> None:
        margin = 0.28 * self._size
        width = max(1, int(self._size * 0.08))

        self.create_line(
            margin,
            margin,
            self._size - margin,
            self._size - margin,
            fill=self._colour,
            width=width,
        )

        self.create_line(
            self._size - margin,
            margin,
            margin,
            self._size - margin,
            fill=self._colour,
            width=width,
        )