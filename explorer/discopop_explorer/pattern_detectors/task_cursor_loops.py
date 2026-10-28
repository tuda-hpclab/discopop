# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Loops that create one task per iteration although they are no do-all loops: the loop walks a data structure with a
cursor, ``while (v) { f(v); v = v->next; }`` (omp-tasks/health: ``task`` on the recursive call, the cursor is
firstprivate).

The iterations depend on each other through the cursor only, a RAW from its update to the next iteration's reads, so
the do-all detection rejects the loop, correctly: the update is sequential. As a loop of tasks the update is no
problem, it stays in the thread that creates the tasks, and the cursor reaches each task as a copy of its value. A loop
qualifies if every dependence its iterations carry is such a cursor dependence, i.e. both its ends are in the code of
the loop itself, not in a function it calls, and the update is not part of a call. The tasks are the lines of the
loop without the header and the updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.new_do_all_detector import (
    dependencies_by_carried_loop,
    loop_node_of,
    structural_rejection,
)
from discopop_explorer.pattern_detectors.task_dataflow import classify_variable

logger = logging.getLogger("Explorer").getChild("Tasking")


class LoopTaskSource(Protocol):
    """What the loop tasking needs to know of a loop: a do-all pattern provides it, and so does a ``CursorLoop``."""

    @property
    def node_id(self) -> str: ...

    @property
    def instruction_ids(self) -> List[int]: ...

    @property
    def shared(self) -> List[Variable]: ...

    @property
    def private(self) -> List[Variable]: ...

    @property
    def first_private(self) -> List[Variable]: ...

    @property
    def reduction(self) -> List[Variable]: ...

    @property
    def last_private(self) -> List[Variable]: ...


@dataclass
class CursorLoop:
    """A loop whose iterations are tasks and whose only carried dependences are those of its cursor variables.
    ``instruction_ids`` are those of the loop without the updates of the cursors."""

    node_id: str
    instruction_ids: List[int]
    shared: List[Variable] = field(default_factory=list)
    private: List[Variable] = field(default_factory=list)
    first_private: List[Variable] = field(default_factory=list)
    reduction: List[Variable] = field(default_factory=list)
    last_private: List[Variable] = field(default_factory=list)
    cursors: List[str] = field(default_factory=list)
    update_lines: List[str] = field(default_factory=list)


def _line_number(line: str) -> int:
    return int(line.split(":")[1])


def _crossing_dependencies(
    iterations: List[IterationContext],
) -> List[Tuple[Context, Context, Dependency]]:
    """The dependences between two different iterations of one loop whose carrying loop is not known (see
    ``Dependency.carried_by_pet_loops``), by the iteration contexts of their ends. The same scan as the do-all
    detection makes."""
    iteration_of: Dict[Context, int] = dict()
    shared_by_iterations: Set[Context] = set()
    subtrees: List[Set[Context]] = []
    for index, iteration in enumerate(iterations):
        subtree = iteration.get_contained_contexts(inclusive=True)
        subtrees.append(subtree)
        for ctx in subtree:
            if iteration_of.setdefault(ctx, index) != index:
                shared_by_iterations.add(ctx)
    found: List[Tuple[Context, Context, Dependency]] = []
    for index, subtree in enumerate(subtrees):
        for ctx in sorted(subtree, key=lambda c: c.creation_index):
            for target, dependency in sorted(ctx.outgoing_dependencies, key=lambda d: (d[0].creation_index, id(d[1]))):
                if dependency.carried_by_pet_loops is not None:
                    continue
                if target in shared_by_iterations or iteration_of.get(target, index) != index:
                    found.append((ctx, target, dependency))
    return found


def _is_update_of_the_loop(
    source: Context, target: Context, dependency: Dependency, functions: Set[Optional[Context]], loop: LoopNode
) -> bool:
    """Whether the dependence is one of a cursor: a RAW with both ends in the function that holds the loop (not in a
    function called by it, the code of recursive callees has the lines of the loop as well) and its earlier end, the
    update, in the lines of the loop."""
    if dependency.dtype != DepType.RAW or dependency.var_name is None or dependency.source_line is None:
        return False
    if (
        source.get_closest_function_ancestor() not in functions
        or target.get_closest_function_ancestor() not in functions
    ):
        return False
    file_id, line = str(dependency.source_line).split(":")
    return int(file_id) == loop.file_id and loop.start_line <= int(line) <= loop.end_line


def _call_lines(pet: PEGraphX, loop_instructions: Sequence[int]) -> Set[str]:
    """The lines of the calls made by the instructions of a loop."""
    instruction_ids = set(loop_instructions)
    calls: List[int] = []
    for cu in all_nodes(pet, CUNode):
        for call in cu.node_calls:
            if call.get("callInstId") is not None and int(call["callInstId"]) in instruction_ids:
                calls.append(int(call["callInstId"]))
    return {str(line) for line in pet.get_line_ids_of_instructions(calls)}


