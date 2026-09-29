# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.TaskGraph.Aliases import PETNodeID
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context


class FunctionContext(Context):
    parent_function: PETNodeID

    def __init__(self, parent_function: PETNodeID):
        self.parent_function = parent_function
        super().__init__()

    def is_function_context(self) -> bool:
        return True

    def get_plot_border_color(self) -> str:
        return "b"

    def get_plot_face_color(self) -> str:
        return "lightgrey"

    def get_label(self) -> str:
        label = "Function " + str(self.parent_function)
        label += "\nstate_ids: " + str(self.get_state_ids())
        return label
