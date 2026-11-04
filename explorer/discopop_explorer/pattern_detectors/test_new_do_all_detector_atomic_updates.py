# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Loops whose only blockers are commutative updates are accepted with atomic updates when asked to
(atomic_updates=True). See design/doall_commutative_updates.md."""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple


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
from discopop_explorer.json_serializer import PatternBaseSerializer
from discopop_explorer.pattern_detectors import new_do_all_detector
from discopop_explorer.pattern_detectors.commutative_updates import ATOMIC_UPDATES_NOTE, DETAILS_KEY
from discopop_explorer.pattern_detectors.new_do_all_detector import (
    DECISION_DETECTOR,
    identify_simple_doall_and_reduction,
)
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_explorer.utilities.ASTUtils.UpdateSites import UpdateSite

Copy = Tuple[WorkContext, WorkContext]

SITE_LINE = 7
SITE_FIRST_COLUMN = 9
SITE_LAST_COLUMN = 11
SOURCE_INSTRUCTION = 100
SINK_INSTRUCTION = 101
OTHER_INSTRUCTION = 200


class _SitesHelper(ASTPatternDetectionHelper):
    """an AST helper with hand-made update sites; no AST graph, so the other queries answer empty"""

    def __init__(self, loaded: bool = True) -> None:
        super().__init__()
        self._loaded = loaded

    def is_ast_loaded(self) -> bool:
        return self._loaded

    def get_update_sites(self, file_id: int, line: int) -> Tuple[UpdateSite, ...]:
        if file_id != 1 or line != SITE_LINE:
            return ()
        return (
            UpdateSite(
                line=SITE_LINE,
                first_column=SITE_FIRST_COLUMN,
                last_column=SITE_LAST_COLUMN,
                operator="+=",
                operator_class="+",
                variable="s",
                begin_column=5,
                end_column=20,
            ),
        )


def _loop_with_copies(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, copies: int
) -> Tuple[TaskGraph, Node, List[Copy], Node]:
    """main -> loop -> body_cu, with `copies` task-graph copies of the loop, each holding two
    iterations of body_cu"""
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
    return build_task_graph(pet, tg_loops), loop, works, body_cu


def _blocker(
    copy: Copy,
    body_cu: Node,
    tg: TaskGraph,
    source_instruction: int = SOURCE_INSTRUCTION,
    sink_instruction: int = SINK_INSTRUCTION,
    source_column: int = 10,
    sink_column: int = 10,
    line: int = SITE_LINE,
    var: str = "s",
) -> None:
    """a RAW dependency of an update statement from the first iteration of the copy to the second, with the
    instructions, positions and the data edge the classifier reads"""

    def dependency() -> Dependency:
        dep = Dependency(EdgeType.DATA)
        dep.dtype = DepType.RAW
        dep.var_name = var
        dep.source_line = LineID("1:" + str(line))
        dep.sink_line = LineID("1:" + str(line))
        dep.origin = DepOrigin.DYNAMIC_ANALYSIS
        dep.source_instruction_id = source_instruction
        dep.sink_instruction_id = sink_instruction
        return dep

    copy[0].register_outgoing_dependency(copy[1], dependency())
    tg.pet.instruction_lines[str(source_instruction)] = "1:" + str(line)
    tg.pet.instruction_columns[str(source_instruction)] = source_column
    tg.pet.instruction_lines[str(sink_instruction)] = "1:" + str(line)
    tg.pet.instruction_columns[str(sink_instruction)] = sink_column
    # sink first
    tg.pet.g.add_edge(body_cu.id, body_cu.id, data=dependency())


def _detect(tg: TaskGraph, loop: Node, atomic_updates: bool, loaded: bool = True) -> Tuple[List[Any], Any]:
    decisions = PatternDecisionLog()
    patterns = identify_simple_doall_and_reduction(
        tg, _SitesHelper(loaded), DataEdgeIndex(tg.pet), decisions, atomic_updates=atomic_updates
    )
    decisions.finalize(DECISION_DETECTOR, patterns)
    decision = decisions.get(DECISION_DETECTOR, loop.id)
    assert decision is not None
    return patterns, decision


def _expected_atomics() -> List[Any]:
    return [{"file_id": 1, "line": SITE_LINE, "operation": "+=", "variable": "s"}]


def _setup(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, copies: int = 1
) -> Tuple[TaskGraph, Node, List[Copy], Node]:
    return _loop_with_copies(make_node, build_pet_graph, build_task_graph, make_tg_node, copies)


def test_flag_off_keeps_a_fixable_loop_rejected_with_the_classification(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)

    patterns, decision = _detect(tg, loop, atomic_updates=False)

    assert patterns == []
    assert decision.outcome == REJECTED
    assert len(decision.reasons) == 1
    reason = decision.reasons[0]
    assert reason.kind == LOOP_CARRIED_DEPENDENCY
    assert reason.details[DETAILS_KEY]["fixable"] is True


def test_flag_on_accepts_a_fixable_loop_with_atomic_updates(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)

    patterns, decision = _detect(tg, loop, atomic_updates=True)

    assert len(patterns) == 1
    assert patterns[0].atomic_updates == _expected_atomics()
    assert decision.outcome == ACCEPTED
    assert [n.kind for n in decision.notes] == [ATOMIC_UPDATES_NOTE]
    assert decision.notes[0].details == {"atomic_updates": _expected_atomics()}


def test_flag_on_rejects_a_loop_with_one_non_fixable_blocker(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)
    # an end at a column no site covers
    _blocker(copy, body, tg, 300, 301, source_column=30, sink_column=30, var="y")

    patterns, decision = _detect(tg, loop, atomic_updates=True)

    assert patterns == []
    assert decision.outcome == REJECTED
    fixable = sorted(r.details[DETAILS_KEY]["fixable"] for r in decision.reasons)
    assert fixable == [False, True]


def test_flag_on_replaces_the_pattern_an_earlier_copy_registered_without_atomics(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, copies, body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node, copies=2)
    _blocker(copies[1], body, tg)

    patterns, decision = _detect(tg, loop, atomic_updates=True)

    assert len(patterns) == 1
    assert patterns[0].atomic_updates == _expected_atomics()
    assert decision.outcome == ACCEPTED


def test_flag_on_accepts_a_blocker_found_only_in_a_third_copy(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, copies, body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node, copies=3)
    _blocker(copies[2], body, tg)

    patterns, decision = _detect(tg, loop, atomic_updates=True)

    assert len(patterns) == 1
    assert patterns[0].atomic_updates == _expected_atomics()
    assert decision.outcome == ACCEPTED


def test_flag_on_without_an_ast_stays_rejected_without_details(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)

    patterns, decision = _detect(tg, loop, atomic_updates=True, loaded=False)

    assert patterns == []
    assert decision.outcome == REJECTED
    assert len(decision.reasons) == 1
    assert not decision.reasons[0].details


def test_atomic_updates_reach_the_json_only_where_there_are_any(
    make_node: Any, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)
    with_atomics, _ = _detect(tg, loop, atomic_updates=True)

    tg2, loop2, _copies, _body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    without_atomics, _ = _detect(tg2, loop2, atomic_updates=True)

    assert len(with_atomics) == 1 and len(without_atomics) == 1
    plain = json.loads(json.dumps(without_atomics[0], cls=PatternBaseSerializer))
    atomic = json.loads(json.dumps(with_atomics[0], cls=PatternBaseSerializer))
    assert "atomic_updates" not in plain
    assert atomic["atomic_updates"] == _expected_atomics()


def test_run_detection_does_not_collapse_patterns_with_atomic_updates(
    make_node: Any,
    build_pet_graph: Any,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
    monkeypatch: Any,
) -> None:
    tg, loop, (copy,), body = _setup(make_node, build_pet_graph, build_task_graph, make_tg_node)
    _blocker(copy, body, tg)
    seen: List[Optional[List[Any]]] = []

    def record(task_graph: Any, ast_helper: Any, patterns: Any) -> List[Any]:
        seen.append(list(patterns))
        return []

    monkeypatch.setattr(new_do_all_detector, "identify_collapsible_loop_nests", record)

    result = new_do_all_detector.run_detection(tg.pet, tg, _SitesHelper(), atomic_updates=True)

    assert len(result) == 1 and result[0].atomic_updates == _expected_atomics()
    assert seen == [[]]
