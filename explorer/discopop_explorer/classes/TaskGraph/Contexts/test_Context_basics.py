# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the basic Context API - code scopes, state ids, ancestry, the preceding/successive
context sets and dependency registration - for the Context subclasses, and for the callstack
helpers in Contexts/utils.py. The relation traversals' robustness against cycles and deep nesting
is covered by test_Context.py."""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.TaskGraph.Contexts.BranchContext import BranchContext
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskEndContext import TaskEndContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.Contexts.utils import (
    CallStackElementType,
    convert_callstacks_to_lineIDs,
    get_context_call_stack,
)
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName


def _nest(parent: Context, child: Context) -> None:
    parent.add_contained_context(child)
    child.register_parent_context(parent)


def _chain(contexts: List[Context]) -> None:
    for predecessor, successor in zip(contexts, contexts[1:]):
        predecessor.register_successor_context(successor)


def _tg_node(pet_node_id: str, level: int = 0, position: int = 0) -> TGNode:
    return TGNode(NodeID(pet_node_id), level, position)


# --- code scope ---------------------------------------------------------------------------


def test_code_scope_covers_the_lines_of_the_contained_nodes(make_node: Any, build_pet_graph: Any) -> None:
    pet = build_pet_graph(
        [make_node("1:1", NodeType.CU, start_line=3, end_line=5), make_node("2:1", NodeType.CU, start_line=4)]
    )
    context = Context()
    context.add_node(_tg_node("1:1"))
    context.add_node(_tg_node("2:1"))
    context.add_node(TGNode(None, 0, 0))  # e.g. the root node, which has no PET node

    assert context.get_code_scope(pet) == ["1:3", "1:4", "1:5", "2:4"]
    assert context.get_code_scope_set(pet) == {"1:3", "1:4", "1:5", "2:4"}
    assert context.get_first_pet_node(pet) is pet.node_at(NodeID("1:1"))


def test_instruction_scope_lists_the_instructions_of_the_contained_cus(make_node: Any, build_pet_graph: Any) -> None:
    pet = build_pet_graph(
        [
            make_node("1:1", NodeType.CU, start_line=3, instruction_ids=[7, 8]),
            make_node("1:2", NodeType.CU, start_line=4, instruction_ids=[9, 8]),
            make_node("1:3", NodeType.LOOP, start_line=5),
        ]
    )
    parent, child = Context(), Context()
    _nest(parent, child)
    parent.add_node(_tg_node("1:1"))
    parent.add_node(_tg_node("1:3"))  # no CU: no instructions
    parent.add_node(TGNode(None, 0, 0))
    child.add_node(_tg_node("1:2"))

    assert parent.get_instruction_scope(pet) == [7, 8]
    assert parent.get_instruction_scope(pet, inclusive=True) == [7, 8, 9]


def test_code_scope_cache_is_invalidated_by_add_node(make_node: Any, build_pet_graph: Any) -> None:
    pet = build_pet_graph([make_node("1:1", NodeType.CU, start_line=3), make_node("1:2", NodeType.CU, start_line=4)])
    context = Context()
    context.add_node(_tg_node("1:1"))
    assert context.get_code_scope(pet) == ["1:3"]
    assert context.get_code_scope_set(pet) == {"1:3"}

    context.add_node(_tg_node("1:2"))

    assert context.get_code_scope(pet) == ["1:3", "1:4"]
    assert context.get_code_scope_set(pet) == {"1:3", "1:4"}


def test_inclusive_code_scope_covers_contained_contexts(make_node: Any, build_pet_graph: Any) -> None:
    pet = build_pet_graph([make_node("1:1", NodeType.CU, start_line=3), make_node("1:2", NodeType.CU, start_line=4)])
    parent, child = Context(), Context()
    _nest(parent, child)
    parent.add_node(_tg_node("1:1"))
    child.add_node(_tg_node("1:2"))

    assert parent.get_code_scope(pet) == ["1:3"]
    assert sorted(parent.get_code_scope(pet, inclusive=True)) == ["1:3", "1:4"]
    assert parent.get_code_scope_set(pet, inclusive=True) == {"1:3", "1:4"}
    assert parent.get_first_pet_node(pet) is pet.node_at(NodeID("1:1"))
    assert Context().get_first_pet_node(pet) is None


def test_defined_variables_are_those_defined_within_the_code_scope(make_node: Any, build_pet_graph: Any) -> None:
    cu = make_node(
        "1:1",
        NodeType.CU,
        start_line=3,
        end_line=4,
        local_vars=[Variable("int", VarName("inside"), "1:4"), Variable("int", VarName("outside"), "1:9")],
        global_vars=[Variable("int", VarName("unknown"), "LineNotFound")],
    )
    pet = build_pet_graph([cu])
    context = WorkContext()
    context.add_node(_tg_node("1:1"))

    assert context.get_defined_variables(pet) == [("inside", "1:4")]
    assert context.get_label_with_defined_vars(pet) == "Work inside@1:4\n 1:1\nstate_ids: []"


def test_work_context_contained_calls(make_node: Any, build_pet_graph: Any) -> None:
    """Every line of a calling CU is reported, since a CU does not record which line issues the call."""
    caller = make_node("1:1", NodeType.CU, start_line=3, end_line=4)
    callee = make_node("1:10", NodeType.FUNC, name="foo", start_line=10)
    pet = build_pet_graph([caller, callee], [("1:1", "1:10", EdgeType.CALLSNODE)])
    context = WorkContext()
    context.add_node(_tg_node("1:1"))

    assert context.get_contained_calls(pet) == [("1:10", "1:3"), ("1:10", "1:4")]


def test_plot_bounding_box() -> None:
    context = Context()
    assert context.get_plot_bounding_box() == (0, 0, 0, 0, 0)

    context.add_node(_tg_node("1:1", level=2, position=5))
    context.add_node(_tg_node("1:2", level=4, position=1))

    assert context.get_plot_bounding_box() == (2, 2, 4, 1, 5)


# --- state ids and ancestry ---------------------------------------------------------------


def test_state_ids_are_inherited_from_the_closest_ancestor_with_any() -> None:
    root, function, loop, work = Context(), FunctionContext(NodeID("1:0")), Context(), WorkContext()
    _nest(root, function)
    _nest(function, loop)
    _nest(loop, work)
    root.state_ids.append(1)
    function.state_ids.append(3)

    assert work.get_state_ids() == [3]
    assert loop.get_state_ids() == [3]
    work.state_ids.append(7)
    assert work.get_state_ids() == [7]
    assert Context().get_state_ids() == []


def test_ancestors_are_ordered_from_the_parent_upwards() -> None:
    root, function, work = Context(), FunctionContext(NodeID("1:0")), WorkContext()
    _nest(root, function)
    _nest(function, work)

    assert work.get_ancestor_contexts() == [function, root]
    assert root.get_ancestor_contexts() == []


def test_closest_function_ancestor() -> None:
    outer, inlined, inner, work = (
        FunctionContext(NodeID("1:0")),
        InlinedFunctionContext(7),
        FunctionContext(NodeID("1:10")),
        WorkContext(),
    )
    _nest(outer, inlined)
    _nest(inlined, inner)
    _nest(inner, work)

    assert work.get_closest_function_ancestor() is inner
    assert inlined.get_closest_function_ancestor() is outer
    assert outer.get_closest_function_ancestor() is outer, "a function context is its own closest one"
    assert WorkContext().get_closest_function_ancestor() is None
    assert outer.is_function_context() and not work.is_function_context()


def test_closest_function_ancestor_gives_up_on_a_cyclic_parent_chain(caplog: Any) -> None:
    first, second = Context(), Context()
    first.parent_context, second.parent_context = second, first

    assert first.get_closest_function_ancestor() is None
    assert "Cyclic parent_context chain" in caplog.text


# --- preceding and successive contexts ----------------------------------------------------


def _sequence_with_nested_middle() -> Tuple[Context, Context, Context, Context, Context]:
    """function holds before -> middle -> after; middle holds inner"""
    function, before, middle, after, inner = Context(), Context(), Context(), Context(), Context()
    for context in (before, middle, after):
        _nest(function, context)
    _nest(middle, inner)
    _chain([before, middle, after])
    return function, before, middle, after, inner


def test_preceding_contexts_include_the_predecessors_of_all_ancestors() -> None:
    function, before, middle, after, inner = _sequence_with_nested_middle()
    outer_predecessor = Context()
    outer_predecessor.register_successor_context(function)

    assert inner.get_preceeding_contexts() == {before, outer_predecessor}
    assert after.get_preceeding_contexts() == {before, middle, inner, outer_predecessor}
    assert before.get_preceeding_contexts() == {outer_predecessor}


def test_successive_contexts_include_the_successors_of_all_ancestors() -> None:
    function, before, middle, after, inner = _sequence_with_nested_middle()
    outer_successor = Context()
    function.register_successor_context(outer_successor)

    assert inner.get_successive_contexts() == {after, outer_successor}
    assert before.get_successive_contexts() == {middle, inner, after, outer_successor}
    assert after.get_successive_contexts() == {outer_successor}


# --- dependencies -------------------------------------------------------------------------


def test_dependencies_are_registered_and_deleted_on_both_ends() -> None:
    source, target = Context(), Context()
    dependency = Dependency(EdgeType.DATA)

    source.register_outgoing_dependency(target, dependency)

    assert source.outgoing_dependencies == {(target, dependency)}
    assert target.incoming_dependencies == {(source, dependency)}
    assert source.get_outgoing_dependency_targets() == {target}

    source.delete_outgoing_dependency(target, dependency)

    assert source.outgoing_dependencies == set()
    assert target.incoming_dependencies == set()


# --- context types ------------------------------------------------------------------------


@pytest.mark.parametrize(  # type: ignore[misc]
    "context, label, face_color",
    [
        (Context(), "CTX", "red"),
        (FunctionContext(NodeID("1:0")), "Function 1:0\nstate_ids: []", "lightgrey"),
        (InlinedFunctionContext(7), "InlinedFunc", "blue"),
        (LoopParentContext(NodeID("1:2")), "LoopParent 1:2\nstate_ids: []", "cyan"),
        (BranchingParentContext(), "BranchParent", "yellow"),
        (BranchContext(), "Branch", "orange"),
        (WorkContext(), "Work\nstate_ids: []", "red"),
        (TaskParentContext(), "TaskParent", "yellow"),
        (TaskEndContext(), "TaskEnd", "yellow"),
    ],
)
def test_labels_and_plot_colors(context: Context, label: str, face_color: str) -> None:
    assert context.get_label() == label
    assert context.get_plot_face_color() == face_color
    assert context.get_plot_border_color() in ("b", "r")
    assert context.get_plot_face_alpha() == 0.2


def test_iteration_context_belongs_to_its_loop() -> None:
    loop = LoopParentContext(NodeID("1:2"), loopstate_position=1)
    iteration = IterationContext(loop, [0, 2])

    assert iteration.belongs_to_context is loop
    assert iteration.loopstate_iteration_ids == [0, 2]
    assert iteration.get_label() == "Iteration [0, 2]\nstate_ids: []"
    assert iteration.get_plot_face_color() == "green"
    assert loop.loopstate_position == 1 and loop.loop_variables == []


def test_iteration_context_collects_pet_nodes(make_node: Any) -> None:
    iteration = IterationContext(LoopParentContext(NodeID("1:2")), [1])
    cu = make_node("1:3", NodeType.CU)

    iteration.add_pet_node(cu)
    iteration.add_pet_node(cu)

    assert iteration.contained_pet_nodes == {cu}


def test_work_context_label_lists_the_contained_nodes_and_states() -> None:
    work = WorkContext()
    work.add_node(_tg_node("1:3"))
    work.state_ids.append(5)

    assert work.get_label() == "Work\n 1:3\nstate_ids: [5]"


def test_task_parent_context_registers_its_tasks_and_end() -> None:
    parent, end, task = TaskParentContext(), TaskEndContext(), Context()

    parent.register_task(task)
    parent.set_task_end(end)

    assert parent.registered_tasks == [task]
    assert parent.task_end_context is end
    assert TaskParentContext().registered_tasks == [], "registered tasks are not shared between instances"


def test_task_end_context_records_its_task_parent() -> None:
    """set_task_parent stores the parent in task_parent_context; a new end context has none."""
    parent, end = TaskParentContext(), TaskEndContext()
    assert end.task_parent_context is None

    end.set_task_parent(parent)

    assert end.task_parent_context is parent


# --- callstacks ---------------------------------------------------------------------------


def _loop_in_function() -> Tuple[FunctionContext, LoopParentContext, IterationContext, WorkContext]:
    function, loop = FunctionContext(NodeID("1:0")), LoopParentContext(NodeID("1:2"))
    iteration, work = IterationContext(loop, [1]), WorkContext()
    branch = BranchContext()  # not part of the callstack
    _nest(function, loop)
    _nest(loop, iteration)
    _nest(iteration, branch)
    _nest(branch, work)
    return function, loop, iteration, work


def test_context_call_stack_lists_functions_loops_and_iterations_from_the_outside_in() -> None:
    function, loop, iteration, work = _loop_in_function()

    assert get_context_call_stack(work) == [function, loop, iteration]
    assert get_context_call_stack(function) == [function]
    assert get_context_call_stack(WorkContext()) == []


def test_callstacks_are_converted_to_the_start_lines_of_their_pet_nodes(make_node: Any, build_pet_graph: Any) -> None:
    """An iteration is identified by its loop, as it has no PET node of its own."""
    pet = build_pet_graph(
        [make_node("1:0", NodeType.FUNC, name="main", start_line=1), make_node("1:2", NodeType.LOOP, start_line=5)]
    )
    function, loop, iteration, work = _loop_in_function()

    assert convert_callstacks_to_lineIDs(pet, get_context_call_stack(work)) == [
        (CallStackElementType.FUNCTION, "1:1"),
        (CallStackElementType.LOOP, "1:5"),
        (CallStackElementType.ITERATION, "1:5"),
    ]


def test_callstack_conversion_rejects_other_contexts(make_node: Any, build_pet_graph: Any) -> None:
    with pytest.raises(ValueError, match="Unsupported call stack element type"):
        convert_callstacks_to_lineIDs(build_pet_graph([]), [WorkContext()])


def test_callstack_conversion_skips_elements_without_pet_node(build_pet_graph: Any, caplog: Any) -> None:
    function = FunctionContext(NodeID("1:0"))
    function.parent_function = None  # type: ignore[assignment]

    assert convert_callstacks_to_lineIDs(build_pet_graph([]), [function]) == []
    assert "Empty PETNodeID" in caplog.text
