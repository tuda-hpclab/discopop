# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
from typing import List
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children


def get_outgoing_call_path_depth(pet: PEGraphX, node: Node) -> int:
    visited: List[Node] = []
    queue: List[tuple[Node, int]] = [(node, 0)]
    child_depths: List[int] = [0]
    visited.append(node)

    while queue:
        cur_node, cur_call_depth = queue.pop()
        visited.append(cur_node)

        for child in direct_children(pet, cur_node):
            out_call_edges = out_edges(pet, child.id, EdgeType.CALLSNODE)
            if len(out_call_edges) > 0:
                for _, t, _ in out_call_edges:
                    if pet.node_at(t) in visited:
                        continue
                    child_depths.append(cur_call_depth + 1)
                    queue.append((pet.node_at(t), cur_call_depth + 1))
            if child not in visited:
                queue.append((child, cur_call_depth))

    return max(child_depths)
