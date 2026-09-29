# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional, cast
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.NodeType import NodeType

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges


def get_parent_function(pet: PEGraphX, node: Node) -> FunctionNode:
    """Finds the parent of a node

    :param node: current node
    :return: node of parent function
    """
    if isinstance(node, FunctionNode):
        return node
    if node.parent_function_id is None:
        # no precalculated information found.
        current_node = node
        parent_node: Optional[Node] = node
        while parent_node is not None:
            current_node = parent_node
            if type(pet.node_at(current_node.id)) == FunctionNode:
                node.parent_function_id = current_node.id
                break
            parents = [e[0] for e in in_edges(pet, current_node.id, etype=EdgeType.CHILD)]
            if len(parents) == 0:
                parent_node = None
            else:
                parent_node = pet.node_at(parents[0])

    assert node.parent_function_id
    return cast(FunctionNode, pet.node_at(node.parent_function_id))


def get_all_parent_functions(pet: PEGraphX, node: Node) -> List[FunctionNode]:
    queue: List[Node] = [node]
    result: set[FunctionNode] = set()
    while queue:
        current = queue.pop()
        current_parent = get_parent_function(pet, current)
        if current_parent not in queue and current_parent not in result:
            queue.append(current_parent)
        if current_parent not in result:
            result.add(current_parent)
        for in_edge in in_edges(pet, current.id, EdgeType.CALLSNODE):
            queue.append(pet.node_at(in_edge[0]))

    return list(result)


def get_all_parents_until_function(pet: PEGraphX, node: Node) -> List[Node]:
    queue: List[Node] = [node]
    result: set[Node] = set()
    while queue:
        current = queue.pop()

        continue_search = True

        if current.type == NodeType.LOOP:
            result.add(current)
        if current.type == NodeType.FUNC:
            result.add(current)
            continue_search = False

        if continue_search:
            parents = [pet.node_at(s) for s, t, d in in_edges(pet, current.id, EdgeType.CHILD)]
            queue += [p for p in parents if p not in queue and p not in result]

    return list(result)
