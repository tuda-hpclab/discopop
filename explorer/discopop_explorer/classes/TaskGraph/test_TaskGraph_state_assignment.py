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
  explorer/test/state_assignment/<program>/ (code.cpp is the profiled source, regenerate.sh
  rebuilds the profiler output). They check that every observed state is assigned, that it is
  assigned to a context whose ancestor chain spells out its callpath, and that the start/end markers
  of the graph are balanced along every path, which context nesting relies on. The callpath check
  reads the loops the way the matcher does (LoopParentContext.loopstate_position); the independent
  oracle (_oracle_violations) starts from the dependency records instead, maps instruction ids to
  lines and identifies loops by the profiler's loopstate_positions.txt.
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

from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Loops.TGEndtIterationNode import TGEndIterationNode
from discopop_explorer.classes.TaskGraph.Loops.TGStartIterationNode import TGStartIterationNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.enums.EdgeType import EdgeType
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
            frames.append((_function_name(tg, ctx), pending_call, {}))
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
    "trycatch": [],
    "recloop": [],
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
    "trycatch": [],
    "recloop": [],
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
    "trycatch": [],
    "recloop": [],
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

    approximate = tg.approximately_assigned_state_ids
    wrong = [
        (state, " / ".join(callpaths[state]), context.get_label())
        for state, contexts in _assignments(tg).items()
        if state not in approximate
        for context in contexts
        if not _context_matches_callpath(tg, context, callpaths[state])
    ]

    assert wrong == []


def _matches_a_callee_suffix(tg: TaskGraph, context: Context, callpath: Sequence[str]) -> bool:
    """The context spells out the part of the callpath from some called function on."""
    return any(
        _context_matches_callpath(tg, context, callpath[start:])
        for start in range(1, len(callpath))
        if not _CALL.match(callpath[start]) and not _LOOPSTATE.match(callpath[start])
    )


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_unmatched_states_go_to_the_standalone_copy_of_a_function_on_their_callpath(
    program: str, tmp_path: Path
) -> None:
    """A state without a context of its full callpath (e.g. deeper than the inlining) is attached
    to the standalone copy of a function on its callpath, keeping the longest matching suffix,
    and is listed as approximate. Together with the exact matches, every observed state whose
    callpath does not end in a call has a context."""
    tg = _task_graph_from_profile(program, tmp_path)
    callpaths = _callpaths(tg)
    assignments = _assignments(tg)

    wrong = [
        (state, " / ".join(callpaths[state]), context.get_label())
        for state in tg.approximately_assigned_state_ids
        for context in assignments.get(state, [])
        if not _matches_a_callee_suffix(tg, context, callpaths[state])
    ]
    unassigned = [
        state
        for state in _observed_states(tg)
        if len(callpaths.get(state, [])) > 0 and not _CALL.match(callpaths[state][-1]) and state not in assignments
    ]

    assert wrong == []
    assert unassigned == []


def _creating_node(context: Context) -> Optional[Any]:
    """The start marker a context was created for (e.g. the TGStartFunctionNode of a
    FunctionContext, the TGStartIterationNode of an IterationContext)."""
    for node in context.contained_nodes:
        if getattr(node, "created_context", None) is context:
            return node
    return None


def _tail_duplication_original(tg: TaskGraph, node: Any) -> Any:
    """The node a tail duplication copy (__split_branch_region_side_entries) was made of, following
    copies of copies; the node itself if it is no copy."""
    seen = set()
    while node in tg.tail_duplication_origins and id(node) not in seen:
        seen.add(id(node))
        node = tg.tail_duplication_origins[node]
    return node


def _unexplained_multi_assignments(tg: TaskGraph) -> Dict[int, List[Context]]:
    """States assigned to several contexts which are not the copies of one context made by tail
    duplication. A copy made there is marked in tg.tail_duplication_origins; its contexts are
    created later for the copied start markers. Every other second context of a callpath (an
    iteration copied twice, a function inlined twice at one call) is a structural error - even if
    it covers the same code, which a comparison of code scopes cannot tell apart."""
    result: Dict[int, List[Context]] = {}
    for state, contexts in _assignments(tg).items():
        if len(contexts) < 2:
            continue
        nodes = [_creating_node(context) for context in contexts]
        originals = {id(_tail_duplication_original(tg, node)) for node in nodes if node is not None}
        explained = (
            all(node is not None for node in nodes)
            and len(originals) == 1
            and any(node in tg.tail_duplication_origins for node in nodes)
        )
        if not explained:
            result[state] = contexts
    return result


