# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.utilities.PEGraphConstruction.classes.LoopData import LoopData

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


# Data.xml: type="2"
class LoopNode(Node):
    loop_iterations: int = -1
    contains_array_reduction: bool = False
    loop_data: Optional[LoopData]
    loop_indices: List[str]

    def __init__(self, node_id: NodeID):
        super().__init__(node_id)
        self.type = NodeType.LOOP
        self.loop_indices = []

    def get_nesting_level(self, pet: PEGraphX, return_invert_result: bool = True) -> int:
        """Returns the loop nesting level for the given loop node.
        Currently, due to the profiling output, only 3 nesting levels of loops can be mapped correctly.
        Innermost level is 0.
        Outermost (maximum) level is 2.
        The order of the results originates from the LoopStack used during the profiling.

        Example:
        main(){
            for(){ // level 1
                for(){}     // level 0
            }
        }
        """
        parents = [s for s, t, d in in_edges(pet, self.id, EdgeType.CHILD)]

        # count levels upwards
        parent_nesting_levels: List[int] = []
        for parent_id in parents:
            parent_node = pet.node_at(parent_id)
            if type(parent_node) == FunctionNode:
                # loop is a direct child of a function node --> Nesting level 0
                parent_nesting_levels.append(0)
                break
            elif type(parent_node) == LoopNode:
                parent_nesting_levels.append(
                    min(
                        2,
                        parent_node.get_nesting_level(pet, return_invert_result=False),
                    )
                )

        if return_invert_result:
            # invert the leveling and cutoff at 0
            inverted_levels = [max(0, 2 - level) for level in parent_nesting_levels]
            return min(inverted_levels)
        else:
            return max(parent_nesting_levels)

    def get_entry_node(self, pet: PEGraphX) -> Optional[Node]:
        """returns the first CU Node contained in the loop (i.e. one without predecessor inside the loop)"""
        for node in direct_children(pet, self):
            predecessors_outside_loop_body = [
                s
                for s, t, d in in_edges(pet, node.id, EdgeType.SUCCESSOR)
                if pet.node_at(s) not in direct_children(pet, self)
            ]
            if len(predecessors_outside_loop_body) > 0:
                return node
        return None
