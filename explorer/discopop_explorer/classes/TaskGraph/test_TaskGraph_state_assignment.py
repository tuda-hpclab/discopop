# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of TaskGraph.__assign_state_ids: which context a callpath state of the profiler ends up at.

The profiler records every dependency under a callpath state ("<instr>@<state>" in
dynamic_dependencies.txt). stateID_to_callpath_mapping.txt resolves a state to its callpath, a
sequence of function names, "call_<instruction id>" entries and "<function>_loopstate<digits>"
entries. The loopstate carries one digit per loop of the function (in the order of the profiler's
loop nesting forest): 0, 1 and 2 are the iteration bucket of an active loop, 3 means "not active".
A state is meant to be assigned to the context its callpath leads to, so that the dependencies
observed under it are attached to the right copy of a function, loop iteration and call.

Two kinds of tests:

- profile tests build the TaskGraph from real profiler output of small programs, checked in below
  explorer/test/state_assignment/<program>/ (code.cpp is the profiled source). They check that every
  observed state is assigned, that it is assigned to a context whose ancestor chain spells out its
  callpath (an oracle independent of the matcher), and that the start/end markers of the graph are
  balanced along every path, which context nesting relies on.
- synthetic tests build small PET graphs by hand (see test_TaskGraph_construction.py), one per
  known cause, so that each cause can be fixed and verified in isolation.

