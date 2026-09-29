# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Callable

from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.task_parallelism.classes import Task
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    check_neighbours,
    check_reachability,
    contains_reduction,
    get_cus_inside_function,
    get_parent_of_type,
    get_predecessor_nodes,
    line_contained_in_region,
)

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


# --- line_contained_in_region ---------------------------------------------------


def test_line_contained_in_region_true_within_bounds() -> None:
    assert line_contained_in_region("1:5", "1:1", "1:10") is True


def test_line_contained_in_region_true_at_boundaries() -> None:
    assert line_contained_in_region("1:1", "1:1", "1:10") is True
    assert line_contained_in_region("1:10", "1:1", "1:10") is True


def test_line_contained_in_region_false_outside_bounds() -> None:
    assert line_contained_in_region("1:0", "1:1", "1:10") is False
    assert line_contained_in_region("1:11", "1:1", "1:10") is False


def test_line_contained_in_region_false_for_different_file_id() -> None:
    assert line_contained_in_region("2:5", "1:1", "1:10") is False


# --- get_parent_of_type -----------------------------------------------------------


def test_get_parent_of_type_finds_ancestor_and_the_last_node_on_the_path(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [main, loop, cu],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, cu.id, EdgeType.CHILD)],
    )
    result = get_parent_of_type(pet, cu, NodeType.FUNC, EdgeType.CHILD, only_first=True)
    assert result == [(main, loop)]


