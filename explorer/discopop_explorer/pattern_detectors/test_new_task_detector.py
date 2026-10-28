# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of the task detection against the hand-written OpenMP task versions of BOTS (bots/omp-tasks).

The detector reads the code scopes of the parent context of a group of tasks and of each task. The scopes
used here are the ones the detector received in a run on the serial BOTS applications; the expectations come
from omp-tasks, which parallelized the same code by hand. A test marked xfail documents a known deviation
of the explorer from it (see design/task_suggestions.md).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Set, Tuple

import pytest

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.new_task_detector import identify_loop_tasking, identify_simple_tasking
from discopop_explorer.pattern_detectors import new_task_detector
from discopop_explorer.pattern_detectors.task_dataflow import AfterDependence, after_dependences_of_instructions
from discopop_explorer.utilities.PEGraphConstruction.parser import instructionToCUIdMap
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., Any]


def _lines(file_id: int, first: int, last: int) -> List[str]:
    return [f"{file_id}:{n}" for n in range(first, last + 1)]


class _StubContext:
    """The parts of a Context the detector reads. Hashable like the real one."""

    def __init__(
        self, scope: List[str], node: Node | None, instructions: List[int] | None, cus: List[Node] | None
    ) -> None:
        self.scope, self.node, self.instructions, self.cus = scope, node, instructions or [], cus or []
        self.outgoing_dependencies: Set[Any] = set()
        self.incoming_dependencies: Set[Any] = set()

    def get_contained_nodes(self, inclusive: bool = False) -> List[Any]:
        return [SimpleNamespace(get_pet_node=lambda pet, cu=cu: cu) for cu in self.cus]

    def get_contained_contexts(self, inclusive: bool = False) -> Set[Any]:
        return set()

    def get_successive_contexts(self) -> Set[Any]:
        return set()

    def get_code_scope(self, pet: Any, inclusive: bool = False) -> List[str]:
        return list(self.scope)

    def get_instruction_scope(self, pet: Any, inclusive: bool = False) -> List[int]:
        return list(self.instructions)

    def get_first_pet_node(self, pet: Any) -> Node | None:
        return self.node


def _context(
    scope: List[str], node: Node | None = None, instructions: List[int] | None = None, cus: List[Node] | None = None
) -> Any:
    return _StubContext(scope, node, instructions, cus)


def _detect(
    parent_node: Node,
    parent_scope: List[str],
    task_scopes: List[List[str]],
    task_instructions: List[List[int]] | None = None,
    instruction_lines: Dict[int, str] | None = None,
    task_cus: List[List[Node]] | None = None,
    pet: Any = None,
    observed: Set[Tuple[int, int]] | None = None,
) -> Tuple[Any, Any]:
    """The tasks and the parallel region the detector reports for one group of tasks."""
    instructions = task_instructions or [[] for _ in task_scopes]
    tpc = SimpleNamespace(
        parent_context=_context(parent_scope, parent_node),
        registered_tasks=[
            _context(scope, None, ids, cus)
            for scope, ids, cus in zip(task_scopes, instructions, task_cus or [[] for _ in task_scopes])
        ],
    )
    lines = instruction_lines or {}
    lines_of = lambda ids: [lines[i] for i in ids if i in lines]  # noqa: E731
    # g: the stub has no node, so instruction ids that another test left in the global instructionToCUIdMap lead
    # nowhere
    pet = pet or SimpleNamespace(
        get_line_ids_of_instructions=lines_of, get_statement_line_ids_of_instructions=lines_of, g=set()
    )
    patterns = identify_simple_tasking(SimpleNamespace(pet=pet), [tpc], observed)  # type: ignore[arg-type, list-item]
    tasks = [p for p in patterns if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)]
    regions = [p for p in patterns if isinstance(p, ParallelRegionInfo)]
    return tasks, regions


