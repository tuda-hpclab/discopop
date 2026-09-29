# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Optional

from discopop_explorer.classes.TaskGraph.Aliases import PETNodeID
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context


class InlinedFunctionContext(Context):

    call_instruction_id: Optional[int] = None

    def __init__(self, call_instruction_id: Optional[int] = None) -> None:
        self.call_instruction_id = call_instruction_id
        super().__init__()

    def get_plot_border_color(self) -> str:
        return "b"

    def get_plot_face_color(self) -> str:
        return "blue"

    def get_label(self) -> str:
        return "InlinedFunc"
