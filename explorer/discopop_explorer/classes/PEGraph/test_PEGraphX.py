# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Callable, cast

import pytest

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


# --- node_at -----------------------------------------------------------------


def test_node_at_returns_the_node_added_to_the_graph(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu")
    pet = build_pet_graph([cu])
    assert pet.node_at(cu.id) is cu


# --- get_node_parent_id -------------------------------------------------------


def test_get_node_parent_id_returns_none_without_parent(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu")
    pet = build_pet_graph([cu])
    assert pet.get_node_parent_id(cu) is None


def test_get_node_parent_id_returns_single_parent(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([main, cu], [(main.id, cu.id, EdgeType.CHILD)])
    assert pet.get_node_parent_id(cu) == main.id


def test_get_node_parent_id_skips_function_type_parent_when_two_parents(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    # a node can have both a loop parent and a (redundant) function parent;
    # the non-function parent should be preferred.
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [main, loop, cu],
        [(main.id, cu.id, EdgeType.CHILD), (loop.id, cu.id, EdgeType.CHILD)],
    )
    assert pet.get_node_parent_id(cu) == loop.id


def test_get_node_parent_id_raises_for_more_than_two_parents(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop1 = make_node("1:2", NodeType.LOOP, name="loop1")
    loop2 = make_node("1:3", NodeType.LOOP, name="loop2")
    cu = make_node("1:4", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [main, loop1, loop2, cu],
        [
            (main.id, cu.id, EdgeType.CHILD),
            (loop1.id, cu.id, EdgeType.CHILD),
            (loop2.id, cu.id, EdgeType.CHILD),
        ],
    )
    with pytest.raises(ValueError):
        pet.get_node_parent_id(cu)


# --- get_dep -------------------------------------------------------------------


def test_get_dep_returns_matching_outgoing_dependency(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    raw_dep = Dependency(EdgeType.DATA)
    raw_dep.dtype = DepType.RAW
    war_dep = Dependency(EdgeType.DATA)
    war_dep.dtype = DepType.WAR
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, raw_dep), (cu1.id, cu2.id, war_dep)])

    raw_results = pet.get_dep(cu1, DepType.RAW, reversed=False)
    assert len(raw_results) == 1
    assert raw_results[0][2] is raw_dep


def test_get_dep_reversed_looks_at_incoming_edges(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    raw_dep = Dependency(EdgeType.DATA)
    raw_dep.dtype = DepType.RAW
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, raw_dep)])

    assert pet.get_dep(cu2, DepType.RAW, reversed=True) == [(cu1.id, cu2.id, raw_dep)]
    assert pet.get_dep(cu1, DepType.RAW, reversed=True) == []


def test_get_dep_filters_by_dep_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    raw_dep = Dependency(EdgeType.DATA)
    raw_dep.dtype = DepType.RAW
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, raw_dep)])

    assert pet.get_dep(cu1, DepType.WAW, reversed=False) == []


# --- path ------------------------------------------------------------------


def test_path_finds_route_over_child_edges(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [main, loop, cu],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, cu.id, EdgeType.CHILD)],
    )
    assert pet.path(main, cu) == [main, loop, cu]


def test_path_follows_calls_node_edges(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    pet = build_pet_graph([cu, helper], [(cu.id, helper.id, EdgeType.CALLSNODE)])
    assert pet.path(cu, helper) == [cu, helper]


def test_path_returns_empty_list_when_unreachable(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    pet = build_pet_graph([cu1, cu2])
    assert pet.path(cu1, cu2) == []


# --- validate ----------------------------------------------------------------


def test_validate_widens_function_bounds_to_cover_children(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main", start_line=5, end_line=5)
    cu1 = make_node("1:2", NodeType.CU, name="cu1", start_line=2, end_line=2)
    cu2 = make_node("1:3", NodeType.CU, name="cu2", start_line=10, end_line=10)
    pet = build_pet_graph(
        [main, cu1, cu2],
        [(main.id, cu1.id, EdgeType.CHILD), (main.id, cu2.id, EdgeType.CHILD)],
    )
    pet.validate()
    assert main.start_line == 2
    assert main.end_line == 10


def test_validate_keeps_bounds_when_children_are_within_range(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main", start_line=1, end_line=10)
    cu1 = make_node("1:2", NodeType.CU, name="cu1", start_line=2, end_line=2)
    pet = build_pet_graph([main, cu1], [(main.id, cu1.id, EdgeType.CHILD)])
    pet.validate()
    assert main.start_line == 1
    assert main.end_line == 10


# --- calculateLoopMetadata -----------------------------------------------------


def test_calculate_loop_metadata_identifies_loop_index(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=8)
    header = make_node(
        "1:3",
        NodeType.CU,
        name="header",
        start_line=5,
        end_line=5,
        local_vars=[Variable("int", VarName("i"), "1:5")],
        global_vars=[],
    )
    self_dep = Dependency(EdgeType.DATA)
    self_dep.dtype = DepType.RAW
    self_dep.var_name = "i"
    self_dep.source_line = LineID("1:5")
    self_dep.sink_line = LineID("1:5")
    pet = build_pet_graph(
        [main, loop, header],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, header.id, EdgeType.CHILD),
            (header.id, header.id, self_dep),
        ],
    )
    pet.calculateLoopMetadata()
    assert cast(LoopNode, loop).loop_indices == ["i"]


def test_calculate_loop_metadata_no_index_without_matching_dependency(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop", start_line=5, end_line=8)
    header = make_node(
        "1:2",
        NodeType.CU,
        name="header",
        start_line=5,
        end_line=5,
        local_vars=[Variable("int", VarName("i"), "1:5")],
        global_vars=[],
    )
    pet = build_pet_graph([loop, header], [(loop.id, header.id, EdgeType.CHILD)])
    pet.calculateLoopMetadata()
    assert cast(LoopNode, loop).loop_indices == []


# --- enforce_single_function_exit_node -----------------------------------------


def test_enforce_single_function_exit_node_adds_exit_node_after_last_successor(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu1 = make_node("1:2", NodeType.CU, name="cu1", start_line=1, end_line=1)
    cu2 = make_node("1:3", NodeType.CU, name="cu2", start_line=2, end_line=2)
    pet = build_pet_graph(
        [main, cu1, cu2],
        [
            (main.id, cu1.id, EdgeType.CHILD),
            (main.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, EdgeType.SUCCESSOR),
        ],
    )
    pet.enforce_single_function_exit_node()

    exit_node = pet.node_at(NodeID("1:4"))
    assert exit_node.name == "FuncExit_main"
    assert exit_node.start_line == 2
    assert exit_node.end_line == 2

    from discopop_explorer.functions.PEGraph.queries.edges import in_edges

    predecessors = {s for s, t, d in in_edges(pet, exit_node.id, EdgeType.SUCCESSOR)}
    assert predecessors == {cu2.id}