def _detect_groups(pet: Any, groups: List[Tuple[Node, List[List[str]], List[List[int]]]]) -> Tuple[Any, Any]:
    """The tasks and parallel regions reported for several groups at once (one simplification result each)."""
    tpcs = [
        SimpleNamespace(
            parent_context=_context(["3:29", "3:35"], parent),
            registered_tasks=[_context(scope, None, ids) for scope, ids in zip(scopes, instructions)],
        )
        for parent, scopes, instructions in groups
    ]
    patterns = identify_simple_tasking(SimpleNamespace(pet=pet), tpcs)  # type: ignore[arg-type]
    tasks = [p for p in patterns if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)]
    return tasks, [p for p in patterns if isinstance(p, ParallelRegionInfo)]


def _span(task: TaskParallelismInfo) -> Tuple[int, int]:
    return int(str(task.region_start_line)), int(str(task.region_end_line))


@pytest.fixture  # type: ignore[misc]
def fib_group(isolated_pattern_id_cwd: Any, make_node: MakeNode) -> Tuple[Any, Any]:
    """fib.c, lines 31 and 32: x = fib(n - 1); y = fib(n - 2);  (omp-tasks/fib/fib.c: one task each).

    The scopes are those of the explorer's run: each call is in a CU of its own statement (3:288, 3:289)."""
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    return _detect(parent, ["3:29", "3:35"], [["3:31"], ["3:32"]])


def test_the_two_recursive_calls_of_fib_are_two_tasks_in_one_region(fib_group: Tuple[Any, Any]) -> None:
    tasks, regions = fib_group
    assert len(tasks) == 2
    assert len(regions) == 1
    region = regions[0]
    assert (int(region.region_start_line), int(region.region_end_line)) == (31, 32)
    assert region.contains_patterns == [t.pattern_id for t in tasks]
    assert all(t.task_group == region.task_group for t in tasks)
    assert region.pragma == ["#pragma omp parallel", "#pragma omp single"]
    assert all(t.pragma == ["#pragma omp task"] for t in tasks)


def test_the_tasks_of_fib_cover_one_statement_each(fib_group: Tuple[Any, Any]) -> None:
    tasks, _ = fib_group
    assert [_span(t) for t in tasks] == [(31, 31), (32, 32)]


