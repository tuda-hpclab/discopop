# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING, Any, List, Set, Tuple, Type, Union, overload
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.NodeT import NodeT

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children, direct_children_or_called_nodes
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function


def get_left_right_subtree(
    self: PEGraphX, target: Node, right_subtree: bool, ignore_called_nodes: bool = False
) -> List[Node]:
    """Searches for all subnodes of main which are to the left or to the right of the specified node

    :param target: node that divides the tree
    :param right_subtree: true - right subtree, false - left subtree
    :return: list of nodes in the subtree
    """
    stack: List[Node] = []
    res: List[Node] = []
    visited = set()

    parent_func = get_parent_function(self, target)
    stack.append(parent_func)

    while stack:
        current = stack.pop()

        if current == target:
            return res
        if isinstance(current, CUNode):
            res.append(current)

        if current in visited:  # suppress looping
            continue
        else:
            visited.add(current)

        if not ignore_called_nodes:
            stack.extend(
                direct_children_or_called_nodes(self, current)
                if right_subtree
                else reversed(direct_children_or_called_nodes(self, current))
            )
        else:
            stack.extend(direct_children(self, current) if right_subtree else reversed(direct_children(self, current)))
    return res


@overload
def subtree_of_type(pet: PEGraphX, root: Node, ignore_called_functions: bool = True) -> List[Node]: ...


@overload
def subtree_of_type(
    pet: PEGraphX, root: Node, type: Union[Type[NodeT], Tuple[Type[NodeT], ...]], ignore_called_functions: bool = True
) -> List[NodeT]: ...


def subtree_of_type(pet: PEGraphX, root: Node, type: Any = Node, ignore_called_functions: bool = True) -> List[NodeT]:  # type: ignore
    """Gets all nodes in subtree of specified type including root

    :param root: root node
    :param type: type of children, None is equal to a wildcard
    :return: list of nodes in subtree
    """
    return subtree_of_type_rec(pet, root, set(), type, ignore_called_functions=ignore_called_functions)


@overload
def subtree_of_type_rec(
    pet: PEGraphX, root: Node, visited: Set[Node], ignore_called_functions: bool = True
) -> List[Node]: ...


@overload
def subtree_of_type_rec(
    pet: PEGraphX,
    root: Node,
    visited: Set[Node],
    type: Union[Type[NodeT], Tuple[Type[NodeT], ...]],
    ignore_called_functions: bool = True,
) -> List[NodeT]: ...


def subtree_of_type_rec(  # type: ignore
    pet: PEGraphX, root: Node, visited: Set[Node], type: Any = Node, ignore_called_functions: bool = True
) -> List[NodeT]:
    """recursive helper function for subtree_of_type"""
    # check if root is of type target
    res = []
    if isinstance(root, type):
        res.append(root)

    # append root to visited
    visited.add(root)

    # enter recursion
    edge_types = [EdgeType.CHILD] if ignore_called_functions else [EdgeType.CHILD, EdgeType.CALLSNODE]
    for _, target, _ in out_edges(pet, root.id, edge_types):
        # prevent cycles
        if pet.node_at(target) in visited:
            continue
        res += subtree_of_type_rec(
            pet, pet.node_at(target), visited, type, ignore_called_functions=ignore_called_functions
        )

    return res
