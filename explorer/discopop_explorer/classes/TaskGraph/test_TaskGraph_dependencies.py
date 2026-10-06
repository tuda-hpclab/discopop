# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests of the dependencies TaskGraph.__insert_data_dependencies_from_files registers: which loop
they are carried by (Dependency.carried_by_pet_loops), for records with and without callpath
states, and what the construction records about code it cut (early exits, exception handlers).

Programs are built by hand as in test_TaskGraph_construction.py: every CU "<file>:<n>" spans line
n unless a test moves it. Records name instructions by id where the instruction order matters;
instructionID_to_lineID_mapping.txt maps them to lines."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import CARRIED_OUTSIDE, Dependency
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.test_TaskGraph_construction import (
    LOOP,
    CallSpec,
    FunctionSpec,
    _build_program,
    _construct,
    _contexts_of_type,
    _work_context_covering,
)
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType


def _all_contexts(tg: TaskGraph) -> List[Context]:
    contexts: List[Context] = tg._TaskGraph__collect_all_contexts()  # type: ignore[attr-defined]
    return contexts


def _dependencies_on(tg: TaskGraph, var_name: str) -> List[Tuple[Context, Context, Dependency]]:
    return [
        (ctx, target, dep)
        for ctx in _all_contexts(tg)
        for target, dep in ctx.outgoing_dependencies
        if dep.var_name == var_name
    ]


def _carried_by(tg: TaskGraph, var_name: str) -> Set[Optional[Tuple[str, ...]]]:
    return {
        None if dep.carried_by_pet_loops is None else tuple(sorted(dep.carried_by_pet_loops))
        for _, _, dep in _dependencies_on(tg, var_name)
    }


def _cu(pet: PEGraphX, node_id: str) -> Any:
    """a node of the PET, to adjust attributes the builder does not take"""
    return pet.node_at(NodeID(node_id))


def _add_loop_node(
    pet: PEGraphX, make_node: Any, loop_id: str, entry_cu: str, start: int, end: int, indices: Sequence[str] = ()
) -> None:
    """the LoopNode of the loop whose entry CU is entry_cu, as Data.xml describes it"""
    loop = make_node(loop_id, NodeType.LOOP, name="loop", start_line=start, end_line=end, loop_indices=list(indices))
    pet.g.add_node(loop.id, data=loop)
    pet.g.add_edge(loop.id, entry_cu, data=Dependency(EdgeType.CHILD))


def _write_instruction_lines(tmp_path: Path, lines: Dict[int, str]) -> None:
    (tmp_path / "instructionID_to_lineID_mapping.txt").write_text(
        "".join(str(instruction) + " " + line + ":1\n" for instruction, line in sorted(lines.items()))
    )


# --- records without callpath states (stack variables) ------------------------------------

# LOOP: 1:1 before the loop, 1:2 the loop header, 1:3 the body, 1:4 after the loop
LOOP_INSTRUCTIONS = {10: "1:1", 20: "1:3", 21: "1:3", 22: "1:3", 23: "1:3"}