The tests marked xfail(strict=True) reproduce known bugs, see the reason of each. A strict xfail
turns into a failure once the bug is fixed, so remove the marker together with the fix.
"""

from __future__ import annotations

import re
import shutil
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Set, Tuple

import pytest

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Loops.TGEndtIterationNode import TGEndIterationNode
from discopop_explorer.classes.TaskGraph.Loops.TGStartIterationNode import TGStartIterationNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.test_TaskGraph_construction import (
    CallSpec,
    FunctionSpec,
    _build_program,
    _construct,
    _contexts_of_type,
    _work_context_covering,
)
from discopop_explorer.pattern_detection import PatternDetectorX
from discopop_explorer.utilities.PEGraphConstruction import parser
from discopop_explorer.utilities.PEGraphConstruction.parser import parse_inputs

PROFILES = Path(__file__).resolve().parents[3] / "test" / "state_assignment"

# TaskGraph.__inline_function_calls stops at call_path_limit = 6 with "depth >= limit", so calls
# are inlined at most 5 levels deep. A state whose callpath contains more calls has no context.
INLINED_CALL_DEPTH = 5

_LOOPSTATE = re.compile(r"^(?P<function>.+)_loopstate(?P<digits>\d+)$")
_CALL = re.compile(r"^call_(?P<id>\d+)$")

# --- helpers: profile based TaskGraphs ------------------------------------------------------


def _task_graph_from_profile(name: str, tmp_path: Path) -> TaskGraph:
    """Builds the TaskGraph of a checked-in profile the way PatternDetectorX.detect_patterns does,
    without the AST and the pattern detectors."""
    profile = tmp_path / name
    shutil.copytree(PROFILES / name, profile)
    # the parser collects the line -> CU maps in module globals and never resets them, so a second
    # PET built in the same process would see the CUs of the first one (pre-existing, see PLAN.md)
    for line_map in (parser.readlineToCUIdMap, parser.writelineToCUIdMap, parser.lineToCUIdMap):
        line_map.clear()
    pet = PEGraphX.from_parsed_input(
        *parse_inputs(  # type: ignore[arg-type]
            str(profile / "Data.xml"),
            str(profile / "dynamic_dependencies.txt"),
            str(profile / "reduction.txt"),
            str(profile / "FileMapping.txt"),
        )
    )
    detector = PatternDetectorX(pet)
    detector._PatternDetectorX__merge(False, True)  # type: ignore[attr-defined]
    pet.map_static_and_dynamic_dependencies()
    pet.calculateFunctionMetadata()
    pet.calculateLoopMetadata()
    pet.enforce_single_function_exit_node()
    return TaskGraph(pet, str(profile / "dynamic_dependencies.txt"), str(profile / "static_dependencies.txt"))


def _observed_states(tg: TaskGraph) -> Set[int]:
    """The states the profiler recorded a dependency end under. State 0 marks the source of an
    INIT record and is no callpath."""
    assert tg.dynamic_dependency_file is not None
    text = Path(tg.dynamic_dependency_file).read_text()
    return {int(state) for state in re.findall(r"@(\d+)", text)} - {0}


def _callpaths(tg: TaskGraph) -> Dict[int, List[str]]:
    assert tg.dynamic_dependency_file is not None
    mappings: Dict[str, List[str]] = tg._TaskGraph__get_state_mappings_from_file(  # type: ignore[attr-defined]
        tg.dynamic_dependency_file
    )
    return {int(state): callpath for state, callpath in mappings.items()}


def _assignable(callpath: Sequence[str]) -> bool:
    """A state can only have a context if its callpath does not end in a call (those are skipped
    by __assign_state_ids on purpose) and its calls are not nested deeper than the inlining."""
    if len(callpath) == 0 or _CALL.match(callpath[-1]):
        return False
    return len([entry for entry in callpath if _CALL.match(entry)]) <= INLINED_CALL_DEPTH


def _all_contexts(tg: TaskGraph) -> List[Context]:
    return list(tg._TaskGraph__collect_all_contexts())  # type: ignore[attr-defined]


def _assignments(tg: TaskGraph) -> Dict[int, List[Context]]:
    result: Dict[int, List[Context]] = {}
    for context in _all_contexts(tg):
        for state_id in context.state_ids:
            result.setdefault(int(state_id), []).append(context)
    return result


# A frame is one function instance on a callpath: (function name, call instruction id it was
# entered through or None for main, {loop position: iteration bucket}).
Frame = Tuple[str, Optional[int], Dict[int, int]]


def _frames_of_callpath(callpath: Sequence[str]) -> List[Frame]:
    frames: List[Frame] = []
    pending_call: Optional[int] = None
    for entry in callpath:
        call = _CALL.match(entry)
        loopstate = _LOOPSTATE.match(entry)
        if call:
            pending_call = int(call.group("id"))
        elif loopstate:
            # successive loopstates of one frame are transitions, the last one is the current state
            assert len(frames) > 0 and frames[-1][0] == loopstate.group("function"), callpath
            digits = loopstate.group("digits")
            frames[-1] = (
                frames[-1][0],
                frames[-1][1],
                {position: int(digit) for position, digit in enumerate(digits) if digit in "012"},
            )
        else:
            frames.append((entry, pending_call, {}))
            pending_call = None
    return frames


def _frames_of_context(tg: TaskGraph, context: Context) -> List[Tuple[str, Optional[int], Dict[int, List[int]]]]:
    """The frames spelled out by the ancestor chain of a context, outermost first. The loops of a
    frame map to the iteration ids of the iteration context the chain passes, or to [0, 1, 2]
    for a loop header (a context below the loop but outside its iterations)."""
    chain: List[Context] = []
    current: Optional[Context] = context
    while current is not None and len(chain) < 10000:
        chain.append(current)
        current = current.parent_context
    chain.reverse()
    frames: List[Tuple[str, Optional[int], Dict[int, List[int]]]] = []
    pending_call: Optional[int] = None
    for index, ctx in enumerate(chain):
        if isinstance(ctx, InlinedFunctionContext):
            pending_call = ctx.call_instruction_id
        elif isinstance(ctx, FunctionContext):
            assert ctx.parent_function is not None
            frames.append((tg.pet.node_at(ctx.parent_function).name, pending_call, {}))
            pending_call = None
        elif isinstance(ctx, LoopParentContext) and len(frames) > 0 and ctx.loopstate_position is not None:
            below = chain[index + 1] if index + 1 < len(chain) else None
            ids = below.loopstate_iteration_ids if isinstance(below, IterationContext) else [0, 1, 2]
            frames[-1][2][ctx.loopstate_position] = list(ids)
    return frames


def _context_matches_callpath(tg: TaskGraph, context: Context, callpath: Sequence[str]) -> bool:
    expected = _frames_of_callpath(callpath)
    actual = _frames_of_context(tg, context)
    if len(expected) != len(actual):
        return False
    for (name, call, buckets), (actual_name, actual_call, iteration_ids) in zip(expected, actual):
        if name != actual_name:
            return False
        # main's frame is not entered through a call; every other frame has to match its call site
        if call is not None and call != actual_call:
            return False
        if set(buckets) != set(iteration_ids):
            return False
        if any(bucket not in iteration_ids[position] for position, bucket in buckets.items()):
            return False
    return True


# start marker class name -> end marker class name
_MARKER_PAIRS = {
    "TGStartFunctionNode": "TGEndFunctionNode",
    "TGStartLoopNode": "TGEndLoopNode",
    "TGStartIterationNode": "TGEndIterationNode",
    "TGStartBranchParentNode": "TGEndBranchParentNode",
    "TGStartBranchNode": "TGEndBranchNode",
    "TGStartWorkNode": "TGEndWorkNode",
    "TGStartInlinedFunctionNode": "TGEndInlinedFunctionNode",
}
_END_MARKERS = {end: start for start, end in _MARKER_PAIRS.items()}


def _unbalanced_markers(tg: TaskGraph, max_depth: int = 80) -> List[Tuple[str, str, Optional[str]]]:
    """(function, end marker, innermost open start marker) for every end marker that some path
    from a function entry reaches while a different start marker is innermost. Context nesting
    walks the graph with exactly such a stack, so every violation gives some context a wrong
    parent."""
    violations: List[Tuple[str, str, Optional[str]]] = []
    for function_id, function_node in tg.TGFunctionNode_pet_node_id_to_tg_node.items():
        assert function_id is not None
        name = tg.pet.node_at(function_id).name
        queue: Deque[Tuple[Any, Tuple[str, ...]]] = deque([(function_node, ())])
        seen: Set[Tuple[Any, Tuple[str, ...]]] = {(function_node, ())}
        while len(queue) > 0:
            node, stack = queue.popleft()
            kind = type(node).__name__
            if kind in _MARKER_PAIRS:
                stack = stack + (kind,)
            elif kind in _END_MARKERS:
                if len(stack) == 0 or stack[-1] != _END_MARKERS[kind]:
                    violations.append((name, kind, stack[-1] if len(stack) > 0 else None))
                stack = stack[:-1]
            if len(stack) > max_depth:
                continue
            for successor in tg.get_successors(node):
                if (successor, stack) not in seen:
                    seen.add((successor, stack))
                    queue.append((successor, stack))
    return violations


# --- profile tests ----------------------------------------------------------------------------


# program -> reasons it currently fails "every assignable state is assigned"
_PROFILES_ALL_ASSIGNED: Dict[str, List[str]] = {
    "ground_truth": [],
    "loopcall": [],
    "nested": [],
    "recursion": [],
    "whileand": [],
    "dowhile": [],
    "breakexit": [],
    "exitinloop": [],
    "conditions": [],
    "shortcircuit": [],
}
# program -> reasons it currently fails "no state is assigned to several contexts"
_PROFILES_UNIQUE: Dict[str, List[str]] = {
    "ground_truth": [],
    "loopcall": [],
    "nested": [],
    "recursion": [],
    "whileand": [],
    "dowhile": [],
    "breakexit": [],
    "exitinloop": [],
    "conditions": [],
    "shortcircuit": [],
}

# reasons which only make a test fail in some processes
_NONDETERMINISTIC: Set[str] = set()

# program -> reasons it currently fails "markers are balanced"
_PROFILES_BALANCED: Dict[str, List[str]] = {
    "ground_truth": [],
    "loopcall": [],
    "nested": [],
    "recursion": [],
    "whileand": [],
    "dowhile": [],
    "breakexit": [],
    "exitinloop": [],
    "conditions": [],
    "shortcircuit": [],
}


def _profile_params(reasons: Dict[str, List[str]]) -> List[Any]:
    return [
        (
            pytest.param(
                name,
                marks=pytest.mark.xfail(
                    strict=not any(reason in _NONDETERMINISTIC for reason in why),
                    raises=AssertionError,
                    reason="; ".join(why),
                ),
            )
            if why
            else name
        )
        for name, why in reasons.items()
    ]


@pytest.mark.parametrize("program", _profile_params(_PROFILES_ALL_ASSIGNED))
def test_every_assignable_observed_state_is_assigned(program: str, tmp_path: Path) -> None:
    """Every state a dependency was observed under, and whose callpath stays within the inlining
    depth, has to reach a context. Otherwise its dependencies are dropped (pattern detection) or
    reported as unmapped (get_side_effects)."""
    tg = _task_graph_from_profile(program, tmp_path)
    callpaths = _callpaths(tg)

    expected = {state for state in _observed_states(tg) if _assignable(callpaths.get(state, []))}
    missing = sorted(expected - set(_assignments(tg)))

    assert missing == [], "\n".join(f"{state}: {' / '.join(callpaths[state])}" for state in missing)


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_assigned_contexts_spell_out_the_callpath_of_their_state(program: str, tmp_path: Path) -> None:
    """A state may only be assigned to a context whose ancestor chain is its callpath: the same
    functions entered through the same call instructions, inside iterations whose ids contain the
    loopstate's bucket of every active loop. Holds for the states assigned today, and has to keep
    holding for the ones a fix adds."""
    tg = _task_graph_from_profile(program, tmp_path)
    callpaths = _callpaths(tg)

    wrong = [
        (state, " / ".join(callpaths[state]), context.get_label())
        for state, contexts in _assignments(tg).items()
        for context in contexts
        if not _context_matches_callpath(tg, context, callpaths[state])
    ]

    assert wrong == []


@pytest.mark.parametrize("program", _profile_params(_PROFILES_UNIQUE))
def test_no_state_is_assigned_to_several_contexts(program: str, tmp_path: Path) -> None:
    """A state has one iteration bucket per active loop and call instruction ids are unique, so it
    describes exactly one copy of a context. A state matching several contexts means that the
    TaskGraph holds two contexts with the same callpath, i.e. a structural error. (A context with
    several states is intended: the iteration [0, 2] gets the states of buckets 0 and 2.) The one
    exception are the copies __split_branch_region_side_entries makes of a block reached through
    different paths of a short-circuit condition: the state cannot tell these paths apart, and
    the copies cover the same code."""
    tg = _task_graph_from_profile(program, tmp_path)
    callpaths = _callpaths(tg)

    multi = {
        state: len(contexts)
        for state, contexts in _assignments(tg).items()
        if len({frozenset(context.get_code_scope_set(tg.pet)) for context in contexts}) > 1
    }

    assert multi == {}, "\n".join(f"{state}: {' / '.join(callpaths[state])}" for state in multi)


@pytest.mark.parametrize("program", _profile_params(_PROFILES_BALANCED))
def test_start_and_end_markers_are_balanced_on_every_path(program: str, tmp_path: Path) -> None:
    """Context nesting (__calculate_context_nesting) walks the graph with a stack of entered
    contexts. An end marker reached while another context is innermost pops the wrong one, so all
    contexts after it get wrong parents - and the state search, which walks the parent/child
    relation, cannot reach them."""
    tg = _task_graph_from_profile(program, tmp_path)

    assert _unbalanced_markers(tg) == []


# --- synthetic tests: one per cause ---------------------------------------------------------

# main: 1:1 -> 1:2 (header) -> 1:3 (body, calls foo with call instruction 7) -> 1:2, 1:2 -> 1:4
# foo:  1:11 -> 1:12
CALL_IN_LOOP: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:2"), ("1:2", "1:4")]),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
CALL_IN_LOOP_CALLS: Sequence[CallSpec] = (("1:3", "1:10", 7),)
# states 30, 31, 32: foo called in iteration bucket 0, 1, 2 of main's loop (written the way the
# profiler writes them: the loopstate transitions of the iteration precede the call)
CALL_IN_LOOP_STATES = "\n".join(
    [
        "1 1 ROOT",
        "11 1 main",
        "20 11 main_loopstate0",
        "21 20 main_loopstate1",
        "22 21 main_loopstate2",
        "23 20 call_7",
        "30 23 foo",
        "24 21 call_7",
        "31 24 foo",
        "25 22 call_7",
        "32 25 foo",
        "",
    ]
)
CALL_IN_LOOP_DEPENDENCIES = "1:12@31 NOM RAW 1:12@30|g(100) RAW 1:12@32|g(100)\n"


def _inlined_foo_by_iteration(tg: TaskGraph) -> Dict[Tuple[int, ...], FunctionContext]:
    result: Dict[Tuple[int, ...], FunctionContext] = {}
    for call in _contexts_of_type(tg, InlinedFunctionContext):
        [inlined] = call.contained_contexts
        assert isinstance(inlined, FunctionContext)
        ancestor = call.parent_context
        while ancestor is not None and not isinstance(ancestor, IterationContext):
            ancestor = ancestor.parent_context
        assert isinstance(ancestor, IterationContext), "the call sits in the loop body"
        result[tuple(ancestor.loopstate_iteration_ids)] = inlined
    return result


def test_a_call_in_a_loop_body_gets_the_states_of_its_iteration(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """A callpath continuing after a loopstate entry ("main_loopstate1 / call_7 / foo") reaches the
    copy of foo inlined into the matching iteration. (The former top-down matcher consumed a
    loopstate entry only if it was the last one of the callpath.)"""
    pet = _build_program(build_pet_graph, make_node, CALL_IN_LOOP, CALL_IN_LOOP_CALLS)

    tg = _construct(tmp_path, pet, CALL_IN_LOOP_DEPENDENCIES, state_mappings=CALL_IN_LOOP_STATES)

    by_iteration = {ids: sorted(foo.state_ids) for ids, foo in _inlined_foo_by_iteration(tg).items()}
    assert by_iteration == {(1,): [31], (0, 2): [30, 32]}


# main: for (i...) { for (j...) { foo(); } }
#   1:1 -> 1:2 (outer header) -> 1:3 (inner header) -> 1:4 (inner body, calls foo) -> 1:3
#          1:3 -> 1:5 (outer latch) -> 1:2,  1:2 -> 1:6 (exit)
NESTED_LOOPS: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6"],
        [
            ("1:1", "1:2"),
            ("1:2", "1:3"),
            ("1:3", "1:4"),
            ("1:4", "1:3"),
            ("1:3", "1:5"),
            ("1:5", "1:2"),
            ("1:2", "1:6"),
        ],
    ),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
NESTED_LOOPS_CALLS: Sequence[CallSpec] = (("1:4", "1:10", 7),)


def _iteration_ids_of_inner_loops(tg: TaskGraph) -> List[List[List[int]]]:
    """For each iteration context of the outer loop (pet node 1:2): the sorted iteration ids of the
    inner loop's (pet node 1:3) iteration contexts nested in it."""
    result = []
    for outer in _contexts_of_type(tg, IterationContext):
        if not isinstance(outer.parent_context, LoopParentContext) or outer.parent_context.parent_loop != "1:2":
            continue
        inner_ids = []
        for context in _all_contexts(tg):
            if isinstance(context, IterationContext) and isinstance(context.parent_context, LoopParentContext):
                if context.parent_context.parent_loop == "1:3" and context.parent_context.parent_context is outer:
                    inner_ids.append(list(context.loopstate_iteration_ids))
        result.append(sorted(inner_ids))
    return sorted(result)


