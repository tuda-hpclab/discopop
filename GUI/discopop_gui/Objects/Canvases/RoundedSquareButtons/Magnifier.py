# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_gui.Objects.Canvases.RoundedSquareButtons.RoundedSquareButton import RoundedSquareButton

class Magnifier(RoundedSquareButton):
    def draw(self) -> None:
        super().draw()
        self.draw_magnifier()

    def draw_magnifier(self) -> None:
        color = "black"

        self.create_oval(9, 8, 23, 22, outline=color, width=2)
        self.create_line(21, 20, 29, 28, fill=color, width=3)