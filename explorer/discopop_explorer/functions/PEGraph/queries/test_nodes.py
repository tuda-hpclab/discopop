# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Any, Callable

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _sample_pet(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> tuple[PEGraphX, Node, Node, Node, Node]:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    cu1 = make_node("1:3", NodeType.CU, name="cu1")
    cu2 = make_node("1:4", NodeType.CU, name="cu2")
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, EdgeType.SUCCESSOR),
        ],
    )
    return pet, main, loop, cu1, cu2


def test_all_nodes_returns_every_node(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, loop, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert {n.id for n in all_nodes(pet)} == {main.id, loop.id, cu1.id, cu2.id}


def test_all_nodes_filters_by_single_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, loop, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert {n.id for n in all_nodes(pet, CUNode)} == {cu1.id, cu2.id}
    assert all_nodes(pet, FunctionNode) == [pet.node_at(main.id)]
    assert all_nodes(pet, LoopNode) == [pet.node_at(loop.id)]


def test_all_nodes_filters_by_type_tuple(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, loop, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert {n.id for n in all_nodes(pet, (FunctionNode, LoopNode))} == {main.id, loop.id}


def test_all_nodes_empty_result_for_absent_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    pet = build_pet_graph([main])
    assert all_nodes(pet, LoopNode) == []
