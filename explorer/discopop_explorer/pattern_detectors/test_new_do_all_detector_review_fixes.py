# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of the do-all / reduction detection for the loops it has to reject regardless of the
iteration copies of the task graph: dependencies carried by the loop whose ends lie outside of its
iteration copies, loops left early, loops with too few observed iterations - and, end to end on a
constructed TaskGraph, the records of stack variables (without callpath states)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import CARRIED_OUTSIDE, Dependency
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.test_TaskGraph_construction import LOOP, _build_program, _construct
from discopop_explorer.classes.TaskGraph.test_TaskGraph_dependencies import (
    LOOP_INSTRUCTIONS,
    _add_loop_node,
    _write_instruction_lines,
)
from discopop_explorer.classes.patterns.PatternDecisions import (
    ACCEPTED,
    CUT_EARLY_EXIT,
    CUT_EXCEPTION_HANDLER,
    LOOP_CARRIED_DEPENDENCY,
    REJECTED,
    TOO_FEW_ITERATIONS,
    PatternDecisionLog,
)
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.pattern_detectors.new_do_all_detector import (
    DECISION_DETECTOR,
    identify_simple_doall_and_reduction,
)
from discopop_explorer.pattern_detectors.test_new_do_all_detector import _build_two_iteration_loop
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_explorer.utilities.PEGraphConstruction.classes.LoopData import LoopData


def _dynamic_raw(var_name: str = "x", carried_by_pet_loops: Optional[frozenset[str]] = None) -> Dependency:
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = var_name
    dep.source_line = LineID("1:7")
    dep.sink_line = LineID("1:6")
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    dep.carried_by_pet_loops = carried_by_pet_loops
    return dep


def _decision(tg: TaskGraph, node_id: str) -> Any:
    decisions = PatternDecisionLog()
    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet), decisions)
    decisions.finalize(DECISION_DETECTOR, patterns)
    decision = decisions.get(DECISION_DETECTOR, node_id)
    assert decision is not None
    return decision


def _two_iteration_loop(make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any) -> Any:
    return _build_two_iteration_loop(make_node, build_pet_graph, build_task_graph, make_tg_node)


# --- the loop carrying a dependency ---------------------------------------------------------


