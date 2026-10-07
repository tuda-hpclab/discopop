# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable


class RoundedSquareButton(tk.Canvas):
    def __init__(
        self, parent: tk.Misc, command: Callable[[], None], size: int = 36, radius: int = 8, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(
            parent,
            width=size,
            height=size,
            highlightthickness=0,
            bg=parent.cget("bg"),
            *args,
            **kwargs,
        )

        self._command = command
        self._size = size
        self._radius = radius
        self._selected = False

        self.bind("<Button-1>", self._on_click)
        self.draw()

    def _on_click(self, event: tk.Event[tk.Canvas]) -> None:
        self._command()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.draw()

    def draw(self) -> None:
        self.delete("all")

        fill = "#cfe8ff" if self._selected else "#f2f2f2"
        outline = "#2f80ed" if self._selected else "#999999"

        self.create_round_rect(
            2,
            2,
            self._size - 2,
            self._size - 2,
            self._radius,
            fill=fill,
            outline=outline,
            width=2,
        )

    def create_round_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        r: float,
        **kwargs: Any,
    ) -> int:
        points = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]

        return self.create_polygon(points, smooth=True, **kwargs)