@pytest.mark.parametrize("program", _profile_params(_PROFILES_UNIQUE))
def test_no_state_is_assigned_to_several_contexts(program: str, tmp_path: Path) -> None:
    """A state has one iteration bucket per active loop and call instruction ids are unique, so it
    describes exactly one copy of a context. A state matching several contexts means that the
    TaskGraph holds two contexts with the same callpath, i.e. a structural error. (A context with
    several states is intended: the iteration [0, 2] gets the states of buckets 0 and 2.) The one
    exception are the copies __split_branch_region_side_entries makes of a block reached through
    different paths of a condition (tail duplication): the state cannot tell these paths apart.
    They are recognized by the copies the TaskGraph records, not by their code scope, which an
    iteration copied twice or a function inlined twice at one call shares as well."""
    tg = _task_graph_from_profile(program, tmp_path)
    callpaths = _callpaths(tg)

    multi = _unexplained_multi_assignments(tg)

    assert multi == {}, "\n".join(f"{state}: {' / '.join(callpaths[state])}" for state in multi)


@pytest.mark.parametrize("program", _profile_params(_PROFILES_BALANCED))
def test_start_and_end_markers_are_balanced_on_every_path(program: str, tmp_path: Path) -> None:
    """Context nesting (__calculate_context_nesting) walks the graph with a stack of entered
    contexts. An end marker reached while another context is innermost pops the wrong one, so all
    contexts after it get wrong parents - and the state search, which walks the parent/child
    relation, cannot reach them."""
    tg = _task_graph_from_profile(program, tmp_path)

    assert _unbalanced_markers(tg) == []


# --- independent oracle: dependency records against contexts ---------------------------------
#
# The tests above check the assignments the matcher made, with the matcher's own view of a loop
# (LoopParentContext.loopstate_position). The checks below start from the profiler's records
# instead and take the identity of a loop from loopstate_positions.txt (Data.xml loop node per
# digit position), so that a wrong position, a wrong iteration or a wrong call shows up as a record
# whose end has no context. They share no code or derived data with TaskGraph.__assign_state_ids.

# program -> {line: reason} of the dependency ends the oracle accepts without a context of their
# state at their line, because the profiler records them under a state of another callpath
# program -> {line: reason} of record ends the profiler attributes to a wrong callpath state, each with its
# profiler cause (the entries for indirect calls and caught exceptions were removed with 098187f1)
_ORACLE_KNOWN_DEVIATIONS: Dict[str, Dict[str, str]] = {
    "exitinloop": {
        # profiler: leaving a loop through `return` executes no loop exit transition, so the shared return
        # block of the function records under the state of the loop iteration it returned from (the
        # function's return then restores the caller's state). Detection is unaffected: such ends are
        # mapped by _ContextFallback, and loops left by return are rejected (cut exits).
        "1:26": "find's return block, reached by `return i;` from inside the loop, records under the loop state",
    },
}


def _instruction_lines(profile: Path) -> Dict[int, str]:
    """instruction id -> "file_id:line" from instructionID_to_lineID_mapping.txt"""
    result: Dict[int, str] = {}
    for line in (profile / "instructionID_to_lineID_mapping.txt").read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1] != "*":
            file_id, line_number = fields[1].split(":")[:2]
            result[int(fields[0])] = file_id + ":" + line_number
    return result


def _record_ends(profile: Path) -> List[Tuple[int, Optional[int]]]:
    """(instruction id, state or None) of both ends of every record of dynamic_dependencies.txt"""
    ends: List[Tuple[int, Optional[int]]] = []
    for line in (profile / "dynamic_dependencies.txt").read_text().splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] != "NOM":
            continue
        for location in [fields[0]] + [field.split("|")[0] for field in fields[2:] if "|" in field]:
            instruction, _, state = location.partition("@")
            if instruction.isdigit():
                ends.append((int(instruction), int(state) if state.isdigit() else None))
    return ends


def _listed_loops(profile: Path) -> Dict[str, Dict[int, Tuple[str, str]]]:
    """function name -> {loopstate position: (Data.xml loop node id, start location)}, read from
    loopstate_positions.txt ("<function> <position> <loop id> <loop node id> <file_id:line>")"""
    result: Dict[str, Dict[int, Tuple[str, str]]] = {}
    for line in (profile / "loopstate_positions.txt").read_text().splitlines():
        fields = line.split()
        if len(fields) == 5:
            result.setdefault(fields[0], {})[int(fields[1])] = (fields[3], fields[4])
    return result


def _function_name(tg: TaskGraph, function: FunctionContext) -> str:
    assert function.parent_function is not None
    return str(tg.pet.node_at(function.parent_function).name)


def _lines_of_cus(tg: TaskGraph, cus: Set[Any]) -> Set[str]:
    lines: Set[str] = set()
    for cu in cus:
        node = tg.pet.node_at(cu)
        lines |= {f"{node.file_id}:{line}" for line in range(node.start_line, node.end_line + 1)}
    return lines


def _loop_node_of(tg: TaskGraph, loop: LoopParentContext) -> Optional[str]:
    """The PET LoopNode of a loop context: the parent of the loop's entry CU."""
    parents = [
        source
        for source, _, edge in tg.pet.g.in_edges(loop.parent_loop, data="data")
        if edge.etype == EdgeType.CHILD and isinstance(tg.pet.node_at(source), LoopNode)
    ]
    return str(parents[0]) if len(parents) == 1 else None


