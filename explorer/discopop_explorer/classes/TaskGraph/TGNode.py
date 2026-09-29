# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING, Set

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PETNode, PETNodeID, TGNodeID, PositionIndex


class TGNode(object):
    pet_node_id: PETNodeID
    level: LevelIndex  # for plotting and predecessor / successor detection
    position: PositionIndex  # for plotting
    parent_context: Set[Context]
    created_context: Optional[Context]
    state_id: Optional[int]

    def __init__(self, pet_node_id: PETNodeID, level: LevelIndex, position: PositionIndex):
        self.pet_node_id = pet_node_id
        self.level = level
        self.position = position
        self.parent_context = set()
        self.created_context = None
        self.state_id = None

    def get_label(self) -> str:
        return str(self.pet_node_id)

    def add_parent_context(self, parent_context: Context) -> None:
        self.parent_context.add(parent_context)

    def register_created_context(self, context: Context) -> None:
        self.created_context = context

    def get_pet_node(self, pet: PEGraphX) -> Optional[PETNode]:
        if self.pet_node_id is None:
            return None
        return pet.node_at(self.pet_node_id)
