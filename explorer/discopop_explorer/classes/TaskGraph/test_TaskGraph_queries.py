# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the graph and context queries TaskGraph offers its construction passes and the
pattern detectors: edge insertion, successor/predecessor and ancestry lookups, the search for the
closest earlier occurrence of a PET node, the loop header lookup, the lookup of work contexts by
source location and callpath state, and the helpers __break_cycles derives a loop's shape with."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Set, Tuple

import pytest

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.TaskGraph.Branching.TGEndBranchNode import TGEndBranchNode
from discopop_explorer.classes.TaskGraph.Branching.TGEndBranchParentNode import TGEndBranchParentNode
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Functions.TGEndFunctionNode import TGEndFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGEndInlinedFunctionNode import TGEndInlinedFunctionNode
from discopop_explorer.classes.TaskGraph.Functions.TGStartFunctionNode import TGStartFunctionNode
from discopop_explorer.classes.TaskGraph.Loops.TGEndLoopNode import TGEndLoopNode
from discopop_explorer.classes.TaskGraph.Loops.TGEndtIterationNode import TGEndIterationNode
from discopop_explorer.classes.TaskGraph.Loops.TGStartLoopNode import TGStartLoopNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.classes.TaskGraph.Work.TGEndWorkNode import TGEndWorkNode
from discopop_explorer.classes.TaskGraph.Work.TGStartWorkNode import TGStartWorkNode


def _node(pet_node_id: str) -> TGNode:
    return TGNode(NodeID(pet_node_id), 0, 0)


# --- edges --------------------------------------------------------------------------------


def test_add_edge_ignores_missing_endpoints(build_task_graph: Any) -> None:
    """The construction passes pass on optional predecessors unchecked, e.g. the None predecessor
    every function is queued with."""
    node = _node("1:1")
    tg = build_task_graph(None, [node])

    tg.add_edge(None, node)
    tg.add_edge(node, None)

    assert tg.graph.number_of_edges() == 0


def test_add_edge_does_not_duplicate_edges(build_task_graph: Any) -> None:
    """The graph is a MultiDiGraph, so preventing duplicates is up to add_edge."""
    source, target = _node("1:1"), _node("1:2")
    tg = build_task_graph(None, [source, target])

    tg.add_edge(source, target)
    tg.add_edge(source, target)

    assert tg.graph.number_of_edges() == 1


def test_add_edge_adds_unknown_nodes(build_task_graph: Any) -> None:
    source, target = _node("1:1"), _node("1:2")
    tg = build_task_graph(None)

    tg.add_edge(source, target)

    assert set(tg.graph.nodes) == {source, target}


def test_successors_and_predecessors_are_unique_and_ordered(build_task_graph: Any) -> None:
    """Parallel edges, which the passes create by adding edges to tg.graph directly, are reported
    once, in insertion order."""
    source, first, second = _node("1:1"), _node("1:2"), _node("1:3")
    tg = build_task_graph(None, [source, first, second])
    tg.graph.add_edge(source, first)
    tg.graph.add_edge(source, second)
    tg.graph.add_edge(source, first)

    assert tg.get_successors(source) == [first, second]
    assert tg.get_predecessors(first) == [source]
    assert tg.get_successors(first) == []
    assert tg.get_successors(None) == []
    assert tg.get_predecessors(None) == []


def test_ancestry(build_task_graph: Any) -> None:
    a, b, c, unrelated = _node("1:1"), _node("1:2"), _node("1:3"), _node("1:4")
    tg = build_task_graph(None, [a, b, c, unrelated])
    tg.add_edge(a, b)
    tg.add_edge(b, c)

    assert set(tg.get_descendants(a)) == {b, c}
    assert set(tg.get_ancestors(c)) == {a, b}
    assert tg.is_ancestor(c, a), "is_ancestor(src, tgt) asks whether tgt is an ancestor of src"
    assert not tg.is_ancestor(a, c)
    assert not tg.is_ancestor(unrelated, a)


# --- closest predecessors -----------------------------------------------------------------


