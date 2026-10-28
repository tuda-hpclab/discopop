# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Loops with a cursor (omp-tasks/health: ``while (v) { f(v); v = v->next; }``) are tasks per iteration."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import pytest

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.new_task_detector import identify_loop_tasking
from discopop_explorer.pattern_detectors.task_cursor_loops import find_cursor_loops

MakeNode = Callable[..., Node]

HEADER, CALL, UPDATE = "1:5", "1:6", "1:7"


def _variable(name: str, mode: str, def_line: str) -> Variable:
    return Variable(type="int", name=name, defLine=def_line, accessMode=mode)  # type: ignore[arg-type]


def _loop(
    make_node: MakeNode,
    build_pet_graph: Callable[..., PEGraphX],
    build_task_graph: Callable[..., TaskGraph],
    make_tg_node: Callable[..., Any],
    iterations: int = 2,
) -> Tuple[TaskGraph, str, List[WorkContext], FunctionContext]:
    """``while (cursor) { f(cursor); cursor = cursor->next; }`` on lines 5-8 of a function; instruction 9 is on the
    header line, 10 and 11 on the line of the call, 12 on the line of the update."""
    function = make_node("1:1", NodeType.FUNC, name="walk", start_line=1, end_line=9)
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=8)
    body = make_node(
        "1:3",
        NodeType.CU,
        name="body",
        start_line=5,
        end_line=7,
        instruction_ids=[9, 10, 11, 12],
        node_calls=[{"cuid": "1:1", "atLine": CALL, "callInstId": "11"}],
        local_vars=[
            _variable("cursor", "RW", "1:3"),
            _variable("local", "W", CALL),
            _variable("n", "R", "1:3"),
        ],
    )
    pet = build_pet_graph(
        [function, loop, body], [(function.id, loop.id, EdgeType.CHILD), (loop.id, body.id, EdgeType.CHILD)]
    )
    pet.instruction_lines = {"9": HEADER, "10": CALL, "11": CALL, "12": UPDATE}
    function_ctx = FunctionContext(function.id)
    loop_ctx = LoopParentContext(parent_loop=loop.id)
    loop_ctx.register_parent_context(function_ctx)
    function_ctx.add_contained_context(loop_ctx)
    works: List[WorkContext] = []
    for index in range(iterations):
        iteration = IterationContext(parent_context=loop_ctx, loopstate_iteration_ids=[index])
        loop_ctx.add_contained_context(iteration)
        iteration.register_parent_context(loop_ctx)
        work = WorkContext()
        work.add_node(make_tg_node(body.id, level=1, position=index))
        iteration.add_contained_context(work)
        work.register_parent_context(iteration)
        works.append(work)
    tg_loop = make_tg_node(loop.id, level=0, position=0)
    tg_loop.register_created_context(loop_ctx)
    return build_task_graph(pet, [tg_loop]), loop.id, works, function_ctx


def _dependency(
    name: str, source_line: str, sink_line: str, dtype: DepType = DepType.RAW, loop_id: Optional[str] = "1:2"
) -> Dependency:
    dependency = Dependency(EdgeType.DATA)
    dependency.dtype = dtype
    dependency.var_name = name
    dependency.source_line = LineID(source_line)
    dependency.sink_line = LineID(sink_line)
    dependency.origin = DepOrigin.DYNAMIC_ANALYSIS
    dependency.carried_by_pet_loops = None if loop_id is None else frozenset({loop_id})
    return dependency


def test_a_loop_whose_only_carried_dependence_is_its_cursor_is_a_task_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, loop_id, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    # the update on line 7 writes the cursor, the next iteration reads it on line 6 (the call) and line 7
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, UPDATE))
    loops = find_cursor_loops(tg, set())
    assert len(loops) == 1
    loop = loops[0]
    assert loop.node_id == loop_id
    assert loop.cursors == ["cursor"]
    assert loop.update_lines == [UPDATE]
    assert loop.instruction_ids == [9, 10, 11]  # the update is no part of the task
    assert [v.name for v in loop.first_private] == ["cursor", "n"]
    assert [v.name for v in loop.private] == ["local"]
    assert loop.shared == []