def test_tasks_and_region_carry_the_instructions_of_the_tasks(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    tasks, regions = _detect(parent, ["3:29", "3:35"], [["3:31"], ["3:32"]], [[849, 850], [853, 854]])
    assert [t.instruction_ids for t in tasks] == [[849, 850], [853, 854]]
    assert regions[0].instruction_ids == [849, 850, 853, 854]


def test_the_spans_follow_the_lines_of_the_instructions_of_the_tasks(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    """The code scope is the range of the nodes: here it is wider than the statements the tasks consist of."""
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    tasks, regions = _detect(
        parent,
        ["3:29", "3:35"],
        [_lines(3, 30, 33), _lines(3, 31, 34)],
        [[849, 850], [853, 854]],
        {849: "3:31", 850: "3:31", 853: "3:32", 854: "3:32"},
    )
    assert [_span(t) for t in tasks] == [(31, 31), (32, 32)]
    assert (int(regions[0].region_start_line), int(regions[0].region_end_line)) == (31, 32)


def _group_with_dependences(
    make_node: MakeNode, observed: Set[Tuple[int, int]], ids: List[List[int]]
) -> Tuple[Any, Any]:
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    lines = {i: f"3:{30 + n}" for n, task in enumerate(ids) for i in task}
    return _detect(parent, ["3:29", "3:40"], [[f"3:{30 + n}"] for n in range(len(ids))], ids, lines, observed=observed)


def test_a_group_whose_neighbouring_tasks_depend_on_each_other_is_dropped(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    """health: check_patients_inside writes what check_patients_assess reads. The simplification found the pair in a
    copy of the code the profile's dependences did not reach; the dependence of another copy is the same instructions.
    """
    tasks, regions = _group_with_dependences(make_node, {(849, 853)}, [[849, 850], [853, 854]])
    assert tasks == [] and regions == []


def test_a_dependence_of_an_earlier_task_on_a_later_one_does_not_count(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    tasks, regions = _group_with_dependences(make_node, {(853, 849)}, [[849, 850], [853, 854]])
    assert len(tasks) == 2 and len(regions) == 1


def test_tasks_that_depend_on_a_non_neighbour_only_stay_a_group(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    """The dependence is a depend clause (task_dependences), no reason to drop the group."""
    tasks, _ = _group_with_dependences(make_node, {(1, 5)}, [[1, 2], [3, 4], [5, 6]])
    assert len(tasks) == 3


def test_instructions_both_tasks_reach_do_not_make_them_dependent(
    isolated_pattern_id_cwd: Any, make_node: MakeNode
) -> None:
    """fib: both calls reach the whole function (the recursion), which depends on itself."""
    tasks, _ = _group_with_dependences(make_node, {(1, 3), (1, 2), (3, 1)}, [[1, 2], [1, 3]])
    assert len(tasks) == 2


def test_a_group_without_scope_inside_its_parent_is_skipped(isolated_pattern_id_cwd: Any, make_node: MakeNode) -> None:
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    with pytest.warns(UserWarning, match="Empty task scope"):
        tasks, regions = _detect(parent, ["3:29", "3:35"], [["3:31"], ["4:50"]])
    assert tasks == []
    assert regions == []


def _cu(make_node: MakeNode, node_id: str, work: bool = True) -> Node:
    """A CU that reads a variable and makes a call, or one that does nothing (a ``return``, a jump)."""
    if not work:
        return make_node(node_id, NodeType.CU)
    return make_node(node_id, NodeType.CU, node_calls=[{"cuid": "9:9", "atLine": "3:1", "callInstId": "1"}])


def test_a_closing_brace_is_no_task(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """bots_get_params: a call and the closing brace of the function. omp-tasks has no tasks here."""
    call, brace = _cu(make_node, "1:83"), _cu(make_node, "1:84", work=False)
    pet = build_pet_graph([call, brace], [("1:83", "1:84", EdgeType.SUCCESSOR)])
    parent = make_node("1:76", NodeType.CU, start_line=436, end_line=440)
    tasks, regions = _detect(parent, _lines(1, 436, 440), [["1:438"], ["1:440"]], task_cus=[[call], [brace]], pet=pet)
    assert tasks == []
    assert regions == []


def test_a_task_that_ends_in_a_conditional_branch_is_no_task(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """``bots_message(...)`` is ``if (verbose) fprintf(...)``: its CU is only the condition, the call lies in the
    branch. omp-tasks has no tasks in the shared BOTS sources."""
    call, condition = _cu(make_node, "2:181"), _cu(make_node, "2:182")
    then, after = make_node("2:183", NodeType.CU), make_node("2:184", NodeType.CU)
    pet = build_pet_graph(
        [call, condition, then, after],
        [
            ("2:181", "2:182", EdgeType.SUCCESSOR),
            ("2:182", "2:183", EdgeType.SUCCESSOR),
            ("2:182", "2:184", EdgeType.SUCCESSOR),
        ],
    )
    parent = make_node("2:136", NodeType.CU, start_line=115, end_line=336)
    tasks, regions = _detect(
        parent, _lines(2, 115, 336), [["2:170"], ["2:173"]], task_cus=[[call], [condition]], pet=pet
    )
    assert tasks == []
    assert regions == []


def test_a_task_with_a_branch_inside_is_a_task(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """Both targets of the branch belong to the task: it has a single exit."""
    first, condition = _cu(make_node, "3:1"), _cu(make_node, "3:2")
    then, otherwise, after = _cu(make_node, "3:3"), _cu(make_node, "3:4"), make_node("3:5", NodeType.CU)
    pet = build_pet_graph(
        [first, condition, then, otherwise, after],
        [
            ("3:1", "3:2", EdgeType.SUCCESSOR),
            ("3:2", "3:3", EdgeType.SUCCESSOR),
            ("3:2", "3:4", EdgeType.SUCCESSOR),
            ("3:3", "3:5", EdgeType.SUCCESSOR),
            ("3:4", "3:5", EdgeType.SUCCESSOR),
        ],
    )
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    tasks, _ = _detect(
        parent, ["3:29", "3:35"], [["3:31"], ["3:32"]], task_cus=[[first], [condition, then, otherwise]], pet=pet
    )
    assert len(tasks) == 2


def test_the_invalid_task_of_a_group_of_three_is_dropped(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    one, two, empty = _cu(make_node, "3:1"), _cu(make_node, "3:2"), _cu(make_node, "3:3", work=False)
    pet = build_pet_graph([one, two, empty])
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    tasks, regions = _detect(
        parent, ["3:29", "3:35"], [["3:31"], ["3:32"], ["3:33"]], task_cus=[[one], [two], [empty]], pet=pet
    )
    assert [_span(t) for t in tasks] == [(31, 31), (32, 32)]
    assert len(regions) == 1


# --- one task per iteration of a do-all loop ---------------------------------


def _loop_with_call(make_node: MakeNode, build_pet_graph: BuildPetGraph, calls: bool = True) -> Tuple[Any, Any]:
    """fft_aux: ``for (k = 0; k < n; k += m) { fft_aux(...); }`` on lines 2951-2953 (the call on 2952)."""
    header = make_node(
        "3:10",
        NodeType.CU,
        start_line=2951,
        end_line=2951,
        node_calls=[{"cuid": "3:99", "atLine": "3:2952", "callInstId": "7"}] if calls else [],
    )
    function = make_node("3:99", NodeType.FUNC, name="fft_aux", end_line=2960)
    header.parent_function_id = function.id
    pet = build_pet_graph([header, function])
    pet.instruction_lines = {"5": "3:2951", "6": "3:2952", "7": "3:2952", "8": "3:2953"}
    pet.jump_only_lines = {"3:2953"}  # the jump back at the closing brace (8)
    do_all = SimpleNamespace(
        node_id="3:10",
        instruction_ids=[5, 6, 7, 8],
        affected_cu_ids=["3:10"],
        shared=[SimpleNamespace(name="data")],
        private=[SimpleNamespace(name="k")],
        first_private=[SimpleNamespace(name="n"), SimpleNamespace(name="n")],
        last_private=[],
        reduction=[],
    )
    return pet, do_all


def _hotspots(*names: str) -> Any:
    return {HotspotType.YES: [(3, 2907, HotspotNodeType.FUNCTION, name, 1.0) for name in names]}


def test_a_call_to_a_hotspot_function_in_a_do_all_loop_is_a_task_per_iteration(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    patterns = identify_loop_tasking(pet, [do_all], _hotspots("fft_aux"), first_task_group=4)
    tasks = [p for p in patterns if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)]
    regions = [p for p in patterns if isinstance(p, ParallelRegionInfo)]
    assert len(tasks) == 1 and len(regions) == 1
    assert _span(tasks[0]) == (2952, 2952)  # the body, without the line of the loop header and the closing brace
    assert (regions[0].region_start_line, regions[0].region_end_line) == ("2952", "2952")  # the statement
    assert tasks[0].loop_start_line == regions[0].loop_start_line == "3:2951"
    assert tasks[0].task_group == regions[0].task_group == [4]
    assert tasks[0].instruction_ids == [5, 6, 7, 8]
    assert regions[0].contains_patterns == [tasks[0].pattern_id]


def test_a_call_to_a_function_that_is_no_hotspot_is_no_task(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    assert identify_loop_tasking(pet, [do_all], _hotspots("compute_w_coefficients"), first_task_group=0) == []


def test_without_hotspot_information_every_call_qualifies(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    assert len(identify_loop_tasking(pet, [do_all], {}, first_task_group=0)) == 2
    assert len(identify_loop_tasking(pet, [do_all], None, first_task_group=0)) == 2


def test_a_do_all_loop_without_a_call_is_no_task_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph, calls=False)
    assert identify_loop_tasking(pet, [do_all], None, first_task_group=0) == []


def test_a_loop_task_takes_the_data_sharing_of_the_do_all_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    task: Any = identify_loop_tasking(pet, [do_all], None, first_task_group=0)[0]
    assert (task.shared, task.private, task.first_private) == (["data"], ["k"], ["n"])


def test_a_reduced_variable_of_a_loop_task_is_a_reduction_and_not_shared(
    monkeypatch: pytest.MonkeyPatch, isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    do_all.shared = [SimpleNamespace(name="data"), SimpleNamespace(name="sum")]
    do_all.reduction = [SimpleNamespace(name="sum", operation="+")]
    # the code after the loop reads the sum: it stays a reduction instead of becoming shared
    after = [AfterDependence(0, "sum", "RAW", "3:2960")]
    monkeypatch.setattr(
        "discopop_explorer.pattern_detectors.new_task_detector.after_dependences_of_instructions",
        lambda *a, **kw: after,
    )
    task: Any = identify_loop_tasking(pet, [do_all], None, first_task_group=0)[0]
    assert task.reduction == ["+:sum"]
    assert task.shared == ["data"]


def test_the_last_private_variables_of_a_do_all_loop_are_kept_next_to_shared(
    monkeypatch: pytest.MonkeyPatch, isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _loop_with_call(make_node, build_pet_graph)
    do_all.last_private = [SimpleNamespace(name="last")]
    after = [AfterDependence(0, "last", "RAW", "3:2960")]
    monkeypatch.setattr(
        "discopop_explorer.pattern_detectors.new_task_detector.after_dependences_of_instructions",
        lambda *a, **kw: after,
    )
    task: Any = identify_loop_tasking(pet, [do_all], None, first_task_group=0)[0]
    assert task.last_private == ["last"]
    assert task.shared == ["data", "last"]


def test_the_join_of_a_loop_task_is_the_first_line_after_the_loop_that_reads_what_it_wrote(
    monkeypatch: pytest.MonkeyPatch, isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    header = make_node("3:10", NodeType.CU, start_line=2951, end_line=2951, instruction_ids=[5, 6, 7])
    after = make_node("3:11", NodeType.CU, start_line=2960, end_line=2960, instruction_ids=[9, 10])
    function = make_node("3:99", NodeType.FUNC, name="fft_aux", end_line=3000)
    deps = []
    for sink in (9, 10):  # reads on the lines 2960 and 2958: the earlier one is the join
        dep = Dependency(EdgeType.DATA)
        dep.dtype, dep.var_name, dep.source_instruction_id, dep.sink_instruction_id = DepType.RAW, "sum", 6, sink
        deps.append((after.id, header.id, dep))
    inside = Dependency(EdgeType.DATA)  # both ends in the loop: not a join
    inside.dtype, inside.var_name, inside.source_instruction_id, inside.sink_instruction_id = DepType.RAW, "k", 5, 7
    pet = build_pet_graph(
        [header, after, function],
        deps
        + [
            (header.id, header.id, inside),
            (function.id, header.id, EdgeType.CHILD),
            (function.id, after.id, EdgeType.CHILD),
        ],
    )
    pet.instruction_lines = {"5": "3:2951", "6": "3:2952", "7": "3:2952", "9": "3:2960", "10": "3:2958"}
    for instruction in (5, 6, 7):
        monkeypatch.setitem(instructionToCUIdMap, instruction, header.id)
    found = after_dependences_of_instructions(pet, [5, 6, 7], 3, 2952, function)  # type: ignore[arg-type]
    assert [(a.variable, a.kind, a.line) for a in found] == [("sum", "RAW", "3:2958")]


@pytest.fixture  # type: ignore[misc]
def lines_pet() -> Any:
    lines = {1: "3:31", 2: "3:32", 3: "3:33"}
    lines_of = lambda ids: [lines[i] for i in ids if i in lines]  # noqa: E731
    # g: no node, so instruction ids that other tests left in the global instructionToCUIdMap lead nowhere
    return SimpleNamespace(
        get_line_ids_of_instructions=lines_of, get_statement_line_ids_of_instructions=lines_of, g=set()
    )


def test_copies_of_a_group_from_the_levels_of_a_recursion_are_reported_once(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, lines_pet: Any
) -> None:
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    group = (parent, [["3:31"], ["3:32"]], [[1], [2]])
    tasks, regions = _detect_groups(lines_pet, [group, group, group])
    assert len(tasks) == 2
    assert len(regions) == 1
    assert [_span(t) for t in tasks] == [(31, 31), (32, 32)]


def test_groups_that_differ_in_parent_lines_or_instructions_are_kept(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, lines_pet: Any
) -> None:
    parent = make_node("3:233", NodeType.CU, start_line=29, end_line=29)
    other_parent = make_node("3:234", NodeType.CU, start_line=29, end_line=29)
    groups = [
        (parent, [["3:31"], ["3:32"]], [[1], [2]]),
        (other_parent, [["3:31"], ["3:32"]], [[1], [2]]),
        (parent, [["3:31"], ["3:33"]], [[1], [3]]),
        (parent, [["3:31"], ["3:32"]], [[1], [2, 3]]),
    ]
    tasks, regions = _detect_groups(lines_pet, groups)
    assert len(regions) == 4
    assert len(tasks) == 8
    assert sorted(g for r in regions for g in r.task_group) == [0, 1, 2, 3]


# --- the statement of a loop task: no loop headers, no guards, one suggestion per nest ----------------------------


def _guarded_call_loop(
    make_node: MakeNode, build_pet_graph: BuildPetGraph, guard_calls: bool = False
) -> Tuple[Any, Any]:
    """sparselu: ``for (jj ...)`` (line 50), ``if (BENCH[jj] != NULL)`` (51), ``fwd(...)`` (53), the jump of ``if.end``
    on line 51. The guard CU has two successors."""
    calls = [{"cuid": "3:99", "atLine": "3:53", "callInstId": "5"}]
    guard_call = [{"cuid": "3:99", "atLine": "3:51", "callInstId": "3"}] if guard_calls else []
    header = make_node("3:10", NodeType.CU, start_line=50, instruction_ids=[1])
    guard = make_node("3:11", NodeType.CU, start_line=51, instruction_ids=[2, 3], node_calls=guard_call)
    call = make_node("3:12", NodeType.CU, start_line=53, instruction_ids=[4, 5], node_calls=calls)
    end = make_node("3:13", NodeType.CU, start_line=51, instruction_ids=[6])  # if.end: only the jump, no variable
    function = make_node("3:99", NodeType.FUNC, name="fwd", end_line=70)
    for cu in (header, guard, call, end):
        cu.parent_function_id = function.id
    pet = build_pet_graph(
        [header, guard, call, end, function],
        [
            ("3:11", "3:12", EdgeType.SUCCESSOR),
            ("3:11", "3:13", EdgeType.SUCCESSOR),
            ("3:12", "3:13", EdgeType.SUCCESSOR),
        ],
    )
    pet.instruction_lines = {"1": "3:50", "2": "3:51", "3": "3:51", "4": "3:53", "5": "3:53", "6": "3:51"}
    do_all = SimpleNamespace(
        node_id="3:10",
        instruction_ids=[1, 2, 3, 4, 5, 6],
        affected_cu_ids=["3:10"],
        shared=[],
        private=[],
        first_private=[],
        reduction=[],
        last_private=[],
    )
    return pet, do_all


def _tasks_and_regions(patterns: List[Any]) -> Tuple[List[Any], List[Any]]:
    return (
        [p for p in patterns if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)],
        [p for p in patterns if isinstance(p, ParallelRegionInfo)],
    )


def test_the_condition_that_only_guards_a_loop_task_is_not_part_of_it(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _guarded_call_loop(make_node, build_pet_graph)
    tasks, regions = _tasks_and_regions(identify_loop_tasking(pet, [do_all], None, first_task_group=0))
    assert _span(tasks[0]) == (53, 53)
    assert (regions[0].region_start_line, regions[0].region_end_line) == ("53", "53")
    assert tasks[0].loop_start_line == regions[0].loop_start_line == "3:50"  # the loop is still known


def test_a_condition_that_calls_something_is_part_of_the_loop_task(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, do_all = _guarded_call_loop(make_node, build_pet_graph, guard_calls=True)  # if (ok(b)) f(b);
    tasks, regions = _tasks_and_regions(identify_loop_tasking(pet, [do_all], None, first_task_group=0))
    assert _span(tasks[0]) == (51, 53)
    assert (regions[0].region_start_line, regions[0].region_end_line) == ("51", "53")


def test_the_loops_of_a_nest_with_the_same_statement_are_one_suggestion_for_the_innermost(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """``for (ii) for (jj) bmod(...)``: both loops are do-all; the task is per iteration of the inner loop."""
    outer = make_node("3:10", NodeType.CU, start_line=50, instruction_ids=[1])
    inner = make_node("3:11", NodeType.CU, start_line=51, instruction_ids=[2])
    call = make_node(
        "3:12",
        NodeType.CU,
        start_line=52,
        instruction_ids=[3, 4],
        node_calls=[{"cuid": "3:99", "atLine": "3:52", "callInstId": "4"}],
    )
    inner_loop = make_node("3:20", NodeType.LOOP, start_line=51, end_line=52)
    function = make_node("3:99", NodeType.FUNC, name="bmod", end_line=70)
    pet = build_pet_graph([outer, inner, call, inner_loop, function])
    pet.instruction_lines = {"1": "3:50", "2": "3:51", "3": "3:52", "4": "3:52"}
    outer_do_all = SimpleNamespace(
        node_id="3:10",
        instruction_ids=[1, 2, 3, 4],
        affected_cu_ids=[],
        shared=[],
        private=[],
        first_private=[],
        reduction=[],
        last_private=[],
    )
    inner_do_all = SimpleNamespace(
        node_id="3:11",
        instruction_ids=[2, 3, 4],
        affected_cu_ids=[],
        shared=[],
        private=[],
        first_private=[],
        reduction=[],
        last_private=[],
    )
    for order in ([outer_do_all, inner_do_all], [inner_do_all, outer_do_all]):
        found = identify_loop_tasking(pet, order, None, first_task_group=0)  # type: ignore[arg-type]
        tasks, regions = _tasks_and_regions(found)
        assert len(tasks) == len(regions) == 1
        assert _span(tasks[0]) == (52, 52)
        assert tasks[0].loop_start_line == "3:51"  # the inner loop
        assert tasks[0].instruction_ids == [2, 3, 4]


def test_a_later_write_of_what_the_task_gets_by_value_is_no_after_dependence(
    monkeypatch: pytest.MonkeyPatch, isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """The next loop of the function starts with ``jj = kk + 1``: a WAR on the index of the loop (and on a
    firstprivate variable) does not make the code after the loop wait for the task; a WAR on another variable does."""
    pet, do_all = _guarded_call_loop(make_node, build_pet_graph)
    do_all.first_private = [SimpleNamespace(name="kk")]
    index_dependence = Dependency(EdgeType.DATA)  # jj++ in the header depends on the jj of the iteration before
    index_dependence.dtype, index_dependence.var_name = DepType.RAW, "jj"
    index_dependence.sink_line = index_dependence.source_line = LineID("3:50")
    pet.g.add_edge("3:10", "3:10", data=index_dependence)
    after = [
        AfterDependence(0, "col", "RAW", "3:66"),
        AfterDependence(0, "jj", "WAR", "3:62"),
        AfterDependence(0, "kk", "WAR", "3:62"),
        AfterDependence(0, "other", "WAR", "3:62"),
    ]
    monkeypatch.setattr(new_task_detector, "after_dependences_of_instructions", lambda *args, **kwargs: after)
    _, regions = _tasks_and_regions(identify_loop_tasking(pet, [do_all], None, first_task_group=0))
    assert [(a["variable"], a["kind"]) for a in regions[0].after_dependences] == [("col", "RAW"), ("other", "WAR")]