def test_a_dependency_carried_by_the_loop_rejects_it_wherever_its_ends_lie(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """e.g. ends in the loop header, or in the standalone copy of a function called in the loop"""
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    outside_a, outside_b = WorkContext(), WorkContext()
    outside_a.register_outgoing_dependency(outside_b, _dynamic_raw(carried_by_pet_loops=frozenset([str(loop.id)])))
    tg.contexts = [outside_a, outside_b]

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [r.kind for r in decision.reasons] == [LOOP_CARRIED_DEPENDENCY]


def test_a_dependency_carried_by_another_loop_does_not_reject_the_loop(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """two consecutive iterations of an outer loop can share an iteration copy of the inner one"""
    tg, loop, _loop_ctx, work1, work2 = _two_iteration_loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    work1.register_outgoing_dependency(work2, _dynamic_raw(carried_by_pet_loops=frozenset(["1:99"])))

    assert _decision(tg, loop.id).outcome == ACCEPTED


def test_a_dependency_carried_by_an_unknown_loop_falls_back_to_the_iteration_copies(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """CARRIED_OUTSIDE without the PET identity of the loop must not mean "crosses no loop" """
    tg, loop, _loop_ctx, work1, work2 = _two_iteration_loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    dep = _dynamic_raw()
    dep.carried_by_loop = CARRIED_OUTSIDE
    work1.register_outgoing_dependency(work2, dep)

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [r.kind for r in decision.reasons] == [LOOP_CARRIED_DEPENDENCY]


# --- loops rejected regardless of their dependencies -----------------------------------------


def test_a_loop_whose_exit_was_cut_is_rejected(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    tg.loops_with_cut_exits = {loop.id: {"1:7"}}

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [(r.kind, r.details) for r in decision.reasons] == [(CUT_EARLY_EXIT, {"exit_lines": ["1:7"]})]


def test_a_loop_with_a_cut_exception_handler_is_rejected(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    tg.loop_nodes_with_cut_exception_handlers = {loop.id}

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [r.kind for r in decision.reasons] == [CUT_EXCEPTION_HANDLER]


def test_a_loop_with_fewer_than_two_observed_iterations_per_execution_is_rejected(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """the task graph always holds two iteration copies; the loop record of the profiler tells how
    many iterations were observed (`1:452 BGN loop 0 2 0 0`: entered twice, never iterated)"""
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    loop.loop_data = LoopData("1:5", 5, 5, 1, 1)

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [(r.kind, r.details) for r in decision.reasons] == [
        (TOO_FEW_ITERATIONS, {"maximum_iteration_count": 1, "entry_count": 5})
    ]


def test_a_loop_without_a_loop_record_is_rejected_if_none_of_its_lines_was_executed(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    other = make_node(
        "1:9", NodeType.LOOP, name="other", start_line=20, end_line=22, loop_data=LoopData("1:20", 4, 1, 4, 4)
    )
    tg.pet.g.add_node(other.id, data=other)

    decision = _decision(tg, loop.id)

    assert decision.outcome == REJECTED
    assert [(r.kind, r.details) for r in decision.reasons] == [(TOO_FEW_ITERATIONS, {"maximum_iteration_count": 0})]


def test_a_loop_without_a_loop_record_but_with_executed_lines_is_not_rejected_for_it(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """an older profiler did not instrument every loop (e.g. one ending an else arm)"""
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    other = make_node(
        "1:9", NodeType.LOOP, name="other", start_line=20, end_line=22, loop_data=LoopData("1:20", 4, 1, 4, 4)
    )
    tg.pet.g.add_node(other.id, data=other)
    tg.lines_with_dynamic_records = {LineID("1:6")}

    assert _decision(tg, loop.id).outcome == ACCEPTED


def test_a_profile_without_loop_records_does_not_reject_loops_for_it(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, _loop_ctx, _work1, _work2 = _two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )

    assert _decision(tg, loop.id).outcome == ACCEPTED


# --- end to end on a constructed TaskGraph ------------------------------------------------


def test_an_accumulation_into_a_stack_variable_rejects_the_loop(
    build_pet_graph: Any, make_node: Any, tmp_path: Path, isolated_pattern_id_cwd: Any
) -> None:
    """`for (i...) s += x;` with s a stack variable, recorded without states (lulesh-init.cc:436,
    costDenominator): it was suggested as do-all with lastprivate(s)"""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _write_instruction_lines(tmp_path, LOOP_INSTRUCTIONS)
    static = "1:3 NOM RAW 1:3|s(S1)\n1:3 NOM RAW 1:1|s(S1)\n"

    tg = _construct(tmp_path, pet, "20 NOM RAW 21|s(S1) RAW 10|s(S1)\n", static_dependencies=static)

    decision = _decision(tg, "1:2")
    assert decision.outcome == REJECTED
    assert [(r.kind, r.dependency.variable, r.dependency.origin) for r in decision.reasons] == [
        (LOOP_CARRIED_DEPENDENCY, "s", "dynamic")
    ]


def test_a_temporary_of_the_iteration_in_a_stack_variable_does_not_reject_the_loop(
    build_pet_graph: Any, make_node: Any, tmp_path: Path, isolated_pattern_id_cwd: Any
) -> None:
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _write_instruction_lines(tmp_path, LOOP_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "23 NOM RAW 22|t(S2)\n")

    assert _decision(tg, "1:2").outcome == ACCEPTED


def test_a_while_condition_reading_a_variable_advanced_in_the_body_rejects_the_loop(
    build_pet_graph: Any, make_node: Any, tmp_path: Path, isolated_pattern_id_cwd: Any
) -> None:
    """`while (v >= end[i]) i++;` (lulesh-init.cc:446): the condition (1:2, load 15) reads the i
    written by the body (1:3, store 21). i is no induction variable of the loop."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _add_loop_node(pet, make_node, "1:20", "1:2", 2, 3, indices=[])
    _write_instruction_lines(tmp_path, {**LOOP_INSTRUCTIONS, 15: "1:2"})

    tg = _construct(tmp_path, pet, "15 NOM RAW 21|i(S3)\n20 NOM RAW 21|i(S3)\n")

    decision = _decision(tg, "1:2")
    assert decision.outcome == REJECTED
    assert [(r.kind, r.dependency.variable) for r in decision.reasons] == [(LOOP_CARRIED_DEPENDENCY, "i")]
