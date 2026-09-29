# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Optional

from discopop_explorer.classes.TaskGraph.Aliases import PETNodeID
from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PositionIndex
from discopop_explorer.classes.TaskGraph.TGNode import TGNode


class TGStartIterationNode(TGNode):
    parent_loop_pet_node_id: PETNodeID = None
    # iteration ids corresponding to this object as reported by the profiler as part of the reported _loopstate in the callstates
    # one iteration object will get iteration id 1 assigned, the other one the ids 0 and 2.
    # This is not perferct, as it might lead to missed dependencies between states 0 and 2.
    # This potential problem might be fixed in the future by creating a third Iteration object.
    loopstate_iteration_ids: Optional[List[int]] = None

    pass

    def get_label(self) -> str:
        return "Start IT " + str(self.pet_node_id) + "\nstate_id: " + str(self.state_id)

    def __init__(
        self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex, parent_loop_pet_node_id: PETNodeID
    ) -> None:
        self.parent_loop_pet_node_id = parent_loop_pet_node_id
        super().__init__(pet_node_id, level, position)

    def set_loopstate_iteration_ids(self, loopstate_iteration_ids: List[int]) -> None:
        self.loopstate_iteration_ids = loopstate_iteration_ids
