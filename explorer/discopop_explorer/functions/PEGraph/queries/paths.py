# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
from collections import deque
from typing import Deque, List, Tuple, cast
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function


def check_reachability_and_get_path_nodes(
    pet: PEGraphX, target: CUNode, source: CUNode, edge_types: List[EdgeType]
) -> Tuple[bool, List[CUNode]]:
    """check if target is reachable from source via edges of types edge_type.
    :param pet: PET graph
    :param source: CUNode
    :param target: CUNode
    :param edge_types: List[EdgeType]
    :return: Boolean"""
    if source == target:
        return True, []

    # trivially not reachable
    if get_parent_function(pet, target) != get_parent_function(pet, source) and EdgeType.CALLSNODE not in edge_types:
        print("TRIVIAL FALSE!: ", source, target)
        return False, []

    visited: List[NodeID] = []
    queue: Deque[Tuple[CUNode, List[CUNode]]] = deque([(target, [])])
    while len(queue) > 0:
        cur_node, cur_path = queue.popleft()
        visited.append(cur_node.id)
        tmp_list = [(s, t, e) for s, t, e in in_edges(pet, cur_node.id) if s not in visited and e.etype in edge_types]
        for e in tmp_list:
            if pet.node_at(e[0]) == source:
                return True, cur_path
            else:
                if e[0] not in visited:
                    tmp_path = copy.deepcopy(cur_path)
                    tmp_path.append(cur_node)
                    queue.append((cast(CUNode, pet.node_at(e[0])), tmp_path))
    return False, []


def get_path_nodes_between(pet: PEGraphX, target: CUNode, source: CUNode, edge_types: List[EdgeType]) -> List[CUNode]:
    """get all nodes of all patch which allow reaching target from source via edges of types edge_type.
    :param pet: PET graph
    :param source: CUNode
    :param target: CUNode
    :param edge_types: List[EdgeType]
    :return: List of encountered nodes"""

    visited: List[NodeID] = []
    queue: Deque[Tuple[CUNode, List[CUNode]]] = deque(
        [
            (cast(CUNode, pet.node_at(t)), [])
            for s, t, d in out_edges(pet, source.id, edge_types)
            if type(pet.node_at(t)) == CUNode
        ]
    )

    while len(queue) > 0:
        cur_node, cur_path = queue.popleft()
        visited.append(cur_node.id)
        tmp_list = [(s, t, e) for s, t, e in out_edges(pet, cur_node.id) if t not in visited and e.etype in edge_types]
        for e in tmp_list:
            if pet.node_at(e[1]) == target or pet.node_at(e[1]) == source:
                continue
            else:
                if e[1] not in visited:
                    tmp_path = copy.deepcopy(cur_path)
                    tmp_path.append(cur_node)
                    queue.append((cast(CUNode, pet.node_at(e[1])), tmp_path))
    return [cast(CUNode, pet.node_at(nid)) for nid in set(visited)]