# a frame of the oracle: (function name, call instruction id, {loop node id: buckets or iteration ids})
_OracleFrame = Tuple[str, Optional[int], Dict[str, Tuple[int, ...]]]


def _oracle_frames_of_callpath(
    callpath: Sequence[str], listed: Dict[str, Dict[int, Tuple[str, str]]]
) -> List[_OracleFrame]:
    """The frames of a callpath, with the active loops named by their Data.xml loop node (a
    position the profiler does not list stays unnamed and matches no context)."""
    frames: List[_OracleFrame] = []
    for name, call, buckets in _frames_of_callpath(callpath):
        loops = listed.get(name, {})
        frames.append(
            (
                name,
                call,
                {(loops[p][0] if p in loops else f"unlisted position {p}"): (b,) for p, b in buckets.items()},
            )
        )
    return frames


def _oracle_frames_of_context(tg: TaskGraph, context: Context) -> List[_OracleFrame]:
    """The frames the ancestor chain of a context spells out, outermost first. A loop maps to the
    iteration ids of the iteration the chain passes, or to (0, 1, 2) for its header."""
    chain = [context] + context.get_ancestor_contexts()
    chain.reverse()
    frames: List[_OracleFrame] = []
    pending_call: Optional[int] = None
    for index, ctx in enumerate(chain):
        if isinstance(ctx, InlinedFunctionContext):
            pending_call = ctx.call_instruction_id
        elif isinstance(ctx, FunctionContext):
            frames.append((_function_name(tg, ctx), pending_call, {}))
            pending_call = None
        elif isinstance(ctx, LoopParentContext) and len(frames) > 0:
            below = chain[index + 1] if index + 1 < len(chain) else None
            ids = tuple(below.loopstate_iteration_ids) if isinstance(below, IterationContext) else (0, 1, 2)
            frames[-1][2][str(_loop_node_of(tg, ctx))] = ids
    return frames


def _oracle_frames_match(expected: List[_OracleFrame], actual: List[_OracleFrame], suffix: bool) -> bool:
    """actual spells out expected: the same functions entered through the same calls, the same active
    loops, iterations containing the buckets. With suffix, actual may spell out a part of expected
    starting at some called function (the standalone copy of a function, see the suffix fallback)."""
    starts = range(0, len(expected)) if suffix else range(0, 1)
    for start in starts:
        tail = expected[start:]
        if len(tail) != len(actual):
            continue
        if all(
            name == actual_name
            and (index == 0 or call == actual_call)
            and set(loops) == set(actual_loops)
            and all(bucket[0] in actual_loops[loop] for loop, bucket in loops.items())
            for index, ((name, call, loops), (actual_name, actual_call, actual_loops)) in enumerate(zip(tail, actual))
        ):
            return True
    return False


def _in_the_header_of_an_active_loop(tg: TaskGraph, context: Context, callpath: Sequence[str]) -> bool:
    """The context lies in the header of the innermost loop the callpath has active (a header
    belongs to the LoopParentContext and carries the states of the context around the loop, the
    end of such a record is mapped by _ContextFallback)."""
    frames = _frames_of_callpath(callpath)
    if len(frames) == 0 or len(frames[-1][2]) == 0:
        return False
    return isinstance(context.parent_context, LoopParentContext)


