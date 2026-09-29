# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import copy
from typing import List, Set
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children


def get_num_function_calls(pet: PEGraphX, node: Node, visited: List[Node]) -> int:
    function_calls = 0
    visited.append(node)

    for child in direct_children(pet, node):
        out_call_edges = out_edges(pet, child.id, EdgeType.CALLSNODE)
        if len(out_call_edges) > 0:
            for _, t, _ in out_call_edges:
                function_calls += 1
                if t in visited:
                    continue
                function_calls += get_num_function_calls(pet, pet.node_at(t), copy.deepcopy(visited))
        else:
            if child in visited:
                continue
            function_calls += get_num_function_calls(pet, child, copy.deepcopy(visited))

    return function_calls