def test_the_task_of_a_cursor_loop_is_the_call_without_the_header_and_the_update(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    patterns = identify_loop_tasking(tg.pet, find_cursor_loops(tg, set()), None, first_task_group=0)
    tasks = [p for p in patterns if type(p) is TaskParallelismInfo]
    regions = [p for p in patterns if isinstance(p, ParallelRegionInfo)]
    assert len(tasks) == 1 and len(regions) == 1
    assert (tasks[0].region_start_line, tasks[0].region_end_line) == ("6", "6")
    # like every loop task: the region covers the task statement, the loop header is the loop_start_line
    assert (regions[0].region_start_line, regions[0].region_end_line) == ("6", "6")
    assert tasks[0].loop_start_line == "1:5"
    assert tasks[0].first_private == ["cursor", "n"]


def test_a_dependence_without_a_known_carrying_loop_counts_as_well(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL, loop_id=None))
    assert len(find_cursor_loops(tg, set())) == 1
    works[0].register_outgoing_dependency(works[1], _dependency("total", CALL, CALL, loop_id=None))
    assert find_cursor_loops(tg, set()) == []


def test_a_loop_without_carried_dependences_is_left_to_the_do_all_detection(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, _, _, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    assert find_cursor_loops(tg, set()) == []


def test_a_loop_that_is_a_pattern_already_is_no_cursor_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, loop_id, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    assert find_cursor_loops(tg, {loop_id}) == []


def test_a_loop_with_one_iteration_is_no_evidence(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node, iterations=1)
    works[0].register_outgoing_dependency(works[0], _dependency("cursor", UPDATE, CALL))
    assert find_cursor_loops(tg, set()) == []


@pytest.mark.parametrize(  # type: ignore[misc]
    "variable,source_line,sink_line",
    [
        ("sum", CALL, CALL),  # the call writes what the next iteration's call reads: the iterations depend
        ("cursor", CALL, UPDATE),  # the update is part of a call: x = f(x)
        ("cursor", "1:3", CALL),  # written outside of the loop
        ("cursor", "2:7", CALL),  # in another file
    ],
)
def test_a_carried_dependence_that_is_no_update_of_a_cursor_rejects_the_loop(
    isolated_pattern_id_cwd: Any,
    make_node: MakeNode,
    build_pet_graph: Any,
    build_task_graph: Any,
    make_tg_node: Any,
    variable: str,
    source_line: str,
    sink_line: str,
) -> None:
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    works[0].register_outgoing_dependency(works[1], _dependency(variable, source_line, sink_line))
    assert find_cursor_loops(tg, set()) == []


def test_a_dependence_inside_a_called_function_rejects_the_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    """A recursive callee has the lines of the loop as well: the position of the update is not enough."""
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    callee = FunctionContext(NodeID("1:1"))
    callee_work = WorkContext()
    callee.add_contained_context(callee_work)
    callee_work.register_parent_context(callee)
    iteration = works[1].parent_context
    assert iteration is not None
    iteration.add_contained_context(callee)
    callee.register_parent_context(iteration)
    works[0].register_outgoing_dependency(callee_work, _dependency("cursor", UPDATE, UPDATE))
    assert find_cursor_loops(tg, set()) == []


def test_war_dependences_between_the_iterations_do_not_matter(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    tg, _, works, _ = _loop(make_node, build_pet_graph, build_task_graph, make_tg_node)
    works[0].register_outgoing_dependency(works[1], _dependency("cursor", UPDATE, CALL))
    works[0].register_outgoing_dependency(works[1], _dependency("tmp", CALL, UPDATE, DepType.WAR))
    assert len(find_cursor_loops(tg, set())) == 1