def _oracle_violations(tg: TaskGraph, profile: Path, program: str) -> Tuple[List[str], Dict[str, int]]:
    """Every end `instruction@state` of a dynamic dependency record: the line of the instruction has
    to lie in the code scope of a work context which carries the state (Context.get_state_ids) and
    whose ancestor chain spells out the state's callpath. Accepted without that: states 0 and
    callpaths ending in a call (no context by design), lines without any context that the TaskGraph
    cut (early exits, exception unwinding), loop headers, and _ORACLE_KNOWN_DEVIATIONS. Returns the
    violations and the number of ends per category."""
    lines = _instruction_lines(profile)
    listed = _listed_loops(profile)
    callpaths = _callpaths(tg)
    known = _ORACLE_KNOWN_DEVIATIONS.get(program, {})
    work_contexts_at: Dict[str, List[Context]] = {}
    for context in _all_contexts(tg):
        if isinstance(context, WorkContext):
            for scope_line in context.get_code_scope_set(tg.pet):
                work_contexts_at.setdefault(str(scope_line), []).append(context)
    cut_lines = _lines_of_cus(tg, set(tg.cus_deleted_by_early_exits) | set(tg.cus_deleted_by_exception_unwinding))

    violations: List[str] = []
    counts: Dict[str, int] = {}
    for instruction, state in sorted(set(_record_ends(profile)), key=lambda end: (end[0], end[1] or 0)):
        callpath = callpaths.get(state, []) if state is not None else []
        line = lines.get(instruction)
        if state is None or state == 0 or line is None:
            category = "without state or line"
        elif len(callpath) == 0 or _CALL.match(callpath[-1]):
            category = "callpath ends in a call"
        elif line in known:
            category = "known deviation"
        elif line not in work_contexts_at:
            category = "cut line" if line in cut_lines else "VIOLATION"
            if category == "VIOLATION":
                violations.append(f"{instruction}@{state} at {line}: no context ({' / '.join(callpath)})")
        else:
            expected = _oracle_frames_of_callpath(callpath, listed)
            suffix = state in tg.approximately_assigned_state_ids
            matching = [
                context
                for context in work_contexts_at[line]
                if _oracle_frames_match(expected, _oracle_frames_of_context(tg, context), suffix)
            ]
            if any(state in context.get_state_ids() for context in matching):
                category = "approximate state" if suffix else "exact"
            elif any(_in_the_header_of_an_active_loop(tg, context, callpath) for context in matching):
                category = "loop header"
            else:
                category = "VIOLATION"
                carrying = [c for c in work_contexts_at[line] if state in c.get_state_ids()]
                violations.append(
                    f"{instruction}@{state} at {line} ({' / '.join(callpath)}): "
                    + f"{len(matching)} contexts spell out the callpath, {len(carrying)} carry the state"
                )
        counts[category] = counts.get(category, 0) + 1
    return violations, counts


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_every_dependency_end_lies_in_a_context_of_its_state(program: str, tmp_path: Path) -> None:
    """The independent oracle (see _oracle_violations): every recorded dependency end is found at a
    context of its state which spells out the state's callpath, with the loops identified by the
    profiler's loopstate_positions.txt. Fails e.g. for swapped loopstate positions, an iteration
    which does not contain its bucket, or a state attached to the wrong copy of a function."""
    tg = _task_graph_from_profile(program, tmp_path)

    violations, counts = _oracle_violations(tg, tmp_path / program, program)

    assert violations == [], counts
    assert counts.get("exact", 0) > 0, "the oracle checked no end at all"


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_every_loop_has_the_loopstate_position_the_profiler_lists(program: str, tmp_path: Path) -> None:
    """The position of a loop in the "_loopstate" digits is written by the profiler to
    loopstate_positions.txt, per function, with the Data.xml loop node and start location; every
    LoopParentContext has to carry exactly that position."""
    tg = _task_graph_from_profile(program, tmp_path)
    listed = _listed_loops(tmp_path / program)
    position_of = {
        (function, node_id): position for function, loops in listed.items() for position, (node_id, _) in loops.items()
    }

    loops = _contexts_of_type(tg, LoopParentContext)
    wrong = []
    for loop in loops:
        function = loop.get_closest_function_ancestor()
        assert isinstance(function, FunctionContext)
        name = _function_name(tg, function)
        node_id = _loop_node_of(tg, loop)
        expected = position_of.get((name, str(node_id)))
        if loop.loopstate_position != expected:
            wrong.append((name, node_id, loop.loopstate_position, expected))
        if expected is not None:
            pet_loop = tg.pet.node_at(node_id)  # type: ignore[arg-type]
            assert listed[name][expected][1] == f"{pet_loop.file_id}:{pet_loop.start_line}", "the start location"

    assert wrong == []
    assert len(loops) == 0 or any(loop.loopstate_position is not None for loop in loops)


def _iterations_in_sequence(loop: LoopParentContext) -> List[IterationContext]:
    """The iteration contexts of a loop in the order they follow each other."""
    iterations = [c for c in loop.contained_contexts if isinstance(c, IterationContext)]
    first = [it for it in iterations if it.predecessor not in iterations]
    if len(first) != 1:
        return []
    sequence: List[IterationContext] = []
    current: Optional[Context] = first[0]
    while isinstance(current, IterationContext) and current in iterations and current not in sequence:
        sequence.append(current)
        current = current.successor
    return sequence


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_the_iteration_copies_follow_the_buckets_of_the_profiler(program: str, tmp_path: Path) -> None:
    """The profiler sets a loop's bucket to 0 when the loop is entered and increments it at the first
    instruction of every iteration (__dp_loop_incr), so the first iteration runs in bucket 1, the
    next in 2, then 0, 1, ... The two iteration copies of a loop therefore have to be [1] followed
    by [0, 2]; with swapped ids, every state would still find an iteration, but dependencies would
    point backwards in the sequence of the iterations."""
    tg = _task_graph_from_profile(program, tmp_path)

    sequences = [
        [list(it.loopstate_iteration_ids) for it in _iterations_in_sequence(loop)]
        for loop in _contexts_of_type(tg, LoopParentContext)
    ]

    assert len(sequences) > 0
    assert [sequence for sequence in sequences if sequence != [[1], [0, 2]]] == []


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


# main's outer loop (position 0, 1:2) and inner loop (position 1, 1:3); the body 1:4 accesses x.
# 40 -> 41: outer bucket 2 -> 0, i.e. consecutive outer iterations, which share the copy [0, 2];
# 42 -> 43: the same outer iteration (bucket 1), inner bucket 0 -> 2
NESTED_LOOP_STATES = "\n".join(
    [
        "1 1 ROOT",
        "11 1 main",
        "40 11 main_loopstate20",
        "41 11 main_loopstate01",
        "42 11 main_loopstate10",
        "43 11 main_loopstate12",
        "",
    ]
)
NESTED_LOOP_DEPENDENCIES = "1:4@41 NOM RAW 1:4@40|x(100)\n1:4@43 NOM RAW 1:4@42|y(101)\n"


