# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from collections import deque
from typing import Deque, List
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors


def is_predecessor(pet: PEGraphX, source_id: NodeID, target_id: NodeID) -> bool:
    """returns true, if source is a predecessor of target.
    This analysis includes traversal of successor, child and calls edges."""
    # if source and target_id are located within differenct functions, consider the callees instead of source_id
    source_parent_function = get_parent_function(pet, pet.node_at(source_id))
    target_parent_function = get_parent_function(pet, pet.node_at(target_id))
    if source_parent_function != target_parent_function:
        for callee_id in [s for s, _, _ in in_edges(pet, source_parent_function.id, EdgeType.CALLSNODE)]:
            if is_predecessor(pet, callee_id, target_id):
                return True

    # if target is a loop node, get the first child of the loop, i.e. the entry node into the loop
    target_node = pet.node_at(target_id)
    if target_node.type == NodeType.LOOP:
        target_id = direct_children(pet, target_node)[0].id

    # perform a bfs search for target
    queue: Deque[NodeID] = deque([source_id])
    visited: List[NodeID] = []
    while queue:
        current = queue.popleft()
        if current == target_id:
            return True
        visited.append(current)
        # add direct successors to queue
        queue += [
            n.id for n in direct_successors(pet, pet.node_at(current)) if n.id not in visited and n.id not in queue
        ]
        # add children to queue
        queue += [n.id for n in direct_children(pet, pet.node_at(current)) if n.id not in visited and n.id not in queue]
        # add called functions to queue
        queue += [t for _, t, _ in out_edges(pet, current, EdgeType.CALLSNODE) if t not in visited and t not in queue]
    return False
