# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PETNodeID, PositionIndex
from discopop_explorer.classes.TaskGraph.TGNode import TGNode


class TGEndIterationNode(TGNode):
    parent_loop_pet_node_id: PETNodeID = None
    pass

    def get_label(self) -> str:
        return "END IT " + str(self.pet_node_id)

    def __init__(
        self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex, parent_loop_pet_node_id: PETNodeID
    ):
        self.parent_loop_pet_node_id = parent_loop_pet_node_id
        super().__init__(pet_node_id, level, position)
