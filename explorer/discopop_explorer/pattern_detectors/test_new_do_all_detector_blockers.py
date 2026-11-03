# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Every dependency which prevents a doall loop is recorded, not only the first one found, and
across every task-graph copy of the loop. See design/doall_commutative_updates.md, phase 1."""

from __future__ import annotations

from typing import Any, List, Tuple

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.PatternDecisions import (
    ACCEPTED,
    LOOP_CARRIED_DEPENDENCY,
    REJECTED,
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
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

# the two iterations of one copy of the loop
Copy = Tuple[WorkContext, WorkContext]


def _loop_with_copies(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, copies: int
) -> Tuple[TaskGraph, Node, List[Copy]]:
    """main -> loop -> body_cu, with `copies` task-graph copies of the loop, each holding two
    iterations of body_cu - as the task graph holds one copy of a loop per calling context"""
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    body_cu = make_node("1:3", NodeType.CU, name="body", start_line=6, end_line=8)
    pet = build_pet_graph(
        [main, loop, body_cu],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, body_cu.id, EdgeType.CHILD)],
    )
    tg_loops = []
    works: List[Copy] = []
    for index in range(copies):
        loop_ctx = LoopParentContext(parent_loop=loop.id)
        iterations = []
        for iteration in range(2):
            ic = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[iteration])
            loop_ctx.add_contained_context(ic)
            ic.register_parent_context(loop_ctx)
            work = WorkContext()
            work.add_node(make_tg_node(body_cu.id, level=1, position=2 * index + iteration))
            ic.add_contained_context(work)
            work.register_parent_context(ic)
            iterations.append(work)
        works.append((iterations[0], iterations[1]))
        tg_loop = make_tg_node(loop.id, level=0, position=index)
        tg_loop.register_created_context(loop_ctx)
        tg_loops.append(tg_loop)
    return build_task_graph(pet, tg_loops), loop, works


def _carried(copy: Copy, var: str, source: str, sink: str, dtype: DepType = DepType.RAW) -> None:
    """registers a dynamic dependency from the first iteration of the copy to the second"""
    dep = Dependency(EdgeType.DATA)
    dep.dtype = dtype
    dep.var_name = var
    dep.source_line = LineID(source)
    dep.sink_line = LineID(sink)
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    copy[0].register_outgoing_dependency(copy[1], dep)


def _detect(tg: TaskGraph, loop: Node) -> Tuple[List[Any], Any]:
    decisions = PatternDecisionLog()
    patterns = identify_simple_doall_and_reduction(tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet), decisions)
    decisions.finalize(DECISION_DETECTOR, patterns)
    decision = decisions.get(DECISION_DETECTOR, loop.id)
    assert decision is not None
    return patterns, decision


def _blockers(decision: Any) -> List[Tuple[str, str, str, str]]:
    assert all(r.kind == LOOP_CARRIED_DEPENDENCY for r in decision.reasons)
    return sorted(
        (r.dependency.type, r.dependency.variable, r.dependency.source_line, r.dependency.sink_line)
        for r in decision.reasons
    )


def test_every_blocking_dependency_of_a_loop_is_recorded(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,) = _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, 1)
    _carried(copy, "x", "1:7", "1:6")
    _carried(copy, "y", "1:8", "1:8")
    _carried(copy, "y", "1:8", "1:8", DepType.WAW)

    patterns, decision = _detect(tg, loop)

    assert patterns == []
    assert decision.outcome == REJECTED
    assert _blockers(decision) == [
        ("RAW", "x", "1:7", "1:6"),
        ("RAW", "y", "1:8", "1:8"),
        ("WAW", "y", "1:8", "1:8"),
    ]


def test_a_dependency_found_more_than_once_is_recorded_once(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """the copies of a loop hold separate Dependency objects for the same dependency"""
    tg, loop, copies = _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, 2)
    for copy in copies:
        _carried(copy, "x", "1:7", "1:6")

    _patterns, decision = _detect(tg, loop)

    assert _blockers(decision) == [("RAW", "x", "1:7", "1:6")]


def test_the_blocking_dependencies_of_every_copy_of_a_loop_are_recorded(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    """the copy found first rejects the loop; a later copy carrying another blocker is still scanned"""
    tg, loop, copies = _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, 3)
    _carried(copies[0], "x", "1:7", "1:6")
    _carried(copies[2], "y", "1:8", "1:8")

    patterns, decision = _detect(tg, loop)

    assert patterns == []
    assert decision.outcome == REJECTED
    assert _blockers(decision) == [("RAW", "x", "1:7", "1:6"), ("RAW", "y", "1:8", "1:8")]


def test_a_blocker_in_a_later_copy_still_rejects_a_loop_registered_by_an_earlier_one(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, copies = _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, 2)
    _carried(copies[1], "y", "1:8", "1:8")

    patterns, decision = _detect(tg, loop)

    assert patterns == []
    assert decision.outcome == REJECTED
    assert _blockers(decision) == [("RAW", "y", "1:8", "1:8")]


def test_a_loop_without_blocking_dependencies_in_any_copy_is_accepted(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, copies = _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, 2)
    _carried(copies[0], "x", "1:7", "1:6", DepType.WAR)

    patterns, decision = _detect(tg, loop)

    assert len(patterns) == 1
    assert decision.outcome == ACCEPTED
