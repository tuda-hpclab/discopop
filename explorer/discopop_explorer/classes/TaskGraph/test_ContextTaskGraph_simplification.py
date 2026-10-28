# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the simplification of the ContextTaskGraph on small, real graphs.

test_new_task_detector.py stubs the scopes of the detector; here the real ContextTaskGraph is built from a
TaskGraph (assembled by hand with the conftest fixtures) and ``simplify_graph`` is run, to check which tasks
``split_taskable_control_sequence`` registers in the TaskParentContexts:

- two independent work contexts in sequence become one TaskParentContext with two registered tasks
- a data dependency between two successive contexts prevents the split
- of overlapping candidates (A, B), (B, C) the earlier one is split first, in program order
"""

from __future__ import annotations

from typing import Any, List, Sequence, Set, Tuple

import pytest

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeType
from discopop_explorer.classes.ContextTaskGraph.modifications.inflate_nodes.split_taskable_control_sequence import (
    split_taskable_control_sequence,
)
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskEndContext import TaskEndContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.enums.EdgeType import EdgeType


@pytest.fixture(autouse=True)  # type: ignore[misc]
def _fresh_edge_information() -> None:
    # ContextTaskGraph.edge_information is a class level dict shared by all instances; start every test empty
    ContextTaskGraph.edge_information = dict()


def _build_sequence(
    build_pet_graph: Any,
    build_task_graph: Any,
    make_tg_node: Any,
    count: int,
    dependent_pairs: Sequence[Tuple[int, int]] = (),
) -> Tuple[ContextTaskGraph, FunctionContext, List[WorkContext]]:
    """A function context containing ``count`` work contexts in sequence. ``dependent_pairs`` (i, j) lets the
    work context j depend on the work context i (RAW)."""
    pet = build_pet_graph([])
    function = FunctionContext(NodeID("1:0"))
    works = [WorkContext() for _ in range(count)]
    tg_nodes = [make_tg_node(NodeID("1:%d" % (i + 1)), 0, i) for i in range(count)]
    for work, tg_node in zip(works, tg_nodes):
        work.register_parent_context(function)
        function.add_contained_context(work)
        work.add_node(tg_node)
        tg_node.register_created_context(work)
    for first, second in zip(works, works[1:]):
        first.register_successor_context(second)
    for source, sink in dependent_pairs:
        works[source].register_outgoing_dependency(works[sink], Dependency(EdgeType.DATA))
    tg = build_task_graph(pet, tg_nodes)
    for first_node, second_node in zip(tg_nodes, tg_nodes[1:]):
        tg.add_edge(first_node, second_node)
    tg.contexts = [function] + works
    return ContextTaskGraph(tg), function, works


def _control_edges(ctg: ContextTaskGraph) -> Set[Tuple[Context, Context]]:
    return {
        (s, t)
        for s, t in ctg.graph.edges()
        if any(info.type == CTGEdgeType.CONTROL for info in ctg.get_edge_info(s, t))
    }


def test_initial_graph_chains_the_work_contexts(build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any) -> None:
    ctg, function, works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 2)

    # the function contains both contexts, the sequence is ordered (the triangle is removed by the simplification)
    assert _control_edges(ctg) == {(function, works[0]), (function, works[1]), (works[0], works[1])}


def test_independent_successive_contexts_become_one_task_parent(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, function, works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 2)

    tasks = ctg.simplify_graph()

    assert len(tasks) == 1
    assert isinstance(tasks[0], TaskParentContext)
    assert tasks[0].registered_tasks == works
    assert tasks[0].parent_context is function
    assert isinstance(tasks[0].task_end_context, TaskEndContext)
    assert tasks[0].task_end_context.task_parent_context is tasks[0]


def test_task_end_context_points_back_to_its_task_parent(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, _function, _works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 2)
    tasks = ctg.simplify_graph()
    task_end = tasks[0].task_end_context
    assert task_end is not None
    assert task_end.task_parent_context is tasks[0]


def test_dependent_successive_contexts_are_no_tasks(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, _function, _works = _build_sequence(
        build_pet_graph, build_task_graph, make_tg_node, 2, dependent_pairs=[(0, 1)]
    )

    assert ctg.simplify_graph() == []


def test_dependency_in_the_other_direction_is_no_task_either(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, _function, _works = _build_sequence(
        build_pet_graph, build_task_graph, make_tg_node, 2, dependent_pairs=[(1, 0)]
    )

    assert ctg.simplify_graph() == []


def test_split_rewires_the_control_edges_through_task_parent_and_task_end(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, function, works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 2)

    modified, tasks = split_taskable_control_sequence(ctg, [])

    assert modified
    assert len(tasks) == 1
    task_parent = tasks[0]
    task_end = task_parent.task_end_context
    assert task_end is not None
    assert _control_edges(ctg) == {
        (function, task_parent),
        (task_parent, works[0]),
        (task_parent, works[1]),
        (works[0], task_end),
        (works[1], task_end),
    }


def test_split_without_independent_pair_does_not_modify_the_graph(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    ctg, _function, _works = _build_sequence(
        build_pet_graph, build_task_graph, make_tg_node, 2, dependent_pairs=[(0, 1)]
    )
    edges_before = _control_edges(ctg)

    modified, tasks = split_taskable_control_sequence(ctg, [])

    assert not modified
    assert tasks == []
    assert _control_edges(ctg) == edges_before


def test_overlapping_candidates_split_the_earlier_sequence_first(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    """A, B and C are pairwise independent: (A, B) and (B, C) overlap on B. In program order the earlier
    sequence (A, B) is split first, B then belongs to its task parent."""
    ctg, _function, works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 3)

    modified, tasks = split_taskable_control_sequence(ctg, [])

    assert modified
    assert tasks[0].registered_tasks == [works[0], works[1]]
    # C stays behind the task end of the first parent: it is no task of the first parent
    assert works[2] not in tasks[0].registered_tasks


def test_overlapping_candidates_do_not_depend_on_the_graph_insertion_order(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    """The first registered tasks are those of the program order of the work contexts, run after run."""
    results = []
    for _ in range(3):
        ctg, _function, works = _build_sequence(build_pet_graph, build_task_graph, make_tg_node, 3)
        _, tasks = split_taskable_control_sequence(ctg, [])
        ordered: List[Context] = list(works)
        results.append([[ordered.index(t) for t in tp.registered_tasks] for tp in tasks[:1]])
    assert results == [[[0, 1]]] * 3


def test_only_the_independent_pair_of_a_dependent_chain_is_a_task(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    """A -> B is a dependency, B and C are independent: only (B, C) can run in parallel."""
    ctg, _function, works = _build_sequence(
        build_pet_graph, build_task_graph, make_tg_node, 3, dependent_pairs=[(0, 1)]
    )

    tasks = ctg.simplify_graph()

    assert all(works[0] not in tp.registered_tasks for tp in tasks)
    assert tasks[0].registered_tasks == [works[1], works[2]]


def test_independent_prefix_of_a_dependent_chain_is_a_task(
    build_pet_graph: Any, build_task_graph: Any, make_tg_node: Any
) -> None:
    """A and B are independent, B -> C is a dependency: only (A, B) are tasks."""
    ctg, _function, works = _build_sequence(
        build_pet_graph, build_task_graph, make_tg_node, 3, dependent_pairs=[(1, 2)]
    )

    tasks = ctg.simplify_graph()

    assert len(tasks) >= 1
    assert tasks[0].registered_tasks == [works[0], works[1]]
    assert all(works[2] not in tp.registered_tasks for tp in tasks)
