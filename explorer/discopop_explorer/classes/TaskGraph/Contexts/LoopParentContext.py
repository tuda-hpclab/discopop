# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Optional, Tuple

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.classes.TaskGraph.Aliases import PETNodeID
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context


class LoopParentContext(Context):
    parent_loop: PETNodeID
    loopstate_position: Optional[int] = None
    loop_variables: List[Tuple[str, MemoryRegion]]
    pass

    def __init__(self, parent_loop: PETNodeID, loopstate_position: Optional[int] = None):
        self.parent_loop = parent_loop
        self.loopstate_position = loopstate_position
        self.loop_variables = []
        super().__init__()

    def get_plot_border_color(self) -> str:
        return "b"

    def get_plot_face_color(self) -> str:
        return "cyan"

    def get_label(self) -> str:
        return "LoopParent " + str(self.parent_loop) + "\nstate_ids: " + str(self.get_state_ids())
