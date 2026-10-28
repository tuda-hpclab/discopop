# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Data flow of a group of tasks: the dependences between the tasks, what the code after the group depends on, and the
data sharing of the variables of the tasks.

The information comes from the dependences registered on the contexts of the TaskGraph (the ContextTaskGraph drops
them while it is simplified): ``Context.outgoing_dependencies`` holds ``(source context, dependence)`` for a context
that is the sink, the later access, of the dependence. Only RAW and WAR are registered on contexts.

The variable types are not used: with opaque pointers they carry no information. A variable is classified by how the
tasks and the code after them access it (``classify_variable``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.utilities.PEGraphConstruction.parser import instructionToCUIdMap
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.enums.DepType import DepType

# the kinds of dependences registered on contexts, and what an access in the earlier task is
_KINDS = {DepType.RAW: "RAW", DepType.WAR: "WAR"}


@dataclass(frozen=True)
class TaskDependence:
    """A later task depends on an earlier one: ``kind`` RAW (the later reads what the earlier wrote) or WAR (the
    later writes what the earlier read)."""

    from_task: int
    to_task: int
    variable: str
    kind: str


@dataclass(frozen=True)
class AfterDependence:
    """The code after the group depends on a task: it reads what the task wrote (RAW) or writes what it read (WAR).
    ``line`` is the first line (file id:line) of the code after the group that does so."""

    task: int
    variable: str
    kind: str
    line: Optional[str]


@dataclass
class Sharing:
    shared: List[str] = field(default_factory=list)
    private: List[str] = field(default_factory=list)
    first_private: List[str] = field(default_factory=list)


@dataclass
class GroupDataflow:
    dependences: List[TaskDependence] = field(default_factory=list)
    after: List[AfterDependence] = field(default_factory=list)
    sharing: List[Sharing] = field(default_factory=list)


def _contexts_of(task: Context) -> Set[Context]:
    return {task} | task.get_contained_contexts(inclusive=True)


def _kind(dependence: Dependency) -> Optional[str]:
    return _KINDS.get(dependence.dtype) if dependence.dtype is not None else None


def _line_of_sink(pet: PEGraphX, dependence: Dependency) -> Optional[str]:
    if dependence.sink_instruction_id is not None:
        lines = pet.get_line_ids_of_instructions([dependence.sink_instruction_id])
        if lines:
            return str(lines[0])
    return str(dependence.sink_line) if dependence.sink_line else None


def _line_number(line: str) -> int:
    return int(line.split(":")[1])


def _dependences_between(task_contexts: List[Set[Context]]) -> List[TaskDependence]:
    found: Dict[Tuple[int, int, str, str], TaskDependence] = {}
    for later, later_contexts in enumerate(task_contexts):
        for context in later_contexts:
            for source_context, dependence in context.outgoing_dependencies:
                kind = _kind(dependence)
                if kind is None or dependence.var_name is None:
                    continue
                for earlier, earlier_contexts in enumerate(task_contexts):
                    if earlier != later and source_context in earlier_contexts:
                        key = (earlier, later, dependence.var_name, kind)
                        found[key] = TaskDependence(earlier, later, dependence.var_name, kind)
    return sorted(found.values(), key=lambda d: (d.from_task, d.to_task, d.variable, d.kind))


def _dependences_after(
    pet: PEGraphX, task_contexts: List[Set[Context]], after_contexts: Set[Context]
) -> List[AfterDependence]:
    first_line: Dict[Tuple[int, str, str], Optional[str]] = {}
    for task, contexts in enumerate(task_contexts):
        for context in contexts:
            for later_context, dependence in context.incoming_dependencies:
                kind = _kind(dependence)
                if later_context not in after_contexts or kind is None or dependence.var_name is None:
                    continue
                key = (task, dependence.var_name, kind)
                line = _line_of_sink(pet, dependence)
                known = first_line.get(key)
                if key not in first_line or (
                    line is not None and (known is None or _line_number(line) < _line_number(known))
                ):
                    first_line[key] = line
    return [AfterDependence(task, variable, kind, line) for (task, variable, kind), line in sorted(first_line.items())]


def _accessed_variables(pet: PEGraphX, task: Context) -> Dict[str, Tuple[bool, bool, str]]:
    """``name -> (read, written, defLine)`` of the variables the CUs of the task access."""
    accessed: Dict[str, Tuple[bool, bool, str]] = {}
    for tg_node in task.get_contained_nodes(inclusive=True):
        node = tg_node.get_pet_node(pet)
        for variable in list(getattr(node, "local_vars", [])) + list(getattr(node, "global_vars", [])):
            read, written, _ = accessed.get(variable.name, (False, False, variable.defLine))
            accessed[variable.name] = (
                read or "R" in variable.accessMode,
                written or "W" in variable.accessMode,
                variable.defLine,
            )
    return accessed


def classify_variable(
    read: bool,
    written: bool,
    declared_in_task: bool,
    global_variable: bool,
    written_by_sibling: bool,
    needed_after: bool,
) -> Optional[str]:
    """The data sharing of a variable of a task: ``shared``, ``private``, ``first_private``, or None if the task does
    not access it.

    - declared in the task: private, unless the code after the group needs its value (shared; the declaration has to
      move out of the task),
    - a global variable or one that is written by the task or by a sibling task: shared,
    - otherwise it is only read: first_private (the task works on the value at its creation).
    """
    if not read and not written:
        return None
    if declared_in_task:
        return "shared" if needed_after else "private"
    if global_variable or written or written_by_sibling:
        return "shared"
    return "first_private"


def _sharing(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    dependences: List[TaskDependence],
    after: List[AfterDependence],
) -> List[Sharing]:
    accessed = [_accessed_variables(pet, task) for task in tasks]
    result: List[Sharing] = []
    for index, variables in enumerate(accessed):
        sharing = Sharing()
        file_id, first, last = task_lines[index]
        for name, (read, written, def_line) in sorted(variables.items()):
            global_variable = def_line == "GlobalVar"
            declared = False
            if not global_variable and ":" in def_line:
                declared = int(def_line.split(":")[0]) == file_id and first <= _line_number(def_line) <= last
            by_sibling = any(
                other != index and variables_of_other[name][1]
                for other, variables_of_other in enumerate(accessed)
                if name in variables_of_other
            )
            needed_after = any(a.task == index and a.variable == name for a in after)
            kind = classify_variable(read, written, declared, global_variable, by_sibling, needed_after)
            if kind == "shared":
                sharing.shared.append(name)
            elif kind == "private":
                sharing.private.append(name)
            elif kind == "first_private":
                sharing.first_private.append(name)
        result.append(sharing)
    return result


def _with_pointer_writes(
    pet: PEGraphX, tasks: List[Context], task_lines: List[Tuple[int, int, int]], after: List[AfterDependence]
) -> List[AfterDependence]:
    """Adds what the code after the group reads of the writes of the callees of the tasks (not in the contexts)."""
    found: Dict[Tuple[int, str, str], Optional[str]] = {(a.task, a.variable, a.kind): a.line for a in after}
    last_line = max(last for _, _, last in task_lines)
    for index, task in enumerate(tasks):
        node = task.get_first_pet_node(pet)
        if node is None:
            continue
        function = function_of(pet, node)
        if function is None:
            continue
        extra = after_dependences_of_instructions(
            pet, task.get_instruction_scope(pet, inclusive=True), task_lines[index][0], last_line, function, index
        )
        for a in extra:
            key = (a.task, a.variable, a.kind)
            known = found.get(key)
            if key not in found or known is None or (a.line is not None and _line_number(a.line) < _line_number(known)):
                found[key] = a.line
    return [AfterDependence(task, variable, kind, line) for (task, variable, kind), line in sorted(found.items())]


def analyze_task_group(pet: PEGraphX, tasks: List[Context], task_lines: List[Tuple[int, int, int]]) -> GroupDataflow:
    """The data flow of the tasks of a group, in program order.

    ``task_lines``: ``(file id, first line, last line)`` of each task, to tell the variables declared in a task."""
    task_contexts = [_contexts_of(task) for task in tasks]
    inside: Set[Context] = set().union(*task_contexts) if task_contexts else set()
    after_contexts: Set[Context] = set()
    for task in tasks:
        after_contexts |= task.get_successive_contexts()
    after_contexts -= inside
    dependences = _dependences_between(task_contexts)
    after = _dependences_after(pet, task_contexts, after_contexts)
    after = _with_pointer_writes(pet, tasks, task_lines, after)
    return GroupDataflow(dependences, after, _sharing(pet, tasks, task_lines, dependences, after))


def instructions_with_callees(pet: PEGraphX, instruction_ids: List[int]) -> Set[int]:
    """The given instructions and the instructions of the functions they call, directly or not. The tasks do not
    inline their callees, but what a callee writes through a pointer is a result of the task."""
    result = set(instruction_ids)
    pending = list(instruction_ids)
    visited_functions: Set[str] = set()
    while pending:
        instruction = pending.pop()
        cu_id = instructionToCUIdMap.get(instruction)
        if cu_id is None or cu_id not in pet.g:
            continue
        for call in pet.node_at(NodeID(cu_id)).node_calls:
            if call.get("callInstId") is None or int(call["callInstId"]) != instruction:
                continue
            if call["cuid"] in visited_functions or call["cuid"] not in pet.g:
                continue
            visited_functions.add(call["cuid"])
            for cu in subtree_of_type(pet, pet.node_at(NodeID(call["cuid"])), CUNode):
                new_ids = [i for i in cu.instruction_ids if i not in result]
                result.update(new_ids)
                pending += new_ids
    return result


def function_of(pet: PEGraphX, node: Node) -> Optional[FunctionNode]:
    """The function that holds the node, None for a node that belongs to none (e.g. of a called function's dummy)."""
    try:
        return get_parent_function(pet, node)
    except AssertionError:
        return None


def _instruction_lines_after(pet: PEGraphX, function: FunctionNode, file_id: int, last_line: int) -> Dict[int, str]:
    """``instruction -> line`` of what runs in the function after ``last_line``: its own instructions on later lines,
    and the instructions of the functions called there, which are attributed to the line of the call."""
    owner: Dict[int, str] = {}
    cus = subtree_of_type(pet, function, CUNode)
    for cu in cus:
        for call in cu.node_calls:
            file, line = (int(part) for part in call["atLine"].split(":"))
            if file != file_id or not last_line < line <= function.end_line or call.get("callInstId") is None:
                continue
            for instruction in instructions_with_callees(pet, [int(call["callInstId"])]):
                owner.setdefault(instruction, f"{file}:{line}")
    for cu in cus:
        for instruction in cu.instruction_ids:
            for line_id in pet.get_line_ids_of_instructions([instruction]):
                file, line = (int(part) for part in str(line_id).split(":"))
                if file == file_id and last_line < line <= function.end_line:
                    owner[instruction] = str(line_id)
    return owner


def after_dependences_of_instructions(
    pet: PEGraphX, instruction_ids: List[int], file_id: int, last_line: int, function: FunctionNode, task: int = 0
) -> List[AfterDependence]:
    """What the code after a task depends on, found in the PET: ``instruction_ids`` are the instructions of the task
    (they lie in the CUs of its body, not only in the node of the task) and those of the functions it calls, whose
    writes through pointers the contexts do not see. A RAW or WAR whose earlier end is one of them and whose later
    end runs in the ``function`` that holds the task after ``last_line`` (the last line of the task), directly or in a
    function called there (reported at the line of the call). Its variable is the name at the later access.
    If the task reaches its own function (recursion), the result is empty: the code of the function cannot be told apart
    from the code the task runs in the recursive calls."""
    inside = instructions_with_callees(pet, instruction_ids)
    later = _instruction_lines_after(pet, function, file_id, last_line)
    own_code = {i for cu in subtree_of_type(pet, function, CUNode) for i in cu.instruction_ids} - set(instruction_ids)
    if own_code & inside:
        # the code of the function cannot be told apart from that of the recursive calls: nothing reliable to say
        return []
    written_by_task = inside - set(later)
    first_line: Dict[Tuple[str, str], str] = {}
    cu_ids = sorted({NodeID(instructionToCUIdMap[i]) for i in written_by_task if i in instructionToCUIdMap})
    for cu_id in cu_ids:
        if cu_id not in pet.g:
            continue
        for _, _, dependence in in_edges(pet, cu_id, EdgeType.DATA):
            kind = _kind(dependence)
            if kind is None or dependence.var_name is None:
                continue
            sink = dependence.sink_instruction_id
            if dependence.source_instruction_id not in written_by_task or sink not in later:
                continue
            line = later[sink]
            key = (dependence.var_name, kind)
            if key not in first_line or _line_number(line) < _line_number(first_line[key]):
                first_line[key] = line
    return [AfterDependence(task, variable, kind, line) for (variable, kind), line in sorted(first_line.items())]


def clauses_of_dependences(dependences: List[TaskDependence], task: int) -> Tuple[List[str], List[str], List[str]]:
    """The ``in``, ``out`` and ``in/out`` variables of a task, as the OpenMP depend clauses would list them: the
    earlier access of a RAW is an out, the later an in; of a WAR, the earlier is an in and the later an out."""
    ins: Set[str] = set()
    outs: Set[str] = set()
    for dependence in dependences:
        earlier_writes = dependence.kind == "RAW"
        if dependence.from_task == task:
            (outs if earlier_writes else ins).add(dependence.variable)
        if dependence.to_task == task:
            (ins if earlier_writes else outs).add(dependence.variable)
    both = ins & outs
    return sorted(ins - both), sorted(outs - both), sorted(both)


__all__: Tuple[str, ...] = (
    "AfterDependence",
    "GroupDataflow",
    "Sharing",
    "TaskDependence",
    "analyze_task_group",
    "classify_variable",
    "clauses_of_dependences",
    "function_of",
    "after_dependences_of_instructions",
    "instructions_with_callees",
)
