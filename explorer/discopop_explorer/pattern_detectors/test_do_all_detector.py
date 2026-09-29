# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import sys
from typing import Callable, cast

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.do_all_detector import (
    __calculate_nesting_level,
    __check_for_problematic_function_argument_access,
    __detect_do_all,
    __get_called_functions,
    __get_parent_loops,
)

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _loop(node: Node) -> LoopNode:
    return cast(LoopNode, node)


# --- __calculate_nesting_level -------------------------------------------------


def test_calculate_nesting_level_zero_for_direct_child(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([loop, cu], [(loop.id, cu.id, EdgeType.CHILD)])
    assert __calculate_nesting_level(pet, _loop(loop), cu.id) == 0


def test_calculate_nesting_level_counts_intermediate_ancestors(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    outer = make_node("1:1", NodeType.LOOP, name="outer")
    inner = make_node("1:2", NodeType.LOOP, name="inner")
    cu = make_node("1:3", NodeType.CU, name="cu")
    pet = build_pet_graph(
        [outer, inner, cu],
        [(outer.id, inner.id, EdgeType.CHILD), (inner.id, cu.id, EdgeType.CHILD)],
    )
    assert __calculate_nesting_level(pet, _loop(outer), cu.id) == 1


def test_calculate_nesting_level_returns_maxsize_when_unrelated(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([loop, cu])
    assert __calculate_nesting_level(pet, _loop(loop), cu.id) == sys.maxsize


# --- __get_parent_loops ---------------------------------------------------------


def test_get_parent_loops_returns_ancestor_loops_excluding_self(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    outer = make_node("1:1", NodeType.LOOP, name="outer", start_line=1)
    inner = make_node("1:2", NodeType.LOOP, name="inner", start_line=2)
    pet = build_pet_graph([outer, inner], [(outer.id, inner.id, EdgeType.CHILD)])
    assert __get_parent_loops(pet, _loop(inner)) == [outer.start_position()]


def test_get_parent_loops_empty_for_top_level_loop(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop")
    pet = build_pet_graph([main, loop], [(main.id, loop.id, EdgeType.CHILD)])
    assert __get_parent_loops(pet, _loop(loop)) == []


def test_get_parent_loops_follows_calls_node_edges(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    outer = make_node("1:1", NodeType.LOOP, name="outer", start_line=1)
    caller_cu = make_node("1:2", NodeType.CU, name="caller_cu")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    inner = make_node("2:2", NodeType.LOOP, name="inner", start_line=2)
    pet = build_pet_graph(
        [outer, caller_cu, helper, inner],
        [
            (outer.id, caller_cu.id, EdgeType.CHILD),
            (caller_cu.id, helper.id, EdgeType.CALLSNODE),
            (helper.id, inner.id, EdgeType.CHILD),
        ],
    )
    assert __get_parent_loops(pet, _loop(inner)) == [outer.start_position()]


# --- __get_called_functions -----------------------------------------------------


def test_get_called_functions_collects_direct_call(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    helper = make_node("2:1", NodeType.FUNC, name="helper")
    pet = build_pet_graph(
        [loop, cu, helper],
        [(loop.id, cu.id, EdgeType.CHILD), (cu.id, helper.id, EdgeType.CALLSNODE)],
    )
    assert __get_called_functions(pet, _loop(loop)) == [helper.start_position()]


def test_get_called_functions_empty_when_nothing_called(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    loop = make_node("1:1", NodeType.LOOP, name="loop")
    cu = make_node("1:2", NodeType.CU, name="cu")
    pet = build_pet_graph([loop, cu], [(loop.id, cu.id, EdgeType.CHILD)])
    assert __get_called_functions(pet, _loop(loop)) == []


# --- __check_for_problematic_function_argument_access ---------------------------


def test_problematic_function_argument_access_true_for_shared_pointer_arg(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[Variable("int*", VarName("p"), "1:1")])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "p"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is True


def test_problematic_function_argument_access_false_for_non_pointer_arg(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[Variable("int", VarName("x"), "1:1")])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "x"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is False


def test_problematic_function_argument_access_false_when_var_is_not_an_argument(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    func = make_node("1:1", NodeType.FUNC, name="f", args=[])
    cu1 = make_node("1:2", NodeType.CU, name="cu1")
    cu2 = make_node("1:3", NodeType.CU, name="cu2")
    pet = build_pet_graph([func, cu1, cu2], [(func.id, cu1.id, EdgeType.CHILD), (func.id, cu2.id, EdgeType.CHILD)])
    dep = Dependency(EdgeType.DATA)
    dep.var_name = "not_an_arg"
    assert __check_for_problematic_function_argument_access(pet, cu1.id, cu2.id, dep) is False


# --- __detect_do_all / __check_loop_dependencies ---------------------------------
#
# NOTE on is_readonly_inside_loop_body/is_loop_index inputs: subtree_of_type(pet, root_loop, ...)
# includes root_loop itself (per its own docstring: "including root"), so `loop_start_lines`
# always contains the outer loop's own start position -- a dependency whose source_line matches
# it is treated the same as a genuine loop-header access.


def test_detect_do_all_true_for_independent_loop_body(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node("1:3", NodeType.CU, name="cu1", start_line=6, end_line=6)
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, cu1.id, EdgeType.CHILD), (loop.id, cu2.id, EdgeType.CHILD)],
    )
    assert __detect_do_all(pet, _loop(loop)) is True


def test_detect_do_all_false_for_cross_cu_raw_with_matching_war(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node("1:3", NodeType.CU, name="cu1", start_line=6, end_line=6)
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    raw = Dependency(EdgeType.DATA)
    raw.dtype = DepType.RAW
    raw.var_name = "x"
    raw.memory_region = "M1"  # type: ignore[assignment]
    war = Dependency(EdgeType.DATA)
    war.dtype = DepType.WAR
    war.var_name = "x"
    war.memory_region = "M1"  # type: ignore[assignment]
    war.sink_line = LineID("1:7")
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, raw),
            (cu2.id, cu1.id, war),
        ],
    )
    # the WAR edge proves "x" is written inside the loop body (not just at the loop header),
    # which makes the RAW dependency non-readonly; with no metadata, that blocks the do-all.
    assert __detect_do_all(pet, _loop(loop)) is False


def test_detect_do_all_true_for_loop_index_self_dependency(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
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
    assert __detect_do_all(pet, _loop(loop)) is True


def test_detect_do_all_true_for_raw_read_at_loop_header_line(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node("1:3", NodeType.CU, name="cu1", start_line=6, end_line=6)
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    raw = Dependency(EdgeType.DATA)
    raw.dtype = DepType.RAW
    raw.var_name = "x"
    raw.memory_region = "M1"  # type: ignore[assignment]
    raw.source_line = LineID("1:5")  # matches the loop's own start line
    raw.sink_line = LineID("1:7")
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, raw),
        ],
    )
    # no WAR/WAW anywhere flags "x" as written inside the body itself, so it counts as
    # read-only inside the loop body and is skipped entirely.
    assert __detect_do_all(pet, _loop(loop)) is True


def test_detect_do_all_false_for_raw_with_inter_iteration_metadata_dependency(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node("1:3", NodeType.CU, name="cu1", start_line=6, end_line=6)
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    raw = Dependency(EdgeType.DATA)
    raw.dtype = DepType.RAW
    raw.var_name = "x"
    raw.memory_region = "M1"  # type: ignore[assignment]
    # fully populated metadata (all non-None, non-empty ancestors) routes the RAW check
    # into the "metadata exists" branch of __check_loop_dependencies instead of the
    # "no metadata created" branch.
    raw.metadata_source_ancestors = [loop.start_position()]
    raw.metadata_sink_ancestors = [loop.start_position()]
    raw.metadata_intra_iteration_dep = []
    raw.metadata_inter_iteration_dep = [loop.start_position()]
    raw.metadata_intra_call_dep = []
    raw.metadata_inter_call_dep = []
    war = Dependency(EdgeType.DATA)
    war.dtype = DepType.WAR
    war.var_name = "x"
    war.memory_region = "M1"  # type: ignore[assignment]
    war.sink_line = LineID("1:7")
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, raw),
            (cu2.id, cu1.id, war),
        ],
    )
    # cond_4 (root_loop.start_position() in dep.metadata_inter_iteration_dep) is satisfied,
    # which must block the do-all suggestion even though full dependency metadata exists.
    assert __detect_do_all(pet, _loop(loop)) is False


def test_detect_do_all_false_for_war_with_explicit_missing_metadata(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    cu1 = make_node("1:3", NodeType.CU, name="cu1", start_line=6, end_line=6)
    cu2 = make_node("1:4", NodeType.CU, name="cu2", start_line=7, end_line=7)
    war = Dependency(EdgeType.DATA)
    war.dtype = DepType.WAR
    war.var_name = "y"
    war.memory_region = "M2"  # type: ignore[assignment]
    war.source_line = LineID("1:6")
    war.sink_line = LineID("1:7")
    # Dependency defaults metadata_intra_iteration_dep to [], not None; the WAR branch of
    # __check_loop_dependencies only takes its "no metadata" path when it is explicitly None.
    war.metadata_intra_iteration_dep = None
    pet = build_pet_graph(
        [main, loop, cu1, cu2],
        [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
            (cu1.id, cu2.id, war),
        ],
    )
    assert __detect_do_all(pet, _loop(loop)) is False
