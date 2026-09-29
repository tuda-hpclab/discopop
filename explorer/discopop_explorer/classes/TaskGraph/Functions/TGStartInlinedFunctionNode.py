# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional

from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PETNodeID, PositionIndex


class TGStartInlinedFunctionNode(TGNode):

    call_instruction_id: Optional[int] = None

    def __init__(
        self,
        pet_node_id: PETNodeID,
        level: LevelIndex,
        position: PositionIndex,
        call_instruction_id: Optional[int] = None,
    ):
        self.call_instruction_id = call_instruction_id
        super().__init__(pet_node_id, level, position)

    def get_label(self) -> str:
        return "Start inline FN " + str(self.pet_node_id)