def test_closest_predecessors_with_matching_pet_node_id_per_path(build_task_graph: Any) -> None:
    """Every path leading back from the start node contributes its closest occurrence of the PET
    node, and the search stops there by default - an earlier copy is shadowed by a later one."""
    #   early -> left  -> late_left  -> start
    #         -> right -> late_right -> start
    early, left, right = _node("1:9"), _node("1:1"), _node("1:2")
    late_left, late_right, start = _node("1:9"), _node("1:9"), _node("1:3")
    tg = build_task_graph(None, [early, left, right, late_left, late_right, start])
    for source, target in [(early, left), (early, right), (left, late_left), (right, late_right)]:
        tg.add_edge(source, target)
    tg.add_edge(late_left, start)
    tg.add_edge(late_right, start)

    assert tg.get_closest_predecessors_with_matching_pet_node_id(start, NodeID("1:9"), set()) == {
        late_left,
        late_right,
    }
    assert tg.get_closest_predecessors_with_matching_pet_node_id(None, NodeID("1:9"), set()) == set()


def test_closest_predecessors_search_further_back_on_request(build_task_graph: Any) -> None:
    early, late, start = _node("1:9"), _node("1:9"), _node("1:3")
    tg = build_task_graph(None, [early, late, start])
    tg.add_edge(early, late)
    tg.add_edge(late, start)

    result = tg.get_closest_predecessors_with_matching_pet_node_id(start, NodeID("1:9"), set(), results_per_path=2)

    assert result == {early, late}


def test_closest_predecessors_skip_disallowed_contexts_and_marker_nodes(build_task_graph: Any) -> None:
    """Only plain TGNodes stand for the PET node itself - a start/end marker carries the PET node
    id of the region it delimits. Occurrences inside a disallowed context are passed over and the
    search continues behind them."""
    early, inside, marker, start = _node("1:9"), _node("1:9"), TGStartWorkNode(NodeID("1:9"), 0, 0), _node("1:3")
    disallowed = Context()
    inside.add_parent_context(disallowed)
    tg = build_task_graph(None, [early, inside, marker, start])
    tg.add_edge(early, inside)
    tg.add_edge(inside, marker)
    tg.add_edge(marker, start)

    assert tg.get_closest_predecessors_with_matching_pet_node_id(start, NodeID("1:9"), {disallowed}) == {early}


# --- context exits ------------------------------------------------------------------------


@pytest.mark.parametrize(  # type: ignore[misc]
    "node_type",
    [
        TGEndFunctionNode,
        TGEndLoopNode,
        TGEndBranchParentNode,
        TGEndBranchNode,
        TGEndWorkNode,
        TGEndInlinedFunctionNode,
    ],
)
def test_is_context_exit_for_end_markers(node_type: Any) -> None:
    assert TaskGraph._TaskGraph__is_context_exit(node_type(NodeID("1:1"), 0, 0))  # type: ignore[attr-defined]


def test_is_context_exit_for_other_nodes() -> None:
    is_context_exit = TaskGraph._TaskGraph__is_context_exit  # type: ignore[attr-defined]

    assert is_context_exit(TGEndIterationNode(NodeID("1:1"), 0, 0, NodeID("1:1")))
    assert not is_context_exit(_node("1:1"))
    assert not is_context_exit(TGStartFunctionNode(NodeID("1:1"), 0, 0))
    assert not is_context_exit(TGStartLoopNode(NodeID("1:1"), 0, 0))
    assert not is_context_exit(TGFunctionNode(NodeID("1:1"), 0, 0))


# --- loop header --------------------------------------------------------------------------


def test_loop_header_is_the_work_context_without_predecessor_in_the_loop(build_task_graph: Any) -> None:
    loop = LoopParentContext(NodeID("1:2"))
    header, iteration = WorkContext(), IterationContext(loop, [1])
    for context in (header, iteration):
        loop.add_contained_context(context)
    header.register_successor_context(iteration)
    tg = build_task_graph(None)

    assert tg.get_loop_header_context(loop) is header


def test_loop_header_is_none_without_an_entry_work_context(build_task_graph: Any) -> None:
    """Only a work context qualifies, and one with a predecessor inside the loop is not the entry."""
    loop = LoopParentContext(NodeID("1:2"))
    iteration, work = IterationContext(loop, [1]), WorkContext()
    for context in (iteration, work):
        loop.add_contained_context(context)
    iteration.register_successor_context(work)
    tg = build_task_graph(None)

    assert tg.get_loop_header_context(loop) is None
    assert tg.get_loop_header_context(LoopParentContext(NodeID("1:3"))) is None