def test_a_record_without_states_is_dynamic_and_carried_if_its_earlier_access_comes_later_in_the_code(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`s += x` in a loop body (s a stack variable, recorded without states): the load (20) reads
    the value of the store (21) after it, which can only stem from an earlier iteration. Read as a
    static dependency, it was exempted when s is written in the iteration (lulesh-init.cc:438,
    costDenominator)."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _write_instruction_lines(tmp_path, LOOP_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "20 NOM RAW 21|s(S1) RAW 10|s(S1)\n")

    deps = _dependencies_on(tg, "s")
    assert len(deps) > 0 and all(dep.origin == DepOrigin.DYNAMIC_ANALYSIS for _, _, dep in deps)
    carried = [(source, target, dep) for source, target, dep in deps if dep.carried_by_pet_loops is not None]
    assert {tuple(sorted(dep.carried_by_pet_loops or [])) for _, _, dep in carried} == {("1:2",)}
    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert all(dep.carried_by_loop is loop for _, _, dep in carried)
    bodies = set(_work_context_covering(tg, "1:3"))
    # between the two iteration copies of the body, and within each of them
    assert {(source, target) for source, target, _ in carried} == {(a, b) for a in bodies for b in bodies}
    # the store before the loop reaches the body as an ordinary dependency
    [before] = _work_context_covering(tg, "1:1")
    assert {(source, dep.carried_by_pet_loops) for source, target, dep in deps if target is before} == {
        (body, None) for body in bodies
    }


def test_a_record_without_states_whose_earlier_access_comes_first_stays_within_an_iteration(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`t = x; y = t;` in a loop body: the store (22) comes before the load (23), which is taken as
    a temporary of the iteration. It must not connect the iteration copies."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _write_instruction_lines(tmp_path, LOOP_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "23 NOM RAW 22|t(S2)\n")

    # both accesses are in the same context, so nothing remains to be registered
    assert _dependencies_on(tg, "t") == []


def test_a_record_without_states_or_instruction_ids_is_treated_as_a_static_one(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """an older profiler format names the lines instead of the instructions: the order is unknown"""
    pet = _build_program(build_pet_graph, make_node, LOOP)

    tg = _construct(tmp_path, pet, "1:3 NOM RAW 1:3|s(S1)\n")

    deps = _dependencies_on(tg, "s")
    assert len(deps) == 2
    assert all(dep.origin == DepOrigin.STATIC_ANALYSIS and dep.carried_by_pet_loops is None for _, _, dep in deps)


# main: an outer loop (header 1:2, lines 2-7) around an inner for loop (header 1:4, lines 4-6, index
# j). 1:3 is the outer body before the inner loop: `s2 = 0` (line 3) and the inner loop's
# initialization `j = 0` (line 4, the inner loop's header line). 1:5 is the inner body, 1:6 the
# inner loop's increment (line 4), 1:7 the outer body after the inner loop.
NEST: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7", "1:8"],
        [
            ("1:1", "1:2"),
            ("1:2", "1:3"),
            ("1:3", "1:4"),
            ("1:4", "1:5"),
            ("1:5", "1:6"),
            ("1:6", "1:4"),
            ("1:4", "1:7"),
            ("1:7", "1:2"),
            ("1:2", "1:8"),
        ],
    ),
)
NEST_INSTRUCTIONS = {
    30: "1:4",  # j = 0 (in 1:3)
    40: "1:4",  # j < 8 (in 1:4)
    50: "1:5",  # load j
    60: "1:4",  # ++j (in 1:6)
    70: "1:5",  # load s
    71: "1:5",  # store s
    80: "1:3",  # s2 = 0
    81: "1:5",  # load s2
    82: "1:5",  # store s2
}


def _nest(build_pet_graph: Any, make_node: Any) -> PEGraphX:
    pet = _build_program(build_pet_graph, make_node, NEST)
    for cu_id, start, end in (("1:3", 3, 4), ("1:6", 4, 4)):
        _cu(pet, cu_id).start_line = start
        _cu(pet, cu_id).end_line = end
    _add_loop_node(pet, make_node, "1:20", "1:2", 2, 7)
    _add_loop_node(pet, make_node, "1:21", "1:4", 4, 6, indices=["j"])
    return pet


def test_the_index_of_an_inner_loop_is_carried_by_the_inner_loop_only(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """j is read in the inner loop's condition and body and written by its increment, which comes
    later in the code. The initialization `j = 0` lies on the same line as the increment, outside
    the inner loop: the records name the increment, but its line also matches the initialization.
    Pairing that with the reads would make the outer loop carry j (lulesh-init.cc:162 inside 159)."""
    pet = _nest(build_pet_graph, make_node)
    _write_instruction_lines(tmp_path, NEST_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "40 NOM RAW 60|j(S3) RAW 30|j(S3)\n50 NOM RAW 60|j(S3) RAW 30|j(S3)\n")

    assert _carried_by(tg, "j") - {None} == {("1:4",)}


def test_a_variable_accumulated_across_a_loop_nest_is_carried_by_both_loops(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`for i { for j { s += x; } }`: without states, the iterations of the outer loop the ends lie
    in are unknown, and nothing sets s again in the outer loop"""
    pet = _nest(build_pet_graph, make_node)
    _write_instruction_lines(tmp_path, NEST_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "70 NOM RAW 71|s(S4)\n")

    assert _carried_by(tg, "s") == {("1:2", "1:4")}


def test_a_variable_set_again_before_the_inner_loop_is_carried_by_the_inner_loop_only(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`for i { s2 = 0; for j { s2 += x; } }`"""
    pet = _nest(build_pet_graph, make_node)
    _write_instruction_lines(tmp_path, NEST_INSTRUCTIONS)

    tg = _construct(tmp_path, pet, "81 NOM RAW 82|s2(S5) RAW 80|s2(S5)\n")

    assert _carried_by(tg, "s2") - {None} == {("1:4",)}


# --- records with callpath states ----------------------------------------------------------

# main: a loop (header 1:2) whose body 1:3 calls rec (1:10), which calls itself in 1:11
RECURSION: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:2"), ("1:2", "1:4")]),
    ("1:10", "rec", ["1:11", "1:12"], [("1:11", "1:12")]),
)
RECURSION_CALLS: Sequence[CallSpec] = (("1:3", "1:10", 7), ("1:11", "1:10", 8))
# the profiler cuts the callpath at the recursive call: every recursion level of rec, called from
# main's loop in the iteration with bucket b, is in the state "main_loopstate<b>/call_7/rec"
RECURSION_STATES = "\n".join(
    [
        "1 1 ROOT",
        "11 1 main",
        "20 11 main_loopstate0",
        "21 11 main_loopstate1",
        "22 20 call_7",
        "23 21 call_7",
        "30 22 rec",
        "31 23 rec",
        "",
    ]
)


def test_the_loop_carrying_a_dependency_is_known_at_every_inlined_recursion_level(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """The TaskGraph inlines rec several levels deep, and the deeper copies inherit the state of
    the first one. Counting frames from the end of the callpath found no loop for them
    (CARRIED_OUTSIDE), which made the dependency cross no loop at all."""
    pet = _build_program(build_pet_graph, make_node, RECURSION, RECURSION_CALLS)

    tg = _construct(tmp_path, pet, "1:12@31 NOM RAW 1:12@30|g(100)\n", state_mappings=RECURSION_STATES)

    deps = _dependencies_on(tg, "g")
    assert len(deps) > 1, "the dependency is registered at several recursion levels"
    assert {tuple(sorted(dep.carried_by_pet_loops or [])) for _, _, dep in deps} == {("1:2",)}
    assert all(
        isinstance(dep.carried_by_loop, LoopParentContext) and dep.carried_by_loop.parent_loop == "1:2"
        for _, _, dep in deps
    )
    assert all(dep.carried_by_loop is not CARRIED_OUTSIDE for _, _, dep in deps)


# main's loop (header 1:2) calls foo (1:10), whose loop has the header 1:12 and the body 1:13
LOOP_CALL: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:2"), ("1:2", "1:4")]),
    (
        "1:10",
        "foo",
        ["1:11", "1:12", "1:13", "1:14"],
        [("1:11", "1:12"), ("1:12", "1:13"), ("1:13", "1:12"), ("1:12", "1:14")],
    ),
)
LOOP_CALL_CALLS: Sequence[CallSpec] = (("1:3", "1:10", 7),)


def test_the_loop_carrying_a_dependency_follows_from_the_states_even_without_its_context(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """states deeper than the inlined copies are attached to the standalone copy of a function
    (approximately_assigned_state_ids), outside the loop of the caller which carries them. The
    loop is still named by the states: main's loop at loopstate position 0."""
    pet = _build_program(build_pet_graph, make_node, LOOP_CALL, LOOP_CALL_CALLS)
    states = "\n".join(
        [
            "1 1 ROOT",
            "11 1 main",
            "20 11 main_loopstate0",
            "21 11 main_loopstate1",
            # an unknown call instruction: no inlined copy matches, only the standalone copy of foo
            "22 20 call_99",
            "23 21 call_99",
            "30 22 foo",
            "31 23 foo",
            "32 30 foo_loopstate0",
            "33 31 foo_loopstate0",
            "",
        ]
    )

    tg = _construct(tmp_path, pet, "1:13@33 NOM RAW 1:13@32|g(100)\n", state_mappings=states)

    assert {32, 33} <= tg.approximately_assigned_state_ids
    deps = _dependencies_on(tg, "g")
    assert len(deps) > 0
    assert {tuple(sorted(dep.carried_by_pet_loops or [])) for _, _, dep in deps} == {("1:2",)}
    # the context of the loop is not on the chain of the standalone copy
    assert {dep.carried_by_loop for _, _, dep in deps} == {CARRIED_OUTSIDE}


def test_a_dependency_with_an_end_in_the_loop_header_keeps_its_carrying_loop(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`while (x < n) { x = ...; }`: the condition (1:2) reads the x written by the body (1:3) in the
    previous iteration. The header lies outside the iterations, so no context carries the
    iteration states at its line and the end is mapped approximately; the loop carrying the
    dependency follows from the states nevertheless."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    states = "\n".join(["1 1 ROOT", "11 1 main", "20 11 main_loopstate0", "21 11 main_loopstate1", ""])

    tg = _construct(tmp_path, pet, "1:2@21 NOM RAW 1:3@20|x(100)\n", state_mappings=states)

    deps = _dependencies_on(tg, "x")
    [header] = _work_context_covering(tg, "1:2")
    assert len(deps) > 0 and all(source is header for source, _, _ in deps)
    assert all(dep.approximate_context for _, _, dep in deps)
    assert {tuple(sorted(dep.carried_by_pet_loops or [])) for _, _, dep in deps} == {("1:2",)}
    # the context is looked up from the end mapped exactly
    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert {dep.carried_by_loop for _, _, dep in deps} == {loop}


# --- loop variables ------------------------------------------------------------------------


def test_a_variable_advanced_in_the_body_only_is_no_loop_variable(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """`while (v >= end[i]) i++;` (lulesh-init.cc:446): i flows between the condition and the body,
    but is no induction variable of the loop. Taken as the loop variable, its loop-carried
    dependency was exempted and the loop suggested as parallel."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    _add_loop_node(pet, make_node, "1:20", "1:2", 2, 3, indices=[])

    tg = _construct(tmp_path, pet, static_dependencies="1:2 NOM RAW 1:3|i(100)\n1:3 NOM RAW 1:2|v(101)\n")

    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert loop.loop_variables == []


def test_a_variable_advanced_on_the_header_line_is_a_loop_variable_without_a_loop_node(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """the increment of a for loop is on the line of its header; without a LoopNode (and so without
    its induction variables) that is what identifies the loop variable"""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    # the body is the increment's CU, on the header line
    _cu(pet, "1:3").start_line = 2
    _cu(pet, "1:3").end_line = 2

    tg = _construct(tmp_path, pet, static_dependencies="1:2 NOM RAW 1:2|i(100)\n")

    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert loop.loop_variables == [("i", "100")]


# --- cut code ------------------------------------------------------------------------------

# main: a loop (header 1:2) whose body 1:3 either continues to the latch 1:4 or leaves the loop
# with a break to 1:5, the code after the loop
LOOP_WITH_BREAK: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6"],
        [
            ("1:1", "1:2"),
            ("1:2", "1:3"),
            ("1:3", "1:4"),
            ("1:4", "1:2"),
            ("1:3", "1:5"),
            ("1:2", "1:5"),
            ("1:5", "1:6"),
        ],
    ),
)


def test_a_loop_whose_exit_was_cut_is_recorded_with_the_line_of_the_exit(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    pet = _build_program(build_pet_graph, make_node, LOOP_WITH_BREAK)
    _cu(pet, "1:6").return_instructions_count = 1

    tg = _construct(tmp_path, pet)

    assert tg.loops_with_cut_exits == {"1:2": {"1:3"}}


# main: a loop (header 1:2) whose body 1:3 calls exit() in 1:5, the end of the program
LOOP_WITH_EXIT: Sequence[FunctionSpec] = (
    (
        "1:0",
        "main",
        ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7"],
        [
            ("1:1", "1:2"),
            ("1:2", "1:3"),
            ("1:3", "1:4"),
            ("1:4", "1:2"),
            ("1:3", "1:5"),
            ("1:2", "1:6"),
            ("1:5", "1:7"),
            ("1:6", "1:7"),
        ],
    ),
)


def test_a_call_which_does_not_return_is_no_early_exit(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """`if (v <= 0) exit(1);` in a loop body (LULESH's volume checks): the CU of the call has no
    successors but the function's exit CU, which enforce_single_function_exit_node added"""
    pet = _build_program(build_pet_graph, make_node, LOOP_WITH_EXIT)
    _cu(pet, "1:7").name = "FuncExit_main"
    _cu(pet, "1:6").return_instructions_count = 1

    tg = _construct(tmp_path, pet)

    assert tg.loops_with_cut_exits == {}


def test_records_on_lines_deleted_with_an_early_exit_are_counted(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """1:7 is only reachable through the break out of the loop (it returns), so it is deleted"""
    functions: Sequence[FunctionSpec] = (
        (
            "1:0",
            "main",
            ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7"],
            [
                ("1:1", "1:2"),
                ("1:2", "1:3"),
                ("1:3", "1:4"),
                ("1:4", "1:2"),
                ("1:3", "1:7"),
                ("1:2", "1:5"),
                ("1:5", "1:6"),
                ("1:7", "1:6"),
            ],
        ),
    )
    pet = _build_program(build_pet_graph, make_node, functions)
    _cu(pet, "1:7").return_instructions_count = 1
    states = "1 1 ROOT\n11 1 main\n"

    tg = _construct(
        tmp_path, pet, "1:7@11 NOM RAW 1:1@11|x(100)\n1:5@11 NOM RAW 1:1@11|y(101)\n", state_mappings=states
    )

    assert "1:7" in tg.cus_deleted_by_early_exits
    assert tg.records_on_deleted_lines == 1


def test_a_loop_containing_a_cut_catch_handler_is_recorded(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """a call in the body (1:3) may throw into a landing pad (1:5), whose catch handler (1:6)
    continues the loop. Both are cut, and with them the dependencies of the handler."""
    functions: Sequence[FunctionSpec] = (
        (
            "1:0",
            "main",
            ["1:1", "1:2", "1:3", "1:4", "1:5", "1:6", "1:7"],
            [
                ("1:1", "1:2"),
                ("1:2", "1:3"),
                ("1:3", "1:4"),
                ("1:4", "1:2"),
                ("1:3", "1:5"),
                ("1:5", "1:6"),
                ("1:6", "1:4"),
                ("1:2", "1:7"),
            ],
        ),
    )
    pet = _build_program(build_pet_graph, make_node, functions)
    _cu(pet, "1:5").basic_block_id = "lpad"
    _cu(pet, "1:6").basic_block_id = "catch"
    _add_loop_node(pet, make_node, "1:20", "1:2", 2, 6)
    _add_loop_node(pet, make_node, "1:21", "1:1", 1, 1)  # a loop elsewhere

    tg = _construct(tmp_path, pet)

    assert {"1:5", "1:6"} <= tg.cus_deleted_by_exception_unwinding
    assert tg.loop_nodes_with_cut_exception_handlers == {"1:20"}
