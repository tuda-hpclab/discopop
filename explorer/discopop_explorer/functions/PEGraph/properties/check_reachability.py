# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from collections import deque
from typing import List
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges


def check_reachability(pet: PEGraphX, target: Node, source: Node, edge_types: List[EdgeType]) -> bool:
    """check if target is reachable from source via edges of types edge_type.
    :param pet: PET graph
    :param source: CUNode
    :param target: CUNode
    :param edge_types: List[EdgeType]
    :return: Boolean"""
    if source == target:
        return True
    visited: List[str] = []
    queue = deque([target])
    while len(queue) > 0:
        cur_node = queue.popleft()
        visited.append(cur_node.id)
        tmp_list = [(s, t, e) for s, t, e in in_edges(pet, cur_node.id) if s not in visited and e.etype in edge_types]
        for e in tmp_list:
            if pet.node_at(e[0]) == source:
                return True
            else:
                if e[0] not in visited:
                    queue.append(pet.node_at(e[0]))
    return False