# --- work contexts by location and state --------------------------------------------------


def _work_contexts_at(
    tg: TaskGraph,
    location: str,
    state_id: str,
    location_index: Dict[str, Set[WorkContext]],
    instruction_ids: Dict[str, str] = {},
) -> Set[Context]:
    state_ids_cache: Dict[Context, FrozenSet[int]] = {}
    lookup_cache: Dict[Tuple[str, str], Set[Context]] = {}
    result: Set[Context] = tg._TaskGraph__get_work_contexts_by_location_and_state_id(  # type: ignore[attr-defined]
        tg.pet, location, state_id, instruction_ids, {}, location_index, lookup_cache, state_ids_cache
    )
    return result


def _work_context_in_state(state_id: int) -> WorkContext:
    """A work context inheriting its state from its parent, as the work contexts of a function do."""
    parent, work = Context(), WorkContext()
    parent.state_ids.append(state_id)
    parent.add_contained_context(work)
    work.register_parent_context(parent)
    return work


def test_work_contexts_by_location_without_state(build_task_graph: Any) -> None:
    first, second = WorkContext(), WorkContext()
    index: Dict[str, Set[WorkContext]] = {LineID("1:5"): {first, second}}
    tg = build_task_graph(None)

    assert _work_contexts_at(tg, "1:5", "NO_STATE", index) == {first, second}
    assert _work_contexts_at(tg, "1:6", "NO_STATE", index) == set()
    assert _work_contexts_at(tg, "*", "NO_STATE", index) == set(), "an unknown location matches nothing"


def test_work_contexts_by_instruction_id_are_exact(build_task_graph: Any) -> None:
    """Two contexts share a line; the instruction decides. One that no CU holds falls back to its line, one of
    a deleted CU (in the index without contexts) to nothing."""
    first, second = WorkContext(), WorkContext()
    index: Dict[str, Set[WorkContext]] = {LineID("1:5"): {first, second}, "851": {first}, "852": set()}
    tg = build_task_graph(None)

    assert _work_contexts_at(tg, "851", "NO_STATE", index) == {first}
    assert _work_contexts_at(tg, "852", "NO_STATE", index, {"852": "1:5"}) == set()
    assert _work_contexts_at(tg, "853", "NO_STATE", index, {"853": "1:5"}) == {first, second}


def test_work_contexts_by_location_filter_by_inherited_state(build_task_graph: Any) -> None:
    in_state_3, in_state_4 = _work_context_in_state(3), _work_context_in_state(4)
    index: Dict[str, Set[WorkContext]] = {LineID("1:5"): {in_state_3, in_state_4}}
    tg = build_task_graph(None)

    assert _work_contexts_at(tg, "1:5", "3", index) == {in_state_3}
    assert _work_contexts_at(tg, "1:5", "5", index) == set()


def test_work_contexts_by_location_translate_instruction_ids(build_task_graph: Any) -> None:
    """Locations given as instruction ids are mapped to their source line first."""
    work = WorkContext()
    index: Dict[str, Set[WorkContext]] = {LineID("1:5"): {work}}
    tg = build_task_graph(None)

    assert _work_contexts_at(tg, "1234", "NO_STATE", index, instruction_ids={"1234": "1:5"}) == {work}
    assert _work_contexts_at(tg, "1234", "NO_STATE", index) == set()


# --- loop shape helpers used by __break_cycles --------------------------------------------


def _cycle_graph(build_task_graph: Any) -> Tuple[TaskGraph, Dict[str, TGNode]]:
    """function -> entry -> header -> body -> latch -> header, header -> exit, body -> early_exit"""
    # ids in this order, so that the body's exit sorts before the header's by label
    names = ["function", "entry", "body", "header", "latch", "exit", "early_exit"]
    nodes = {name: _node("1:" + str(i)) for i, name in enumerate(names)}
    tg = build_task_graph(None, list(nodes.values()))
    for source, target in [
        ("function", "entry"),
        ("entry", "header"),
        ("header", "body"),
        ("body", "latch"),
        ("latch", "header"),
        ("header", "exit"),
        ("body", "early_exit"),
    ]:
        tg.add_edge(nodes[source], nodes[target])
    return tg, nodes