def test_a_dependency_knows_the_loop_whose_iterations_it_crosses(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Consecutive iterations with the buckets 2 and 0 share the iteration copy [0, 2], so the
    copies alone make a dependency carried by the outer loop look like one between iterations of
    the inner loop (a false loop-carried dependency of the inner loop, and a missed one of the outer
    loop). The callpath states of the ends tell which loop it crosses."""
    pet = _build_program(build_pet_graph, make_node, NESTED_LOOPS, NESTED_LOOPS_CALLS)

    tg = _construct(tmp_path, pet, NESTED_LOOP_DEPENDENCIES, state_mappings=NESTED_LOOP_STATES)

    carried: Dict[str, Set[Optional[str]]] = {}
    for context in _all_contexts(tg):
        for _, dependency in context.outgoing_dependencies:
            loop = dependency.carried_by_loop
            carried.setdefault(str(dependency.var_name), set()).add(
                loop.parent_loop if isinstance(loop, LoopParentContext) else None
            )
    assert carried == {"x": {"1:2"}, "y": {"1:3"}}


def test_a_dependency_between_iterations_three_apart_is_attributed_to_the_inner_loop(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Known limitation, intended behaviour (the user's decision): the profiler keeps the iteration
    count of a loop modulo 3 only, to save profiling time, and equal buckets are taken as the same
    iteration. The record below can come from the same outer iteration (inner buckets 0 and 2) or
    from the outer iterations k and k+3, which have equal outer buckets. The callpath states cannot
    tell these apart, so it is attributed to the inner loop. Consequences: a dependency carried by
    a loop only at distances 3n looks like one within an iteration of it (a false negative for that
    loop, here the outer one), and the inner loop gets a dependency which may not exist."""
    pet = _build_program(build_pet_graph, make_node, NESTED_LOOPS, NESTED_LOOPS_CALLS)
    states = "\n".join(["1 1 ROOT", "11 1 main", "50 11 main_loopstate10", "51 11 main_loopstate12", ""])

    tg = _construct(tmp_path, pet, "1:4@51 NOM RAW 1:4@50|z(100)\n", state_mappings=states)

    carried = {
        dependency.carried_by_loop.parent_loop
        for context in _all_contexts(tg)
        for _, dependency in context.outgoing_dependencies
        if isinstance(dependency.carried_by_loop, LoopParentContext)
    }
    assert carried == {"1:3"}, "the inner loop, never the outer one (1:2)"


# --- _ContextFallback -----------------------------------------------------------------------

# main: 1:1 -> 1:2 (calls foo, call instruction 7) -> 1:3;  foo: 1:11 -> 1:12
CALL_ONCE: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3"], [("1:1", "1:2"), ("1:2", "1:3")]),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
CALL_ONCE_CALLS: Sequence[CallSpec] = (("1:2", "1:10", 7),)
# 30: foo called from main; 41: a function bar the PET does not know, so no context gets the state
CALL_ONCE_STATES = "\n".join(["1 1 ROOT", "11 1 main", "23 11 call_7", "30 23 foo", "40 11 call_8", "41 40 bar", ""])


def _dependencies_by_variable(tg: TaskGraph) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {}
    for context in _all_contexts(tg):
        for _, dependency in context.outgoing_dependencies:
            result.setdefault(str(dependency.var_name), []).append(dependency)
    return result


def test_an_end_at_a_line_outside_the_contexts_of_its_state_is_mapped_within_its_scope(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """An end recorded under foo's state at a line of main (1:3) has no context carrying its state
    there. _ContextFallback maps it to the contexts at the line below the closest ancestor of foo's
    context (main), instead of dropping the dependency, and marks the dependency approximate; an
    approximate dependency tells no loop it is carried by."""
    pet = _build_program(build_pet_graph, make_node, CALL_ONCE, CALL_ONCE_CALLS)

    tg = _construct(tmp_path, pet, "1:3@30 NOM RAW 1:12@30|x(100)\n", state_mappings=CALL_ONCE_STATES)

    [dependency] = _dependencies_by_variable(tg)["x"]
    assert dependency.approximate_context is True
    assert dependency.carried_by_loop is None
    assert tg.approximate_dependency_end_statistics == {"ends": 1, "scoped": 1, "location_only": 0}
    [sink] = [c for c in _all_contexts(tg) for _, d in c.outgoing_dependencies if d is dependency]
    assert sink in _work_context_covering(tg, "1:3")


def test_an_end_whose_state_no_context_carries_is_mapped_by_its_location_only(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """An end under a state no context carries (here a callpath through a function the PET does not
    know) is mapped to every work context at its line, the coarsest over-approximation."""
    pet = _build_program(build_pet_graph, make_node, CALL_ONCE, CALL_ONCE_CALLS)

    tg = _construct(tmp_path, pet, "1:3@41 NOM RAW 1:12@30|y(101)\n", state_mappings=CALL_ONCE_STATES)

    [dependency] = _dependencies_by_variable(tg)["y"]
    assert dependency.approximate_context is True
    assert dependency.carried_by_loop is None
    assert tg.approximate_dependency_end_statistics == {"ends": 1, "scoped": 0, "location_only": 1}
    assert 41 not in _assignments(tg)


# --- deep callpaths -------------------------------------------------------------------------

# main -> f1 -> f2 -> ... -> f7: seven nested calls, call instruction 100 + k (in CU 1:<10k-9>) calls fk
DEEP_CALLS = 7
DEEP_CHAIN: Sequence[FunctionSpec] = (("1:0", "main", ["1:1", "1:2"], [("1:1", "1:2")]),) + tuple(
    (f"1:{10 * k}", f"f{k}", [f"1:{10 * k + 1}", f"1:{10 * k + 2}"], [(f"1:{10 * k + 1}", f"1:{10 * k + 2}")])
    for k in range(1, DEEP_CALLS + 1)
)
DEEP_CHAIN_CALLS: Sequence[CallSpec] = tuple(
    (f"1:{10 * k - 9}", f"1:{10 * k}", 100 + k) for k in range(1, DEEP_CALLS + 1)
)
# state 2 is main; 10 + 2k the call of fk, 11 + 2k fk itself
DEEP_CHAIN_STATES = "\n".join(
    ["1 1 ROOT", "2 1 main"]
    + [
        line
        for k in range(1, DEEP_CALLS + 1)
        for line in (f"{10 + 2 * k} {2 if k == 1 else 9 + 2 * k} call_{100 + k}", f"{11 + 2 * k} {10 + 2 * k} f{k}")
    ]
    + [""]
)
DEEP_STATE = 11 + 2 * DEEP_CALLS


def test_a_callpath_deeper_than_the_inlining_goes_to_the_standalone_copy_of_a_called_function(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Calls are inlined into main INLINED_CALL_DEPTH levels deep, so the callpath of f7 (seven
    calls) has no context. The suffix fallback attaches the state to the standalone copy of f7,
    marks it approximate and counts it as too deep. (The standalone copies of functions get no
    inlined calls - __inline_function_calls starts at the root, i.e. at main - so the "longest
    suffix" the fallback looks for is always the innermost function alone.)"""
    pet = _build_program(build_pet_graph, make_node, DEEP_CHAIN, DEEP_CHAIN_CALLS)
    record = f"1:72@{DEEP_STATE} NOM RAW 1:72@{DEEP_STATE}|g(100)\n"

    tg = _construct(tmp_path, pet, record, state_mappings=DEEP_CHAIN_STATES)

    [f7] = _assignments(tg)[DEEP_STATE]
    assert isinstance(f7, FunctionContext) and _function_name(tg, f7) == "f7"
    assert [c for c in f7.get_ancestor_contexts() if isinstance(c, (FunctionContext, InlinedFunctionContext))] == []
    assert tg.approximately_assigned_state_ids == {DEEP_STATE}
    assert tg.state_assignment_statistics["too_deep"] == 1
    assert tg.state_assignment_statistics["approximate"] == 1
    assert tg.state_assignment_statistics["assigned"] == 0


# --- side entries of branch regions -----------------------------------------------------------


def _callee(cu_count: int) -> FunctionSpec:
    """foo (1:99) with a chain of cu_count CUs from 1:100 on"""
    cus = [f"1:{100 + k}" for k in range(cu_count)]
    return ("1:99", "foo", cus, list(zip(cus, cus[1:])))


def _side_entry_main(edges: Sequence[Tuple[str, str]]) -> FunctionSpec:
    return ("1:0", "main", ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6"], edges)


# if (a) { if (b) T else U } else { V; T }, T calls foo: T (1:4) is reached from inside the region
# of b (1:2) and from V (1:3) outside of it, whose only successor is T - a side entry that only tail
# duplication resolves
SHARED_TAIL = _side_entry_main(
    [("1:1", "1:2"), ("1:1", "1:3"), ("1:2", "1:4"), ("1:2", "1:5"), ("1:3", "1:4"), ("1:4", "1:6"), ("1:5", "1:6")]
)
SHARED_TAIL_CALLS: Sequence[CallSpec] = (("1:4", "1:99", 7),)
# if (a && b()) T else E, b calls foo: E (1:5) is reached from a (1:1) and from b (1:2)
SHORT_CIRCUIT = _side_entry_main(
    [("1:1", "1:2"), ("1:1", "1:5"), ("1:2", "1:4"), ("1:2", "1:5"), ("1:3", "1:6"), ("1:4", "1:6"), ("1:5", "1:6")]
)
SHORT_CIRCUIT_CALLS: Sequence[CallSpec] = (("1:2", "1:99", 7),)
FOO_STATES = "\n".join(["1 1 ROOT", "11 1 main", "23 11 call_7", "30 23 foo", ""])
FOO_RECORD = "1:100@30 NOM RAW 1:100@30|x(100)\n"


def test_a_shared_tail_is_duplicated_and_its_copies_are_told_apart_from_structural_errors(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Tail duplication splits the shared block T (and the inlined foo it calls), which makes the
    markers nest. The state of foo then matches both copies of foo, which cover the same code and
    are recorded as copies, so the uniqueness check accepts them - and flags them once the record of
    the copies is gone, as it flags any other second context of one callpath."""
    pet = _build_program(build_pet_graph, make_node, (SHARED_TAIL, _callee(2)), SHARED_TAIL_CALLS)

    tg = _construct(tmp_path, pet, FOO_RECORD, state_mappings=FOO_STATES)

    statistics = tg.branch_region_side_entry_statistics
    assert statistics["removed_edges"] == 0 and statistics["unresolved"] == 0
    assert statistics["copied_nodes"] > 0
    assert len(tg.tail_duplication_origins) == statistics["copied_nodes"]
    assert _unbalanced_markers(tg) == []
    assert len(_assignments(tg)[30]) == 2
    assert _unexplained_multi_assignments(tg) == {}

    tg.tail_duplication_origins = {}
    assert list(_unexplained_multi_assignments(tg)) == [30]


def test_a_shared_tail_over_the_duplication_limit_is_left_unresolved(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """A tail of more than _MAX_TAIL_DUPLICATION_NODES nodes (here through the inlined foo) is not
    copied: the side entry is counted as unresolved, and, as documented, the markers of its region
    do not nest. The state of foo keeps its single context."""
    # 90 CUs, i.e. more than the 80 nodes of _MAX_TAIL_DUPLICATION_NODES
    pet = _build_program(build_pet_graph, make_node, (SHARED_TAIL, _callee(90)), SHARED_TAIL_CALLS)

    tg = _construct(tmp_path, pet, FOO_RECORD, state_mappings=FOO_STATES)

    assert tg.branch_region_side_entry_statistics == {"removed_edges": 0, "copied_nodes": 0, "unresolved": 1}
    assert tg.tail_duplication_origins == {}
    assert _unbalanced_markers(tg) != [], "documented consequence of an unresolved side entry"
    assert len(_assignments(tg)[30]) == 1


# callee CUs, whether the short circuit is within the 200 nodes of _MAX_CHAINED_CONDITION_NODES
@pytest.mark.parametrize("callee_cus, within_limit", [(2, True), (250, False)])
def test_a_short_circuit_edge_is_removed_only_within_the_condition_node_limit(
    build_pet_graph: Any, make_node: Any, tmp_path: Path, callee_cus: int, within_limit: bool
) -> None:
    """In `a && b()` the edge a -> else short-circuits b. Within _MAX_CHAINED_CONDITION_NODES nodes
    of b (including the inlined callee) it is removed (b counts as always evaluated); beyond, the
    edge stays and the side entry is resolved by tail duplication instead. Both nest."""
    pet = _build_program(build_pet_graph, make_node, (SHORT_CIRCUIT, _callee(callee_cus)), SHORT_CIRCUIT_CALLS)

    tg = _construct(tmp_path, pet, FOO_RECORD, state_mappings=FOO_STATES)

    statistics = tg.branch_region_side_entry_statistics
    assert statistics["removed_edges"] == (1 if within_limit else 0)
    assert (statistics["copied_nodes"] > 0) == (not within_limit)
    assert statistics["unresolved"] == 0
    assert _unbalanced_markers(tg) == []
    assert len(_assignments(tg)[30]) == 1


def test_the_uniqueness_check_flags_a_second_iteration_with_the_same_code_scope(tmp_path: Path) -> None:
    """The check of test_no_state_is_assigned_to_several_contexts used to compare code scopes,
    which an iteration copied twice shares with its original. Attaching a state to both iteration
    copies of a loop (equal code scopes) has to be flagged."""
    tg = _task_graph_from_profile("loopcall", tmp_path)
    [state] = [s for s, contexts in _assignments(tg).items() if isinstance(contexts[0], IterationContext)][:1]
    [context] = _assignments(tg)[state]
    assert isinstance(context, IterationContext) and isinstance(context.parent_context, LoopParentContext)
    [sibling] = [it for it in _iterations_in_sequence(context.parent_context) if it is not context]
    assert sibling.get_code_scope_set(tg.pet, inclusive=True) == context.get_code_scope_set(tg.pet, inclusive=True)

    sibling.state_ids.append(state)

    assert list(_unexplained_multi_assignments(tg)) == [state]


# --- cut code: early exits and exception unwinding ------------------------------------------


def _record_ends_at_cut_lines(tg: TaskGraph, profile: Path) -> Dict[str, int]:
    """The number of dependency record ends (with or without a state) whose instruction lies on a
    line which only CUs cut from the TaskGraph cover, per cut: their dependencies are lost."""
    alive = {node.pet_node_id for node in tg.graph.nodes if type(node) is TGNode and node.pet_node_id is not None}
    alive_lines = _lines_of_cus(tg, alive)
    lines = _instruction_lines(profile)
    ends = _record_ends(profile)
    result: Dict[str, int] = {}
    for kind, cut in (
        ("early exits", tg.cus_deleted_by_early_exits),
        ("exception unwinding", tg.cus_deleted_by_exception_unwinding),
    ):
        cut_only = _lines_of_cus(tg, set(cut)) - alive_lines
        result[kind] = len([instruction for instruction, _ in ends if lines.get(instruction) in cut_only])
    return result


# program -> record ends at lines only cut code covers, see test_records_at_cut_lines
_RECORD_ENDS_AT_CUT_LINES: Dict[str, Dict[str, int]] = {
    # exit() never runs
    "breakexit": {"early exits": 0, "exception unwinding": 0},
    # exit() never runs, but the `return i;` inside find's loop does (the stack accesses of i and of the
    # return value; since the hybrid-analysis records carry states, one end per state of the returning
    # iteration)
    "exitinloop": {"early exits": 9, "exception unwinding": 0},
    # the catch handler runs once (g_caught, under the state work threw from) and the landing pads
    # copy the exception object (exn.slot, ehselector.slot)
    "trycatch": {"early exits": 0, "exception unwinding": 6},
}


@pytest.mark.parametrize("program", list(_PROFILES_ALL_ASSIGNED))
def test_records_at_cut_lines(program: str, tmp_path: Path) -> None:
    """The measurement behind the decision to keep early exits and exception unwind paths cut
    (0 such record ends on LULESH and miniFE): the record ends at lines covered only by the code
    __fix_loop_structures and __cut_exception_unwind_paths delete. Instruction ids are mapped to
    lines with instructionID_to_lineID_mapping.txt - comparing the ids themselves with lines finds
    nothing, which made an earlier measurement read 0 everywhere."""
    tg = _task_graph_from_profile(program, tmp_path)

    measured = _record_ends_at_cut_lines(tg, tmp_path / program)

    assert measured == _RECORD_ENDS_AT_CUT_LINES.get(program, {"early exits": 0, "exception unwinding": 0})


def test_exception_unwind_paths_are_cut(tmp_path: Path) -> None:
    """trycatch throws inside a loop body and catches it there. The landing pads, the cleanup of the
    destructor and the catch handler are cut (__cut_exception_unwind_paths, by basic block name),
    the regular path through the call stays, and the markers nest."""
    tg = _task_graph_from_profile("trycatch", tmp_path)

    def block(cu: Any) -> str:
        return str(getattr(tg.pet.node_at(cu), "basic_block_id", "") or "")

    deleted = set(tg.cus_deleted_by_exception_unwinding)
    alive = {node.pet_node_id for node in tg.graph.nodes if type(node) is TGNode and node.pet_node_id is not None}
    assert {block(cu) for cu in deleted} >= {"lpad", "ehcleanup", "eh.resume", "catch"}
    assert [cu for cu in alive if block(cu).startswith(TaskGraph._EXCEPTION_UNWIND_BLOCK_PREFIXES)] == []
    assert "1:22" in _lines_of_cus(tg, deleted) - _lines_of_cus(tg, alive), "the catch handler"
    assert "1:20" in _lines_of_cus(tg, alive), "the call of work in the try block"
    assert _unbalanced_markers(tg) == []
    # the destructor call on the unwind path (call 41) is cut with it, so its state is attached to
    # the standalone copy of the destructor; every other state keeps its exact context
    callpaths = _callpaths(tg)
    assert [callpaths[state][-2:] for state in tg.approximately_assigned_state_ids] == [["call_41", "_ZN5GuardD2Ev"]]
    assert tg.state_assignment_statistics["observed"] == tg.state_assignment_statistics["assigned"] + 1


# --- recursion with a loop ------------------------------------------------------------------


def test_a_loop_inside_a_recursive_function_carries_its_dependencies(tmp_path: Path) -> None:
    """recloop: rec(n) runs a loop accumulating g_acc and calls itself. The profiler cuts the
    callpath at the recursive call, so all levels share the states of the first one, which the
    TaskGraph attaches to rec as inlined into main. A dependency of g_acc between two iterations of
    rec's loop is carried by that loop (in the copy of rec on the chain of its end), one between
    two iterations of main's loop by main's loop; none is left without a loop."""
    tg = _task_graph_from_profile("recloop", tmp_path)

    carried_by: Dict[str, int] = {}
    for context in _all_contexts(tg):
        for _, dependency in context.outgoing_dependencies:
            if dependency.var_name != "g_acc" or dependency.sink_line != dependency.source_line:
                continue
            loop = dependency.carried_by_loop
            assert isinstance(loop, LoopParentContext), (dependency.source_line, loop)
            assert loop in context.get_ancestor_contexts()
            function = loop.get_closest_function_ancestor()
            assert isinstance(function, FunctionContext)
            name = _function_name(tg, function)
            carried_by[name] = carried_by.get(name, 0) + 1

    assert set(carried_by) == {"_Z3reci", "main"}
