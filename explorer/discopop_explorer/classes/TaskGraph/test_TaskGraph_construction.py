# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests running the complete TaskGraph construction (TaskGraph.__init__) on small hand-built PET
graphs, with the profiler's dependency files written to a temp directory.

test_TaskGraph.py drives single construction passes on shapes that used to break them. The tests
here instead pin what the passes produce together: which contexts a function, a work region, a
loop, a branch and an inlined call end up as, how those contexts are nested and chained, which
callpath states they are assigned, and which data dependencies end up between them.

Every CU "<file>:<n>" built here spans source line n of its file, so a location in a dependency
file names the CU of the same number. Every function ends in an exit CU without successors, as
PEGraphX.enforce_single_function_exit_node guarantees for real input - a function's
TGEndFunctionNode is only created on reaching a CU without successors through a predecessor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence, Set, Tuple, Type, TypeVar

import networkx as nx
import pytest

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Branching.TGEndBranchParentNode import TGEndBranchParentNode
from discopop_explorer.classes.TaskGraph.Branching.TGStartBranchParentNode import TGStartBranchParentNode
from discopop_explorer.classes.TaskGraph.Contexts.BranchContext import BranchContext
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Functions.TGEndFunctionNode import TGEndFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGStartInlinedFunctionNode import TGStartInlinedFunctionNode
from discopop_explorer.classes.TaskGraph.RootNode import RootNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

C = TypeVar("C", bound=Context)

# (function id, function name, [CU ids], [(source CU, target CU)] successor edges)
FunctionSpec = Tuple[str, str, Sequence[str], Sequence[Tuple[str, str]]]
# (calling CU, called function, call instruction id)
CallSpec = Tuple[str, str, int]


def _line_of(node_id: str) -> int:
    return int(node_id.split(":")[1])


def _build_program(
    build_pet_graph: Any, make_node: Any, functions: Sequence[FunctionSpec], calls: Sequence[CallSpec] = ()
) -> PEGraphX:
    """A PET graph of the given functions, the first of which is called "main" by convention, since
    pet.main is where __visit_pet starts."""
    nodes = []
    edges: List[Tuple[str, str, EdgeType]] = []
    cu_nodes = {}
    for function_id, name, cu_ids, successors in functions:
        lines = [_line_of(cu_id) for cu_id in cu_ids]
        nodes.append(make_node(function_id, NodeType.FUNC, name=name, start_line=min(lines), end_line=max(lines)))
        for cu_id in cu_ids:
            cu_nodes[cu_id] = make_node(cu_id, NodeType.CU, name="cu", start_line=_line_of(cu_id))
            nodes.append(cu_nodes[cu_id])
            edges.append((function_id, cu_id, EdgeType.CHILD))
        edges += [(source, target, EdgeType.SUCCESSOR) for source, target in successors]
    for caller, callee, call_instruction_id in calls:
        # instance attribute: Node.node_calls is a class-level default shared by all nodes
        cu_nodes[caller].node_calls = [{"cuid": callee, "callInstId": str(call_instruction_id)}]
        edges.append((caller, callee, EdgeType.CALLSNODE))
    pet: PEGraphX = build_pet_graph(nodes, edges)
    return pet


def _construct(
    tmp_path: Path,
    pet: PEGraphX,
    dynamic_dependencies: str = "",
    static_dependencies: Optional[str] = None,
    state_mappings: Optional[str] = None,
) -> TaskGraph:
    dynamic_file = tmp_path / "dynamic_dependencies.txt"
    dynamic_file.write_text(dynamic_dependencies)
    static_file = None
    if static_dependencies is not None:
        static_file = tmp_path / "static_dependencies.txt"
        static_file.write_text(static_dependencies)
    if state_mappings is not None:
        (tmp_path / "stateID_to_callpath_mapping.txt").write_text(state_mappings)
    return TaskGraph(pet, str(dynamic_file), None if static_file is None else str(static_file))