def test_get_parent_of_type_empty_when_no_ancestor_matches(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([main, cu], [(main.id, cu.id, EdgeType.CHILD)])
    assert get_parent_of_type(pet, cu, NodeType.LOOP, EdgeType.CHILD, only_first=True) == []


def test_get_parent_of_type_only_first_returns_a_single_match(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    loop1 = make_node("1:1", NodeType.LOOP, name="loop1")
    loop2 = make_node("1:2", NodeType.LOOP, name="loop2")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [loop1, loop2, cu],
        [(loop1.id, cu.id, EdgeType.CHILD), (loop2.id, cu.id, EdgeType.CHILD)],
    )
    result = get_parent_of_type(pet, cu, NodeType.LOOP, EdgeType.CHILD, only_first=True)
    assert len(result) == 1
    assert result[0][0] in (loop1, loop2)


def test_get_parent_of_type_collects_all_matches_when_not_only_first(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    loop1 = make_node("1:1", NodeType.LOOP, name="loop1")
    loop2 = make_node("1:2", NodeType.LOOP, name="loop2")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [loop1, loop2, cu],
        [(loop1.id, cu.id, EdgeType.CHILD), (loop2.id, cu.id, EdgeType.CHILD)],
    )
    result = get_parent_of_type(pet, cu, NodeType.LOOP, EdgeType.CHILD, only_first=False)
    assert {r[0].id for r in result} == {loop1.id, loop2.id}
    assert all(r[1] == cu for r in result)


# --- get_cus_inside_function -------------------------------------------------------


def test_get_cus_inside_function_collects_all_descendants(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    func = make_node("1:1", NodeType.FUNC, name="func")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    cu1 = make_node("1:3", NodeType.CU, name="cu1")
    cu2 = make_node("1:4", NodeType.CU, name="cu2")
    pet = build_pet_graph(
        [func, loop, cu1, cu2],
        [
            (func.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
        ],
    )
    result = get_cus_inside_function(pet, func)
    assert {n.id for n in result} == {func.id, loop.id, cu1.id, cu2.id}


def test_get_cus_inside_function_single_node_without_children(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu")
    pet = build_pet_graph([cu])
    assert get_cus_inside_function(pet, cu) == [cu]


# --- check_reachability -------------------------------------------------------------


def test_check_reachability_true_for_identical_nodes(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu")
    pet = build_pet_graph([cu])
    assert check_reachability(pet, cu, cu, [EdgeType.SUCCESSOR]) is True


def test_check_reachability_true_along_successor_chain(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, EdgeType.SUCCESSOR)])
    assert check_reachability(pet, cu2, cu1, [EdgeType.SUCCESSOR]) is True


def test_check_reachability_false_in_wrong_direction(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, EdgeType.SUCCESSOR)])
    assert check_reachability(pet, cu1, cu2, [EdgeType.SUCCESSOR]) is False


def test_check_reachability_false_for_mismatched_edge_type(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    pet = build_pet_graph([cu1, cu2], [(cu1.id, cu2.id, EdgeType.CHILD)])
    assert check_reachability(pet, cu2, cu1, [EdgeType.SUCCESSOR]) is False


# --- get_predecessor_nodes ----------------------------------------------------------


def test_get_predecessor_nodes_follows_successor_chain(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2")
    cu3 = make_node("1:3", NodeType.CU, name="cu3")
    pet = build_pet_graph(
        [cu1, cu2, cu3],
        [(cu1.id, cu2.id, EdgeType.SUCCESSOR), (cu2.id, cu3.id, EdgeType.SUCCESSOR)],
    )
    result, visited = get_predecessor_nodes(pet, cu3, [])
    assert result == [cu3, cu2, cu1]


def test_get_predecessor_nodes_stops_at_barrier(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu1 = make_node("1:1", NodeType.CU, name="cu1")
    cu2 = make_node("1:2", NodeType.CU, name="cu2", tp_contains_taskwait=True)
    cu3 = make_node("1:3", NodeType.CU, name="cu3")
    pet = build_pet_graph(
        [cu1, cu2, cu3],
        [(cu1.id, cu2.id, EdgeType.SUCCESSOR), (cu2.id, cu3.id, EdgeType.SUCCESSOR)],
    )
    result, visited = get_predecessor_nodes(pet, cu3, [])
    assert result == [cu3, cu2]


def test_get_predecessor_nodes_stops_at_function_node(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    func = make_node("1:1", NodeType.FUNC, name="func")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([func, cu], [(func.id, cu.id, EdgeType.SUCCESSOR)])
    result, visited = get_predecessor_nodes(pet, cu, [])
    assert result == [cu, func]


# --- check_neighbours ----------------------------------------------------------------


def test_check_neighbours_true_when_adjacent(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    n1 = make_node("1:1", NodeType.CU, name="cu1", start_line=1, end_line=5)
    n2 = make_node("1:2", NodeType.CU, name="cu2", start_line=5, end_line=8)
    pet = build_pet_graph([n1, n2])
    assert check_neighbours(Task(pet, n1), Task(pet, n2)) is True


def test_check_neighbours_true_within_gap_of_two_lines(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    n1 = make_node("1:1", NodeType.CU, name="cu1", start_line=1, end_line=5)
    n2 = make_node("1:2", NodeType.CU, name="cu2", start_line=7, end_line=9)
    pet = build_pet_graph([n1, n2])
    assert check_neighbours(Task(pet, n1), Task(pet, n2)) is True


def test_check_neighbours_false_when_far_apart(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    n1 = make_node("1:1", NodeType.CU, name="cu1", start_line=1, end_line=5)
    n2 = make_node("1:2", NodeType.CU, name="cu2", start_line=20, end_line=25)
    pet = build_pet_graph([n1, n2])
    assert check_neighbours(Task(pet, n1), Task(pet, n2)) is False


# --- contains_reduction ---------------------------------------------------------------


def test_contains_reduction_true_when_reduction_line_within_node(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu", start_line=1, end_line=10)
    pet = build_pet_graph([cu], reduction_vars=[{"reduction_line": "1:5", "name": "sum"}])
    assert contains_reduction(pet, cu) is True


def test_contains_reduction_false_when_no_reduction_vars(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu", start_line=1, end_line=10)
    pet = build_pet_graph([cu])
    assert contains_reduction(pet, cu) is False


def test_contains_reduction_false_when_reduction_line_outside_node(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    cu = make_node("1:1", NodeType.CU, name="cu", start_line=1, end_line=10)
    pet = build_pet_graph([cu], reduction_vars=[{"reduction_line": "1:50", "name": "sum"}])
    assert contains_reduction(pet, cu) is False
