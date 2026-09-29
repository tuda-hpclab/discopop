# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Callable, Tuple

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.edges import count_edges, in_edges, out_edges

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _sample_pet(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> Tuple[PEGraphX, Node, Node, Node]:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "x"
    pet = build_pet_graph(
        [main, cu1, cu2],
        [
            (main.id, cu1.id, EdgeType.CHILD),
            (main.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, EdgeType.SUCCESSOR),
            (cu1.id, cu2.id, dep),
        ],
    )
    return pet, main, cu1, cu2


def test_out_edges_no_filter_returns_all(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = out_edges(pet, cu1.id)
    assert {e[2].etype for e in edges} == {EdgeType.SUCCESSOR, EdgeType.DATA}


def test_out_edges_filters_by_single_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = out_edges(pet, cu1.id, EdgeType.SUCCESSOR)
    assert len(edges) == 1
    assert edges[0][0] == cu1.id and edges[0][1] == cu2.id


def test_out_edges_filters_by_type_list(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = out_edges(pet, main.id, [EdgeType.CHILD, EdgeType.DATA])
    assert {e[1] for e in edges} == {cu1.id, cu2.id}


def test_in_edges_no_filter_returns_all(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = in_edges(pet, cu2.id)
    assert {e[2].etype for e in edges} == {EdgeType.CHILD, EdgeType.SUCCESSOR, EdgeType.DATA}


def test_in_edges_filters_by_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = in_edges(pet, cu2.id, EdgeType.CHILD)
    assert len(edges) == 1
    assert edges[0][0] == main.id


def test_in_edges_filters_by_type_list(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    edges = in_edges(pet, cu2.id, [EdgeType.SUCCESSOR, EdgeType.DATA])
    assert {e[2].etype for e in edges} == {EdgeType.SUCCESSOR, EdgeType.DATA}


def test_in_edges_no_match_returns_empty(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert in_edges(pet, main.id, EdgeType.CHILD) == []


def test_count_edges_no_filter_counts_all(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert count_edges(pet) == 4


def test_count_edges_filters_by_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert count_edges(pet, EdgeType.CHILD) == 2
    assert count_edges(pet, EdgeType.DATA) == 1


def test_count_edges_filters_by_type_list(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, main, cu1, cu2 = _sample_pet(make_node, build_pet_graph)
    assert count_edges(pet, [EdgeType.SUCCESSOR, EdgeType.DATA]) == 2