def _contexts_of_type(tg: TaskGraph, context_type: Type[C]) -> List[C]:
    # type() rather than isinstance(): the context classes are not meant to be specialized further,
    # and Context itself would otherwise match everything
    contexts = [c for c in tg._TaskGraph__collect_all_contexts() if type(c) is context_type]  # type: ignore[attr-defined]
    return sorted(contexts, key=lambda c: c.creation_index)


def _covered_cus(context: Context) -> Set[str]:
    return {str(node.pet_node_id) for node in context.contained_nodes if type(node).__name__ == "TGNode"}


def _work_context_covering(tg: TaskGraph, *cu_ids: str) -> List[WorkContext]:
    return [c for c in _contexts_of_type(tg, WorkContext) if _covered_cus(c) == set(cu_ids)]


def _sequence(first: Optional[Context]) -> List[Context]:
    result = []
    while first is not None:
        result.append(first)
        first = first.successor
    return result


def _dependencies(source: Context, target: Context) -> Set[Tuple[Optional[DepType], Optional[str], Any]]:
    return {(dep.dtype, dep.var_name, dep.origin) for t, dep in source.outgoing_dependencies if t is target}


# --- straight-line code -------------------------------------------------------------------

STRAIGHT_LINE: Sequence[FunctionSpec] = (("1:0", "main", ["1:1", "1:2", "1:3"], [("1:1", "1:2"), ("1:2", "1:3")]),)


def test_construction_rejects_a_missing_dynamic_dependency_file(build_pet_graph: Any, make_node: Any) -> None:
    """The state ids, and with them every dynamic dependency, come from the dynamic dependency file,
    so there is nothing sensible to build without one."""
    pet = _build_program(build_pet_graph, make_node, STRAIGHT_LINE)

    with pytest.raises(ValueError, match="Invalid Path"):
        TaskGraph(pet, None, None)


