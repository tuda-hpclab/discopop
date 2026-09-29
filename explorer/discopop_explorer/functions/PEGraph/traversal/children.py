# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from typing import TYPE_CHECKING, List, Type

from discopop_explorer.classes.PEGraph.NodeT import NodeT
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
    from discopop_explorer.classes.PEGraph.Node import Node


def direct_children_or_called_nodes(pet: PEGraphX, root: Node) -> List[Node]:
    """Gets direct children of any type. Also includes nodes of called functions

    :param root: root node
    :return: list of direct children
    """
    return [pet.node_at(t) for s, t, d in out_edges(pet, root.id, [EdgeType.CHILD, EdgeType.CALLSNODE])]


def direct_children(pet: PEGraphX, root: Node) -> List[Node]:
    """Gets direct children of any type. This includes called nodes!

    :param root: root node
    :return: list of direct children
    """
    return [pet.node_at(t) for s, t, d in out_edges(pet, root.id, EdgeType.CHILD)]


def direct_children_or_called_nodes_of_type(pet: PEGraphX, root: Node, type: Type[NodeT]) -> List[NodeT]:
    """Gets only direct children of specified type. This includes called nodes!

    :param root: root node
    :param type: type of children
    :return: list of direct children
    """
    nodes = [pet.node_at(t) for s, t, d in out_edges(pet, root.id, [EdgeType.CHILD, EdgeType.CALLSNODE])]

    return [t for t in nodes if isinstance(t, type)]


def get_entry_child(pet: PEGraphX, root: Node) -> List[Node]:
    """Gets direct children of any type with no incoming successor edge without considering called nodes

    :param root: root node
    :return: list of direct children
    """
    return [
        pet.node_at(t)
        for s, t, d in out_edges(pet, root.id, EdgeType.CHILD)
        if len(in_edges(pet, t, EdgeType.SUCCESSOR)) == 0
    ]