def test_cyclic_region_is_the_whole_strongly_connected_component(build_task_graph: Any) -> None:
    tg, nodes = _cycle_graph(build_task_graph)

    region = tg._TaskGraph__get_cyclic_region(nodes["body"])  # type: ignore[attr-defined]

    assert region == {nodes["header"], nodes["body"], nodes["latch"]}
    assert tg._TaskGraph__get_cyclic_region(nodes["exit"]) == {nodes["exit"]}  # type: ignore[attr-defined]


def test_loop_entry_node_is_the_first_cycle_node_reached_from_the_function(build_task_graph: Any) -> None:
    tg, nodes = _cycle_graph(build_task_graph)
    cycle = {nodes["header"], nodes["body"], nodes["latch"]}

    entry = tg._TaskGraph__find_loop_entry_node(nodes["function"], cycle)  # type: ignore[attr-defined]

    assert entry is nodes["header"]
    assert tg._TaskGraph__find_loop_entry_node(nodes["exit"], cycle) is None  # type: ignore[attr-defined]


def test_loop_exit_edge_prefers_the_exit_of_the_entry_node(build_task_graph: Any) -> None:
    """The body's early exit sorts first by label, but the loop test sits at the entry node."""
    tg, nodes = _cycle_graph(build_task_graph)
    cycle = {nodes["header"], nodes["body"], nodes["latch"]}
    find_loop_exit_edge = tg._TaskGraph__find_loop_exit_edge  # type: ignore[attr-defined]

    assert find_loop_exit_edge(nodes["header"], cycle) == (nodes["header"], nodes["exit"])
    # without an exit at the entry node, the first exit in label order is taken
    assert find_loop_exit_edge(nodes["latch"], cycle) == (nodes["body"], nodes["early_exit"])
    assert find_loop_exit_edge(None, cycle) == (None, None)


def test_loop_exit_edge_of_an_endless_loop(build_task_graph: Any) -> None:
    a, b = _node("1:1"), _node("1:2")
    tg = build_task_graph(None, [a, b])
    tg.add_edge(a, b)
    tg.add_edge(b, a)

    assert tg._TaskGraph__find_loop_exit_edge(a, {a, b}) == (None, None)  # type: ignore[attr-defined]


def test_copy_iteration_subgraph_rejects_an_empty_iteration(build_task_graph: Any) -> None:
    tg = build_task_graph(None)
    node = _node("1:1")

    with pytest.raises(ValueError, match="Empty set of iteration nodes"):
        tg._TaskGraph__copy_iteration_subgraph({}, set(), node, node)  # type: ignore[attr-defined]


def test_copy_iteration_subgraph_copies_nodes_and_inner_edges(build_task_graph: Any) -> None:
    """The copy keeps the edges between the iteration's nodes but none leaving its exit, which the
    caller reconnects itself."""
    entry, middle, exit_node, after = _node("1:1"), _node("1:2"), _node("1:3"), _node("1:4")
    tg = build_task_graph(None, [entry, middle, exit_node, after])
    tg.add_edge(entry, middle)
    tg.add_edge(middle, exit_node)
    tg.add_edge(exit_node, after)

    copied, copied_nodes, copied_entry, copied_exit = tg._TaskGraph__copy_iteration_subgraph(  # type: ignore[attr-defined]
        {}, {entry, middle, exit_node}, entry, exit_node
    )

    assert set(copied) == {entry, middle, exit_node}
    assert set(copied_nodes) == set(copied.values())
    assert not set(copied_nodes) & {entry, middle, exit_node}, "the nodes are copies"
    assert [n.pet_node_id for n in (copied_entry, copied_exit)] == ["1:1", "1:3"]
    assert tg.get_successors(copied_entry) == [copied[middle]]
    assert tg.get_successors(copied[middle]) == [copied_exit]
    assert tg.get_successors(copied_exit) == []