def test_construction_of_straight_line_code(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """A function without control flow is a function context holding a single work region: the
    CUs of a successor chain are merged into one work context."""
    pet = _build_program(build_pet_graph, make_node, STRAIGHT_LINE)

    tg = _construct(tmp_path, pet)

    assert isinstance(tg.root, RootNode)
    assert nx.is_directed_acyclic_graph(tg.graph)
    reachable = nx.descendants(tg.graph, tg.root)
    assert all(node in reachable for node in tg.graph.nodes if node is not tg.root)

    [function] = _contexts_of_type(tg, FunctionContext)
    assert function.parent_function == "1:0"
    [work] = _contexts_of_type(tg, WorkContext)
    assert _covered_cus(work) == {"1:1", "1:2", "1:3"}
    assert work.parent_context is function
    assert function.contained_contexts == {work}
    assert work.get_closest_function_ancestor() is function


def test_construction_does_not_share_state_between_task_graphs(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """The pet-node-id lookup maps are class attributes with per-instance shadows. A second
    TaskGraph built from the same PET graph must not be wired up to the first one's nodes."""
    pet = _build_program(build_pet_graph, make_node, STRAIGHT_LINE)

    first = _construct(tmp_path, pet)
    second = _construct(tmp_path, pet)

    assert set(first.graph.nodes).isdisjoint(second.graph.nodes)
    assert first.TGNode_pet_node_id_to_tg_node is not second.TGNode_pet_node_id_to_tg_node
    assert first.contexts is not second.contexts
    assert TaskGraph.TGNode_pet_node_id_to_tg_node == {}, "the class-level default must stay untouched"


# --- loops --------------------------------------------------------------------------------

# main: for (...) { body }
#   1:1 -> 1:2 (header) -> 1:3 (body) -> 1:2 (back edge)
#          1:2 -> 1:4 (exit)
LOOP: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:2", "1:3"), ("1:3", "1:2"), ("1:2", "1:4")]),
)


def test_construction_of_a_loop(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """A loop becomes a LoopParentContext holding the loop header and two unrolled iterations -
    one standing for the profiler's iteration id 1, one for the ids 0 and 2 - each with its own
    copy of the loop body. The loop sits between the code before and after it."""
    pet = _build_program(build_pet_graph, make_node, LOOP)

    tg = _construct(tmp_path, pet)

    assert nx.is_directed_acyclic_graph(tg.graph), "the back edge has to be broken"
    [function] = _contexts_of_type(tg, FunctionContext)
    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert loop.parent_loop == "1:2"
    assert loop.parent_context is function
    assert loop.loopstate_position == 0, "an outermost loop is the first entry of the loopstate"

    iterations = _contexts_of_type(tg, IterationContext)
    assert sorted(it.loopstate_iteration_ids for it in iterations) == [[0, 2], [1]]
    assert all(it.parent_context is loop and it.belongs_to_context is loop for it in iterations)

    [header] = _work_context_covering(tg, "1:2")
    assert header.parent_context is loop
    assert tg.get_loop_header_context(loop) is header
    # the header is followed by the iteration standing for id 1, which is followed by the other one
    assert [type(c) for c in _sequence(header)] == [WorkContext, IterationContext, IterationContext]
    assert [c.loopstate_iteration_ids for c in _sequence(header)[1:]] == [[1], [0, 2]]  # type: ignore[attr-defined]

    bodies = _work_context_covering(tg, "1:3")
    assert len(bodies) == 2, "every iteration carries its own copy of the loop body"
    assert {body.parent_context for body in bodies} == set(iterations)

    [before] = _work_context_covering(tg, "1:1")
    [after] = _work_context_covering(tg, "1:4")
    assert _sequence(before) == [before, loop, after]


def test_loop_variables_and_their_cross_iteration_dependencies(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """A variable flowing between the loop header and the loop body is the loop variable if the
    loop advances it: it is an induction variable of the loop's LoopNode. The statically derived
    dependencies on it between two iterations are an artifact of the unrolling and get removed,
    while those on other variables stay."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    # the LoopNode of the loop, which PEGraphX.calculateLoopMetadata found i to be the index of
    loop_node = make_node("1:20", NodeType.LOOP, name="loop", start_line=2, end_line=3, loop_indices=["i"])
    pet.g.add_node(loop_node.id, data=loop_node)
    pet.g.add_edge(loop_node.id, "1:2", data=Dependency(EdgeType.CHILD))
    static_dependencies = "\n".join(
        [
            "1:3 NOM RAW 1:2|i(100)",  # body reads i written by the header
            "1:3 NOM RAW 1:3|i(100) RAW 1:3|s(300)",  # body reads i and s written by the body
            "1:4 NOM RAW 1:3|s(300)",  # code after the loop reads s
            "",
        ]
    )

    tg = _construct(tmp_path, pet, static_dependencies=static_dependencies)

    [loop] = _contexts_of_type(tg, LoopParentContext)
    assert loop.loop_variables == [("i", "100")]

    [header] = _work_context_covering(tg, "1:2")
    first_body, second_body = _work_context_covering(tg, "1:3")
    [after] = _work_context_covering(tg, "1:4")
    static = DepOrigin.STATIC_ANALYSIS
    for body in (first_body, second_body):
        assert _dependencies(body, header) == {(DepType.RAW, "i", static)}
        assert _dependencies(after, body) == {(DepType.RAW, "s", static)}
    assert _dependencies(first_body, second_body) == {(DepType.RAW, "s", static)}
    assert _dependencies(second_body, first_body) == {(DepType.RAW, "s", static)}


# --- branches -----------------------------------------------------------------------------

# main: if (...) { then } else { else }
#   1:1 -> 1:2 / 1:3 -> 1:4
BRANCH: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3", "1:4"], [("1:1", "1:2"), ("1:1", "1:3"), ("1:2", "1:4"), ("1:3", "1:4")]),
)


def test_construction_of_a_branch(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """A branch becomes a BranchingParentContext with one BranchContext per arm, placed between
    the branch point and the merge point."""
    pet = _build_program(build_pet_graph, make_node, BRANCH)

    tg = _construct(tmp_path, pet)

    assert len([n for n in tg.graph.nodes if isinstance(n, TGStartBranchParentNode)]) == 1
    assert len([n for n in tg.graph.nodes if isinstance(n, TGEndBranchParentNode)]) == 1
    [function] = _contexts_of_type(tg, FunctionContext)
    [branching] = _contexts_of_type(tg, BranchingParentContext)
    assert branching.parent_context is function
    arms = _contexts_of_type(tg, BranchContext)
    assert len(arms) == 2
    assert all(arm.parent_context is branching for arm in arms)
    assert branching.contained_contexts == set(arms)
    assert sorted(cu for arm in arms for c in arm.contained_contexts for cu in _covered_cus(c)) == ["1:2", "1:3"]
    assert all(len(arm.contained_contexts) == 1 for arm in arms), "each arm holds the work region of one CU"

    [branch_point] = _work_context_covering(tg, "1:1")
    [merge_point] = _work_context_covering(tg, "1:4")
    assert _sequence(branch_point) == [branch_point, branching, merge_point]


# --- function calls and callpath states ---------------------------------------------------

# main: 1:1 -> 1:2 (calls foo, call instruction 7) -> 1:3
# foo:  1:11 -> 1:12
CALL: Sequence[FunctionSpec] = (
    ("1:0", "main", ["1:1", "1:2", "1:3"], [("1:1", "1:2"), ("1:2", "1:3")]),
    ("1:10", "foo", ["1:11", "1:12"], [("1:11", "1:12")]),
)
CALLS: Sequence[CallSpec] = (("1:2", "1:10", 7),)
# state 3 is main itself, state 4 is foo as called by call instruction 7 from main
CALL_STATE_MAPPINGS = "\n".join(
    ["# Format: <NodeID> <ParentID> <Label>", "1 1 ROOT", "3 1 main", "2 3 call_7", "4 2 foo", ""]
)


def _inlined_foo(tg: TaskGraph) -> FunctionContext:
    [call] = _contexts_of_type(tg, InlinedFunctionContext)
    [inlined] = call.contained_contexts
    assert isinstance(inlined, FunctionContext)
    return inlined


def test_construction_inlines_called_functions(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """A call is replaced by a copy of the called function, wrapped in an InlinedFunctionContext
    which remembers the call instruction (the profiler's "call_<id>" callpath entries refer to
    it). A calling CU always ends a work region, so the call follows it in the sequence."""
    pet = _build_program(build_pet_graph, make_node, CALL, CALLS)

    tg = _construct(tmp_path, pet)

    [start_inlined] = [n for n in tg.graph.nodes if isinstance(n, TGStartInlinedFunctionNode)]
    assert start_inlined.call_instruction_id == 7
    [call] = _contexts_of_type(tg, InlinedFunctionContext)
    assert call.call_instruction_id == 7

    [caller] = _work_context_covering(tg, "1:2")
    assert call.parent_context is caller, "the call is nested into the work region that issues it"
    assert _inlined_foo(tg).parent_function == "1:10"

    # foo is also kept as a function on its own, next to its inlined copy in main
    foo_contexts = [c for c in _contexts_of_type(tg, FunctionContext) if c.parent_function == "1:10"]
    assert len(foo_contexts) == 2
    assert len([n for n in tg.graph.nodes if isinstance(n, TGEndFunctionNode) and n.pet_node_id == "1:10"]) == 2

    [main] = [c for c in _contexts_of_type(tg, FunctionContext) if c.parent_function == "1:0"]
    [before, after] = _work_context_covering(tg, "1:1") + _work_context_covering(tg, "1:3")
    assert _sequence(before) == [before, caller, after]
    assert {before.parent_context, caller.parent_context, after.parent_context} == {main}


def test_state_ids_are_assigned_along_the_callpath(build_pet_graph: Any, make_node: Any, tmp_path: Path) -> None:
    """A state is assigned to the context its callpath leads to: "main" to main's function context,
    "main/call_7/foo" to the copy of foo inlined at call instruction 7 - not to foo on its own.
    Contexts without a state of their own inherit the one of their closest ancestor."""
    pet = _build_program(build_pet_graph, make_node, CALL, CALLS)
    # the reader only resolves the states a dependency was observed in
    dynamic_dependencies = "1:3@3 NOM RAW 1:11@4|x(100)\n"

    tg = _construct(tmp_path, pet, dynamic_dependencies, state_mappings=CALL_STATE_MAPPINGS)

    [main] = [c for c in _contexts_of_type(tg, FunctionContext) if c.parent_function == "1:0"]
    inlined_foo = _inlined_foo(tg)
    [standalone_foo] = [
        c for c in _contexts_of_type(tg, FunctionContext) if c.parent_function == "1:10" and c is not inlined_foo
    ]
    assert main.state_ids == [3]
    assert inlined_foo.state_ids == [4]
    assert standalone_foo.state_ids == []

    [caller] = _work_context_covering(tg, "1:2")
    assert caller.state_ids == [] and caller.get_state_ids() == [3]


def test_dynamic_dependencies_connect_the_contexts_of_their_states(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Dynamic dependencies may cross function boundaries, and the state ids pick the context they
    were observed in among those covering the same source line."""
    pet = _build_program(build_pet_graph, make_node, CALL, CALLS)
    dynamic_dependencies = "\n".join(
        [
            "1:3@3 NOM RAW 1:11@4|x(100)",  # main reads x written in foo, called from main
            "1:3@3 NOM RAW 1:1@3|y(200)",  # within main
            "1:3@3 NOM WAW 1:1@3|y(200)",  # no data flow, ignored
            "",
        ]
    )

    tg = _construct(tmp_path, pet, dynamic_dependencies, state_mappings=CALL_STATE_MAPPINGS)

    [before] = _work_context_covering(tg, "1:1")
    [after] = _work_context_covering(tg, "1:3")
    [inlined_body] = [c for c in _work_context_covering(tg, "1:11", "1:12") if c.parent_context is _inlined_foo(tg)]
    [standalone_body] = [c for c in _work_context_covering(tg, "1:11", "1:12") if c is not inlined_body]
    dynamic = DepOrigin.DYNAMIC_ANALYSIS
    assert _dependencies(after, inlined_body) == {(DepType.RAW, "x", dynamic)}
    assert _dependencies(after, standalone_body) == set(), "the standalone copy of foo was not observed in state 4"
    assert _dependencies(after, before) == {(DepType.RAW, "y", dynamic)}


def test_static_dependencies_do_not_cross_function_boundaries(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """Static dependencies carry no state, so they could stem from any call of a function. They
    are only kept between contexts of the same function."""
    pet = _build_program(build_pet_graph, make_node, CALL, CALLS)
    static_dependencies = "1:3 NOM RAW 1:11|x(100) RAW 1:1|y(200)\n"

    tg = _construct(tmp_path, pet, static_dependencies=static_dependencies)

    [before] = _work_context_covering(tg, "1:1")
    [after] = _work_context_covering(tg, "1:3")
    assert _dependencies(after, before) == {(DepType.RAW, "y", DepOrigin.STATIC_ANALYSIS)}
    for foo_body in _work_context_covering(tg, "1:11", "1:12"):
        assert _dependencies(after, foo_body) == set()


def test_loop_iteration_states_are_assigned_to_their_iteration_context(
    build_pet_graph: Any, make_node: Any, tmp_path: Path
) -> None:
    """A "<function>_loopstate<digits>" callpath entry carries one iteration id per enclosing loop,
    at the loop's loopstate position. Iteration id 1 is the iteration context standing for it, 0
    and 2 are the other one."""
    pet = _build_program(build_pet_graph, make_node, LOOP)
    state_mappings = "\n".join(
        ["1 1 ROOT", "11 1 main", "20 11 main_loopstate0", "21 11 main_loopstate1", "22 11 main_loopstate2", ""]
    )
    dynamic_dependencies = "1:3@20 NOM RAW 1:3@21|i(100) RAW 1:3@22|i(100)\n"

    tg = _construct(tmp_path, pet, dynamic_dependencies, state_mappings=state_mappings)

    state_ids_by_iteration = {
        tuple(it.loopstate_iteration_ids): sorted(it.state_ids) for it in _contexts_of_type(tg, IterationContext)
    }
    assert state_ids_by_iteration == {(1,): [21], (0, 2): [20, 22]}