@pytest.mark.parametrize(
    "outer_first",
    [
        True,
        False,
    ],
)
def test_nested_loop_iterations_are_duplicated_regardless_of_processing_order(
    build_pet_graph: Any, make_node: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outer_first: bool
) -> None:
    """Every iteration of the outer loop has to contain both iterations ([1] and [0, 2]) of the inner
    loop. Copies are never copied again, so __duplicate_loop_iterations has to duplicate inner loops
    first; it used to follow the order of get_descendants (set iteration order, varying between
    processes), which is forced both ways here."""
    original = TaskGraph.get_descendants

    def ordered_descendants(self: TaskGraph, node: Any) -> List[Any]:
        def key(n: Any) -> Tuple[int, str]:
            if isinstance(n, TGStartIterationNode):
                is_outer = n.parent_loop_pet_node_id == "1:2"
                return (0 if is_outer == outer_first else 1, str(n.pet_node_id))
            return (2, "")

        return sorted(original(self, node), key=key)

    monkeypatch.setattr(TaskGraph, "get_descendants", ordered_descendants)
    pet = _build_program(build_pet_graph, make_node, NESTED_LOOPS, NESTED_LOOPS_CALLS)

    tg = _construct(tmp_path, pet)

    assert _iteration_ids_of_inner_loops(tg) == [[[0, 2], [1]], [[0, 2], [1]]]


