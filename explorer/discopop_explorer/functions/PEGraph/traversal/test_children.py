# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Callable, Tuple

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.traversal.children import (
    direct_children,
    direct_children_or_called_nodes,
    direct_children_or_called_nodes_of_type,
    get_entry_child,
)

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _sample_pet(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> Tuple[PEGraphX, Node, Node, Node, Node]:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    pet = build_pet_graph(
        [main, cu1, cu2, helper],
        [
            (main.id, cu1.id, EdgeType.CHILD),
            (main.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, EdgeType.SUCCESSOR),
            (cu1.id, helper.id, EdgeType.CALLSNODE),
        ],
    )
    return pet, main, cu1, cu2, helper


def test_direct_children_excludes_called_nodes(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2, helper = _sample_pet(make_node, build_pet_graph)
    assert {c.id for c in direct_children(pet, main)} == {cu1.id, cu2.id}
    assert direct_children(pet, cu1) == []


def test_direct_children_or_called_nodes_includes_calls(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2, helper = _sample_pet(make_node, build_pet_graph)
    assert {c.id for c in direct_children_or_called_nodes(pet, cu1)} == {helper.id}
    assert {c.id for c in direct_children_or_called_nodes(pet, main)} == {cu1.id, cu2.id}


def test_direct_children_or_called_nodes_of_type_filters(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2, helper = _sample_pet(make_node, build_pet_graph)
    assert direct_children_or_called_nodes_of_type(pet, cu1, FunctionNode) == [pet.node_at(helper.id)]
    assert direct_children_or_called_nodes_of_type(pet, cu1, CUNode) == []


def test_get_entry_child_returns_node_without_incoming_successor(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, main, cu1, cu2, helper = _sample_pet(make_node, build_pet_graph)
    # cu1 has no incoming SUCCESSOR edge, cu2 has one (from cu1)
    assert get_entry_child(pet, main) == [pet.node_at(cu1.id)]


def test_get_entry_child_empty_when_all_children_have_predecessors(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph(
        [main, cu1, cu2],
        [
            (main.id, cu1.id, EdgeType.CHILD),
            (main.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, EdgeType.SUCCESSOR),
            (cu2.id, cu1.id, EdgeType.SUCCESSOR),
        ],
    )
    assert get_entry_child(pet, pet.node_at(main.id)) == []