def _sharing(
    pet: PEGraphX, loop_context: Context, loop: LoopNode, cursors: Set[str], task_lines: Set[str]
) -> Tuple[List[str], List[str], List[str]]:
    """``(shared, private, first_private)`` of the variables the loop accesses; cursors are firstprivate."""
    accessed: Dict[str, Tuple[bool, bool, str]] = {}
    for tg_node in loop_context.get_contained_nodes(inclusive=True):
        node = tg_node.get_pet_node(pet)
        for variable in list(getattr(node, "local_vars", [])) + list(getattr(node, "global_vars", [])):
            read, written, _ = accessed.get(variable.name, (False, False, variable.defLine))
            accessed[variable.name] = (
                read or "R" in variable.accessMode,
                written or "W" in variable.accessMode,
                variable.defLine,
            )
    shared: List[str] = []
    private: List[str] = []
    first_private: List[str] = []
    for name, (read, written, def_line) in sorted(accessed.items()):
        if name in cursors:
            first_private.append(name)
            continue
        global_variable = def_line == "GlobalVar"
        declared = global_variable is False and ":" in def_line and def_line in task_lines
        kind = classify_variable(read, written, declared, global_variable, False, False)
        if kind == "shared":
            shared.append(name)
        elif kind == "private":
            private.append(name)
        elif kind == "first_private":
            first_private.append(name)
    return shared, private, first_private


def find_cursor_loops(tg: TaskGraph, claimed_loops: Set[str]) -> List[CursorLoop]:
    """The loops that are tasks per iteration with their cursors (see the module description). ``claimed_loops`` are
    the loops that are patterns of their own (do-all, reduction)."""
    pet = tg.pet
    copies: Dict[NodeID, List[LoopParentContext]] = dict()
    for tg_node in tg.graph.nodes():
        loop_id = tg_node.pet_node_id
        if isinstance(tg_node.created_context, LoopParentContext) and loop_id is not None:
            copies.setdefault(loop_id, []).append(tg_node.created_context)
    carried_index = dependencies_by_carried_loop(tg)
    profile_has_loop_data = any(getattr(n, "loop_data", None) is not None for n in all_nodes(pet, LoopNode))

    result: List[CursorLoop] = []
    for pet_node_id in sorted(copies, key=str):
        if pet_node_id in claimed_loops:
            continue
        loop = loop_node_of(pet, pet_node_id)
        if loop is None or structural_rejection(tg, pet_node_id, loop, profile_has_loop_data) is not None:
            continue
        contexts = sorted(copies[pet_node_id], key=lambda ctx: ctx.creation_index)
        iterations_of = {
            ctx: sorted(
                (c for c in ctx.get_contained_contexts() if isinstance(c, IterationContext)),
                key=lambda c: c.creation_index,
            )
            for ctx in contexts
        }
        executed = [ctx for ctx in contexts if len(iterations_of[ctx]) >= 2]
        if len(executed) == 0:
            continue
        functions = {ctx.get_closest_function_ancestor() for ctx in contexts}
        carried: List[Tuple[Context, Context, Dependency]] = list(carried_index.get(pet_node_id, []))
        for ctx in executed:
            carried += _crossing_dependencies(iterations_of[ctx])
        # WAR dependences between iterations are no obstacle, a variable is privatized
        carried = [c for c in carried if not (c[2].dtype == DepType.WAR)]
        if len(carried) == 0 or not all(_is_update_of_the_loop(s, t, d, functions, loop) for s, t, d in carried):
            continue
        cursor_dependences = [d for _, _, d in carried]
        update_lines = {str(d.source_line) for d in cursor_dependences}
        loop_context = executed[0]
        instruction_ids = loop_context.get_instruction_scope(pet, inclusive=True)
        calls = _call_lines(pet, instruction_ids)
        if update_lines & calls:
            # the update is part of a call (x = f(x)): the task cannot be separated from it
            continue
        remaining = [
            i
            for i in instruction_ids
            if not (set(str(line) for line in pet.get_line_ids_of_instructions([i])) & update_lines)
        ]
        task_lines = {str(line) for line in pet.get_line_ids_of_instructions(remaining)} - {
            f"{loop.file_id}:{loop.start_line}"
        }
        if len(calls & task_lines) == 0:
            continue
        cursors = {str(d.var_name) for d in cursor_dependences}
        shared, private, first_private = _sharing(pet, loop_context, loop, cursors, task_lines)
        result.append(
            CursorLoop(
                node_id=str(pet_node_id),
                instruction_ids=remaining,
                shared=[Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in shared],
                private=[Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in private],
                first_private=[Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in first_private],
                cursors=sorted(cursors),
                update_lines=sorted(update_lines, key=_line_number),
            )
        )
        logger.info("Loop %s: tasks per iteration, cursors %s", pet_node_id, sorted(cursors))
    return result


__all__: Tuple[str, ...] = ("CursorLoop", "LoopTaskSource", "find_cursor_loops")