# main: do { body (calls foo) } while (cond);
#   1:1 -> 1:2 (body entry) -> 1:3 (body, calls foo) -> 1:4 (condition, latch) -> 1:2 (back edge)
#          1:4 -> 1:5 (exit)
# (with a body of a single CU, the start and the end iteration marker share its pet node id, and
# __fix_loop_structures happens to remove the duplicated end marker; see the compound condition)
DO_WHILE: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5"],
        [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:4"), ("1:4", "1:2"), ("1:4", "1:5")],
    ),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
DO_WHILE_CALLS: Sequence[CallSpec] = (("1:3", "1:10", 7),)


def test_a_loop_tested_at_its_bottom_has_one_start_and_one_end_per_iteration(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """In a do-while loop the latch is also the exit source. __break_cycles used to add it to the
    iteration exit points twice (as latch and as exit source), and __duplicate_loop_iterations
    copied the iteration once per end marker: three iteration copies ([1], [1], [0, 2]) hanging
    off different arms of the latch instead of two in sequence."""
    pet = _build_program(build_pet_graph, make_node, DO_WHILE, DO_WHILE_CALLS)

    tg = _construct(tmp_path, pet)

    main_nodes = set(tg.get_descendants(tg.TGFunctionNode_pet_node_id_to_tg_node["1:0"]))  # type: ignore[index]
    starts = [n for n in main_nodes if isinstance(n, TGStartIterationNode)]
    ends = [n for n in main_nodes if isinstance(n, TGEndIterationNode)]
    assert (len(starts), len(ends)) == (2, 2), "the original iteration and its single copy"
    [loop] = _contexts_of_type(tg, LoopParentContext)
    iterations = [c for c in _contexts_of_type(tg, IterationContext) if c.parent_context is loop]
    assert sorted(it.loopstate_iteration_ids for it in iterations) == [[0, 2], [1]]


# main: while (a() && b) { body (calls foo) }
#   1:1 -> 1:2 (first condition) -> 1:3 (second condition) -> 1:4 (combined result)
#          1:2 -> 1:4 (short circuit),  1:4 -> 1:5 (body, calls foo) -> 1:6 (latch) -> 1:2
#          1:4 -> 1:7 (exit)
COMPOUND_CONDITION: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7"],
        [
            ("1:1", "1:2"),
            ("1:2", "1:3"),
            ("1:2", "1:4"),
            ("1:3", "1:4"),
            ("1:4", "1:5"),
            ("1:5", "1:6"),
            ("1:6", "1:2"),
            ("1:4", "1:7"),
        ],
    ),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
COMPOUND_CONDITION_CALLS: Sequence[CallSpec] = (("1:5", "1:10", 7),)


def test_a_loop_with_a_compound_condition_keeps_its_body(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """The entry node 1:2 has two successors in the cycle. __break_cycles used to create a start
    iteration marker for each (1:3 and 1:4), and an end marker after the exit source 1:4. The start
    marker of 1:4 and that end marker shared a pet node id, which is what __fix_loop_structures
    pairs on: the "iteration" between them was 1:4 alone, the edge 1:4 -> 1:5 looked like a break,
    and the whole body was deleted as unreachable."""
    pet = _build_program(build_pet_graph, make_node, COMPOUND_CONDITION, COMPOUND_CONDITION_CALLS)

    tg = _construct(tmp_path, pet)

    bodies = _work_context_covering(tg, "1:5")
    assert len(bodies) == 2, "one copy of the body per iteration context"
    assert sorted(it.loopstate_iteration_ids for it in _contexts_of_type(tg, IterationContext)) == [[0, 2], [1]]


# main: for (i = 0; i < n(); ++i) { body }  - the header calls n (call instruction 7)
#   1:1 -> 1:2 (header, calls n) -> 1:3 (body) -> 1:2,  1:2 -> 1:4
CALL_IN_HEADER: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:2"), ("1:2", "1:4")]),
    ("1:10", "n", ["1:11", "1:12"], [("1:11", "1:12")]),
)
CALL_IN_HEADER_CALLS: Sequence[CallSpec] = (("1:2", "1:10", 7),)
CALL_IN_HEADER_STATES = CALL_IN_LOOP_STATES.replace(" foo", " n")


def test_a_call_in_a_loop_header_gets_the_states_of_all_iterations(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """The loop header (the entry node, between the loop start and the first iteration) belongs
    to the LoopParentContext, not to an iteration. A call in it runs in every iteration bucket, so
    it gets the states of all of them."""
    pet = _build_program(build_pet_graph, make_node, CALL_IN_HEADER, CALL_IN_HEADER_CALLS)

    tg = _construct(tmp_path, pet, CALL_IN_LOOP_DEPENDENCIES, state_mappings=CALL_IN_HEADER_STATES)

    [call] = _contexts_of_type(tg, InlinedFunctionContext)
    [inlined] = call.contained_contexts
    assert sorted(inlined.state_ids) == [30, 31, 32]
