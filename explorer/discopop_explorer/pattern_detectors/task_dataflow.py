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
that is the sink, the later access, of the dependence. Only RAW and WAR are registered on contexts: a WAW would make
the contexts depend on each other, which changes which sequences are split into tasks and which loops are do-all.
The output dependences between the tasks (WAW) are therefore read from the PET by the instructions of the tasks.

The variable types are not used: with opaque pointers they carry no information. A variable is classified by how the
tasks and the code after them access it (``classify_variable``).

Names. The pragmas of a task group are written in the scope of the function that holds the group, so every name that is
reported (``variable`` of a dependence) is a name of that scope: a variable the code of the function accesses (its
parameters and locals) or a global. The profiler names a dependence by its LATER access, which can lie in a callee (a
callee writing ``*dst`` shows as ``res``) or in the code that called the function (``a`` in ``main``). A name that is
not one of the function's is translated (``_caller_names``):

- a global keeps its name,
- otherwise the candidates are the variables the code of the task itself accesses (not its callees): those that the
  code at the later access names as well (the variables of the call line that reads the result), else the pointer
  parameters of the function that the task accesses (the callee's ``dst`` is one of them), else none: the dependence is
  reported without a name (``""``), since its join or ordering is still needed.
- the callee's own name is not known (a dependence holds the name at the later access only), and neither are the
  arguments of a call, so the translation is a heuristic: a task that passes two pointer parameters on yields both.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.utilities.PEGraphConstruction.parser import instructionToCUIdMap
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_explorer.utilities.callpath_states import call_instructions_of_state
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.enums.DepType import DepType

# the kinds of dependences of the code after a group; contexts only carry RAW and WAR (see the module docstring)
OUTPUT = "WAW"
_KINDS = {DepType.RAW: "RAW", DepType.WAR: "WAR", DepType.WAW: OUTPUT}


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
    """The code after the group depends on a task: it reads what the task wrote (RAW), writes what it read (WAR) or
    writes what it wrote (WAW).
    ``line`` is the first line (file id:line) of the code after the group that does so; ``at_return`` if the code is not
    in the function of the group at all (then there is no line)."""

    task: int
    variable: str
    kind: str
    line: Optional[str]
    # the reader is outside of the function that holds the group, i.e. the group has to be complete before the
    # function returns (``line`` is None): a task writes through a pointer parameter or a global, and the caller
    # reads it
    at_return: bool = False


@dataclass
class Sharing:
    shared: List[str] = field(default_factory=list)
    private: List[str] = field(default_factory=list)
    first_private: List[str] = field(default_factory=list)
    # "<operation>:<name>", the operation is "?" if the explorer does not know it: variables that several tasks
    # accumulate into (they are not listed as shared)
    reduction: List[str] = field(default_factory=list)


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


@dataclass
class _Scope:
    """What the names of the function that holds a task group can be: see the module docstring."""

    # names of the variables the code of the function accesses, and of its parameters
    local: Set[str]
    # the names of the global variables of the program
    globals: Set[str]
    # the parameters that are pointers (or references): what a callee writes through, the caller reads
    pointer_params: Set[str]
    # the instructions of the code of the function itself (not of its callees)
    instructions: Set[int]


_global_names_of: "weakref.WeakKeyDictionary[PEGraphX, Set[str]]" = weakref.WeakKeyDictionary()


def _global_names(pet: PEGraphX) -> Set[str]:
    cached = _global_names_of.get(pet)
    if cached is None:
        cached = set()
        for cu in all_nodes(pet, CUNode):
            cached.update(v.name for v in cu.global_vars)
            cached.update(v.name for v in cu.local_vars if v.defLine == "GlobalVar")
        _global_names_of[pet] = cached
    return cached


def _scope_of(
    pet: PEGraphX,
    function: FunctionNode,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
    file_id: int = 0,
    line: int = 0,
) -> _Scope:
    """The scope of ``function``. The profiler only knows the variables that are read or written, the AST also those
    that are declared (``ast_helper``: the declarations visible at ``line``), e.g. a local that is only passed by
    address."""
    local: Set[str] = {str(v.name) for v in function.args}
    if ast_helper is not None:
        local.update(name for name, _ in ast_helper.get_variables_at_location(file_id, line))
    instructions: Set[int] = set()
    for cu in subtree_of_type(pet, function, CUNode):
        local.update(v.name for v in cu.local_vars)
        local.update(v.name for v in cu.global_vars)
        instructions.update(cu.instruction_ids)
    pointers = {str(v.name) for v in function.args if "ptr" in str(v.type) or "*" in str(v.type)}
    return _Scope(local, _global_names(pet), pointers, instructions)


def _variables_of_instructions(pet: PEGraphX, instruction_ids: Iterable[int]) -> Set[str]:
    """The names of the variables the CUs of the instructions access (the code itself, not its callees)."""
    names: Set[str] = set()
    for cu_id in {instructionToCUIdMap[i] for i in instruction_ids if i in instructionToCUIdMap}:
        if cu_id in pet.g:
            node = pet.node_at(NodeID(cu_id))
            for variable in list(getattr(node, "local_vars", [])) + list(getattr(node, "global_vars", [])):
                names.add(variable.name)
    return names


def _referenced_names(ast_helper: Optional[ASTPatternDetectionHelper], lines: Tuple[int, int, int]) -> Set[str]:
    """The names the code on the lines of a task refers to (AST), none without AST."""
    if ast_helper is None:
        return set()
    file_id, first, last = lines
    return set(ast_helper.get_referenced_names(file_id, first, last))


def _variables_at_line(
    pet: PEGraphX, function: FunctionNode, line: Optional[str], ast_helper: Optional[ASTPatternDetectionHelper] = None
) -> Optional[Set[str]]:
    """The names of the variables the CUs of the function that have an instruction on the line access, and the names
    the code on the line refers to (AST); None for no line."""
    if line is None:
        return None
    names: Set[str] = set()
    for cu in subtree_of_type(pet, function, CUNode):
        if any(pet.instruction_lines.get(str(i)) == line for i in cu.instruction_ids):
            names.update(v.name for v in cu.local_vars)
            names.update(v.name for v in cu.global_vars)
    if ast_helper is not None:
        file_id, line_number = (int(part) for part in line.split(":"))
        names.update(ast_helper.get_referenced_names(file_id, line_number, line_number))
    return names


def _caller_names(
    scope: _Scope, name: str, sink_in_function: bool, own: Set[str], at_sink: Optional[Set[str]] = None
) -> List[str]:
    """The names of the scope of the function for a dependence that the profiler named ``name`` at its later access.

    ``sink_in_function``: the later access is code of the function itself, so ``name`` is one of the scope.
    ``own``: the names the code of the task (or of both tasks of a dependence between tasks) accesses.
    ``at_sink``: the names accessed by the code of the function that holds the later access (the line of the call
    that reads a result), if there is such code. Empty if the name cannot be translated."""
    if sink_in_function or name in scope.globals:
        return [name]
    candidates = own & scope.local
    if at_sink is not None and candidates & at_sink:
        return sorted(candidates & at_sink)
    return sorted(candidates & scope.pointer_params)


def _belongs_to_task(pet: PEGraphX, dependence: Dependency, own_instructions: Set[int]) -> bool:
    """Whether the earlier access of the dependence was made by the task with the instructions ``own_instructions``.
    Tasks that call one function share its instructions, so the callpath state of the earlier access tells which call
    it came from. Without a state, the instruction decides (a task may be credited with the write of a sibling)."""
    if dependence.source_instruction_id in own_instructions:
        return True
    calls = call_instructions_of_state(getattr(pet, "callpath_tree", {}), dependence.source_state_id)
    return not calls or bool(calls & own_instructions)


def _dependences_between(
    task_contexts: List[Set[Context]], scope: Optional[_Scope] = None, own: Optional[List[Set[str]]] = None
) -> List[TaskDependence]:
    found: Dict[Tuple[int, int, str, str], TaskDependence] = {}
    for later, later_contexts in enumerate(task_contexts):
        for context in later_contexts:
            for source_context, dependence in context.outgoing_dependencies:
                kind = _kind(dependence)
                if kind is None or dependence.var_name is None:
                    continue
                for earlier, earlier_contexts in enumerate(task_contexts):
                    if earlier != later and source_context in earlier_contexts:
                        names = [dependence.var_name]
                        if scope is not None and own is not None:
                            sink_in_function = (
                                dependence.sink_instruction_id is None
                                or dependence.sink_instruction_id in scope.instructions
                            )
                            names = _caller_names(
                                scope, dependence.var_name, sink_in_function, own[earlier] & own[later]
                            ) or [""]
                        for name in names:
                            found[(earlier, later, name, kind)] = TaskDependence(earlier, later, name, kind)
    return sorted(found.values(), key=lambda d: (d.from_task, d.to_task, d.variable, d.kind))


def _output_dependences(pet: PEGraphX, task_instructions: List[Set[int]]) -> List[TaskDependence]:
    """The WAW dependences between the tasks, by the instructions at their two ends (not registered on contexts)."""
    owner: Dict[int, int] = {}
    for task, instructions in enumerate(task_instructions):
        for instruction in instructions:
            owner.setdefault(instruction, task)
    cu_ids = sorted({NodeID(instructionToCUIdMap[i]) for i in owner if i in instructionToCUIdMap})
    found: Dict[Tuple[int, int, str], TaskDependence] = {}
    for cu_id in cu_ids:
        if cu_id not in pet.g:
            continue
        for _, _, dependence in in_edges(pet, cu_id, EdgeType.DATA):
            if dependence.dtype != DepType.WAW or dependence.var_name is None:
                continue
            earlier = owner.get(dependence.source_instruction_id) if dependence.source_instruction_id else None
            later = owner.get(dependence.sink_instruction_id) if dependence.sink_instruction_id else None
            if earlier is None or later is None or earlier == later:
                continue
            found[(earlier, later, dependence.var_name)] = TaskDependence(earlier, later, dependence.var_name, OUTPUT)
    return list(found.values())


def _dependences_after(
    pet: PEGraphX,
    task_contexts: List[Set[Context]],
    after_contexts: Set[Context],
    function: Optional[FunctionNode] = None,
    own: Optional[List[Set[str]]] = None,
    scope: Optional[_Scope] = None,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> List[AfterDependence]:
    first_line: Dict[Tuple[int, str, str], Optional[str]] = {}
    for task, contexts in enumerate(task_contexts):
        for context in contexts:
            for later_context, dependence in context.incoming_dependencies:
                kind = _kind(dependence)
                if later_context not in after_contexts or kind is None or dependence.var_name is None:
                    continue
                line = _line_of_sink(pet, dependence)
                names = [dependence.var_name]
                if scope is not None and own is not None and function is not None:
                    sink_in_function = (
                        dependence.sink_instruction_id is None or dependence.sink_instruction_id in scope.instructions
                    )
                    names = _caller_names(
                        scope,
                        dependence.var_name,
                        sink_in_function,
                        own[task],
                        _variables_at_line(pet, function, line, ast_helper),
                    ) or [""]
                for name in names:
                    key = (task, name, kind)
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
    accumulated_by_siblings: bool = False,
) -> Optional[str]:
    """The data sharing of a variable of a task: ``shared``, ``private``, ``first_private``, ``reduction``, or None if
    the task does not access it.

    - declared in the task: private, unless the code after the group needs its value (shared; the declaration has to
      move out of the task),
    - read and written by the task and by a sibling (``accumulated_by_siblings``, e.g. ``sum += ...`` in each): a
      reduction; plain shared would be a race,
    - a global variable or one that is written by the task or by a sibling task: shared,
    - otherwise it is only read: first_private (the task works on the value at its creation).
    """
    if not read and not written:
        return None
    if declared_in_task:
        return "shared" if needed_after else "private"
    if read and written and accumulated_by_siblings:
        return "reduction"
    if global_variable or written or written_by_sibling:
        return "shared"
    return "first_private"


def _reduction_operation(pet: PEGraphX, name: str, file_id: int, first: int, last: int) -> str:
    """The operation of the reduction of ``name`` on a line of the task, as the profiler recorded it (reduction.txt,
    which covers the loops only); ``?`` if there is none."""
    for entry in getattr(pet, "reduction_vars", None) or []:
        file, _, line = entry["reduction_line"].partition(":")
        if entry["name"] == name and file.isdigit() and int(file) == file_id and line.isdigit():
            if first <= int(line) <= last:
                return str(entry["operation"])
    return "?"


def _mark_written(
    accessed: List[Dict[str, Tuple[bool, bool, str]]],
    dependences: List[TaskDependence],
    after: List[AfterDependence],
) -> None:
    """A task is known to write the variable of a RAW or WAW that starts at it. The CU of a compound assignment
    (``sum += f(x)``) can list the variable as read only, but the dependences show the write."""
    writes = [(a.task, a.variable) for a in after if a.kind in ("RAW", OUTPUT)]
    writes += [(d.from_task, d.variable) for d in dependences if d.kind in ("RAW", OUTPUT)]
    writes += [(d.to_task, d.variable) for d in dependences if d.kind in ("WAR", OUTPUT)]
    for task, name in writes:
        if name in accessed[task]:
            read, _, def_line = accessed[task][name]
            accessed[task][name] = (read, True, def_line)


def _sharing(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    dependences: List[TaskDependence],
    after: List[AfterDependence],
) -> List[Sharing]:
    accessed = [_accessed_variables(pet, task) for task in tasks]
    _mark_written(accessed, dependences, after)
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
            accumulated = any(
                other != index and variables_of_other[name][0] and variables_of_other[name][1]
                for other, variables_of_other in enumerate(accessed)
                if name in variables_of_other
            )
            needed_after = any(a.task == index and a.variable == name for a in after)
            kind = classify_variable(read, written, declared, global_variable, by_sibling, needed_after, accumulated)
            if kind == "shared":
                sharing.shared.append(name)
            elif kind == "private":
                sharing.private.append(name)
            elif kind == "first_private":
                sharing.first_private.append(name)
            elif kind == "reduction":
                sharing.reduction.append(f"{_reduction_operation(pet, name, file_id, first, last)}:{name}")
        result.append(sharing)
    return result


def _with_pointer_writes(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    after: List[AfterDependence],
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> List[AfterDependence]:
    """Adds what the code after the group reads of the writes of the callees of the tasks (not in the contexts), in the
    function of the group or, for a function that returns before, after it returned."""
    found: Dict[Tuple[int, str, str, bool], Optional[str]] = {
        (a.task, a.variable, a.kind, a.at_return): a.line for a in after
    }
    last_line = max(last for _, _, last in task_lines)
    placed: List[Tuple[int, FunctionNode, List[int]]] = []
    for index, task in enumerate(tasks):
        node = task.get_first_pet_node(pet)
        function = function_of(pet, node) if node is not None else None
        if function is not None:
            placed.append((index, function, task.get_instruction_scope(pet, inclusive=True)))
    # what a dependence between tasks is not: a read of the group, even in the callees of a task, is no join
    group: Set[int] = (
        set().union(*(instructions_with_callees(pet, scope) for _, _, scope in placed)) if placed else set()
    )
    for index, function, scope in placed:
        extra = after_dependences_of_instructions(
            pet,
            scope,
            task_lines[index][0],
            last_line,
            function,
            index,
            group,
            ast_helper,
            task_lines[index][1],
            task_lines[index][2],
        )
        for a in extra:
            key = (a.task, a.variable, a.kind, a.at_return)
            known = found.get(key)
            if key not in found or known is None or (a.line is not None and _line_number(a.line) < _line_number(known)):
                found[key] = a.line
    return [
        AfterDependence(task, variable, kind, line, at_return)
        for (task, variable, kind, at_return), line in sorted(found.items(), key=lambda item: (item[0][:3], item[0][3]))
    ]


def analyze_task_group(
    pet: PEGraphX,
    tasks: List[Context],
    task_lines: List[Tuple[int, int, int]],
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
) -> GroupDataflow:
    """The data flow of the tasks of a group, in program order.

    ``task_lines``: ``(file id, first line, last line)`` of each task, to tell the variables declared in a task.
    ``ast_helper``: the AST, if there is one, which knows the variables that are only passed by address."""
    task_contexts = [_contexts_of(task) for task in tasks]
    inside: Set[Context] = set().union(*task_contexts) if task_contexts else set()
    after_contexts: Set[Context] = set()
    for task in tasks:
        after_contexts |= task.get_successive_contexts()
    after_contexts -= inside
    function = None
    first_node = tasks[0].get_first_pet_node(pet) if tasks else None
    if first_node is not None:
        function = function_of(pet, first_node)
    scope = _scope_of(pet, function, ast_helper, task_lines[0][0], task_lines[0][1]) if function is not None else None
    own = None
    if scope is not None:
        own = [
            set(_accessed_variables(pet, task)) | _referenced_names(ast_helper, lines)
            for task, lines in zip(tasks, task_lines)
        ]
    dependences = _dependences_between(task_contexts, scope, own) + _output_dependences(
        pet, [set(task.get_instruction_scope(pet, inclusive=True)) for task in tasks]
    )
    dependences.sort(key=lambda d: (d.from_task, d.to_task, d.variable, d.kind))
    after = _dependences_after(pet, task_contexts, after_contexts, function, own, scope, ast_helper)
    after = _with_pointer_writes(pet, tasks, task_lines, after, ast_helper)
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


def variables_of_instructions(pet: PEGraphX, instruction_ids: List[int]) -> Set[str]:
    """The names of the variables that the CUs of the instructions access (CU granularity: it may include variables
    of code that shares a CU with the instructions)."""
    return _variables_of_instructions(pet, instruction_ids)


def _written_by_recursive_task(pet: PEGraphX, reached: Set[int], function: FunctionNode, file_id: int) -> Set[int]:
    """The instructions whose writes a task that reaches its own function may leave to the code after it.

    The profiler cuts the callpath states at a recursive call, so every recursion level shares the states of the
    first one: a record cannot tell whether its earlier end ran in the task (a deeper level) or in the code of the
    function around it (the caller's level). Everything the function runs before the code after the task counts as
    the work of the task, except the instructions on the header line of the function: they store the parameters,
    which belong to the frame of the level that runs them, never to the caller. The result over-approximates: a write
    of the caller's own level before the task that the code after it reads is reported as well (a join where none
    may be needed, never a missing one)."""
    header = f"{file_id}:{function.start_line}"
    return {i for i in reached if header not in {str(line) for line in pet.get_line_ids_of_instructions([i])}}


def after_dependences_of_instructions(
    pet: PEGraphX,
    instruction_ids: List[int],
    file_id: int,
    last_line: int,
    function: FunctionNode,
    task: int = 0,
    group_instructions: Optional[Set[int]] = None,
    ast_helper: Optional[ASTPatternDetectionHelper] = None,
    task_first_line: Optional[int] = None,
    task_last_line: Optional[int] = None,
) -> List[AfterDependence]:
    """What the code after a task depends on, found in the PET: ``instruction_ids`` are the instructions of the task
    (they lie in the CUs of its body, not only in the node of the task) and those of the functions it calls, whose
    writes through pointers the contexts do not see.

    - A RAW or WAR whose earlier end is one of them and whose later end runs in the ``function`` that holds the task
      after ``last_line`` (the last line of the task), directly or in a function called there (reported at the line of
      the call).
    - A RAW whose later end runs outside of the function (in its caller, after it returned, or in anything else that
      is not part of the function or the group) is a dependence ``at_return``: the task has to be complete before the
      function returns. It has no line. WAR is not looked for there: any later write of the caller to memory the task
      read would qualify.

    The earlier end must belong to the task: tasks that call the same function share its instructions, so the callpath
    state of the dependence tells which call wrote (``_belongs_to_task``).
    ``task_first_line``, ``task_last_line``: the lines of the task (for the AST), default: up to ``last_line``.
    ``group_instructions``: the instructions of all tasks of the group with their callees; a dependence into them is
    one between the tasks. The names are those of the scope of ``function`` (see the module docstring).
    If the task reaches its own function (recursion), the dependences cannot be assigned to a recursion level (the
    callpath states are cut at the recursive call): see ``_written_by_recursive_task``; the result is an
    over-approximation. A parameter of the function that the CUs of the task's own instructions do not access is not
    reported: it is read by the code after the task through the frame of the caller's own level (``*out = 0; ...
    *out += x`` after the task), while one the task passes on may be written by the deeper levels."""
    inside = instructions_with_callees(pet, instruction_ids)
    later = _instruction_lines_after(pet, function, file_id, last_line)
    scope = _scope_of(pet, function, ast_helper, file_id, task_first_line or last_line)
    own_code = scope.instructions
    written_by_task = inside - set(later)
    unpassed_parameters: Set[str] = set()
    recursive = bool((own_code - set(instruction_ids)) & inside)
    if recursive:
        # the task reaches its own function: the code of the function cannot be told apart from the code the task
        # runs in the recursive calls
        written_by_task = _written_by_recursive_task(pet, written_by_task, function, file_id)
        parameters = {str(v.name) for v in function.args}
        unpassed_parameters = parameters - variables_of_instructions(pet, instruction_ids)
    excluded = inside | (group_instructions or set())
    own_instructions = set(instruction_ids)
    own_names = _variables_of_instructions(pet, instruction_ids) | _referenced_names(
        ast_helper, (file_id, task_first_line or last_line, task_last_line or last_line)
    )
    first_line: Dict[Tuple[str, str, bool], Optional[str]] = {}
    cu_ids = sorted({NodeID(instructionToCUIdMap[i]) for i in written_by_task if i in instructionToCUIdMap})
    for cu_id in cu_ids:
        if cu_id not in pet.g:
            continue
        for _, _, dependence in in_edges(pet, cu_id, EdgeType.DATA):
            kind = _kind(dependence)
            if kind is None or dependence.var_name is None:
                continue
            if dependence.var_name in unpassed_parameters:
                continue
            sink = dependence.sink_instruction_id
            if dependence.source_instruction_id not in written_by_task or sink is None:
                continue
            # the callpath state tells which call wrote, but not for a recursive task: the states are cut at the
            # recursive call, and every record has the state of the first level
            if not recursive and not _belongs_to_task(pet, dependence, own_instructions):
                continue
            if sink in later:
                line: Optional[str] = later[sink]
                names = _caller_names(
                    scope,
                    dependence.var_name,
                    sink in own_code,
                    own_names,
                    _variables_at_line(pet, function, line, ast_helper),
                )
                at_return = False
            elif not recursive and kind == "RAW" and sink not in excluded and sink not in own_code:
                # not for a recursive task: the writes of its recursion levels cannot be told apart (the call paths
                # are cut), and memory the recursion left on the stack would be reported as read by unrelated code
                line, at_return = None, True
                names = _caller_names(scope, dependence.var_name, False, own_names)
            else:
                continue
            for name in names or [""]:
                key = (name, kind, at_return)
                known = first_line.get(key)
                if key not in first_line or (
                    line is not None and (known is None or _line_number(line) < _line_number(known))
                ):
                    first_line[key] = line
    return [
        AfterDependence(task, variable, kind, line, at_return)
        for (variable, kind, at_return), line in sorted(first_line.items(), key=lambda item: (item[0][:2], item[0][2]))
    ]


def clauses_of_dependences(dependences: List[TaskDependence], task: int) -> Tuple[List[str], List[str], List[str]]:
    """The ``in``, ``out`` and ``in/out`` variables of a task, as the OpenMP depend clauses would list them: the
    earlier access of a RAW is an out, the later an in; of a WAR, the earlier is an in and the later an out; both
    accesses of a WAW are outs."""
    ins: Set[str] = set()
    outs: Set[str] = set()
    for dependence in dependences:
        if not dependence.variable:
            continue
        earlier_writes = dependence.kind in ("RAW", OUTPUT)
        later_writes = dependence.kind in ("WAR", OUTPUT)
        if dependence.from_task == task:
            (outs if earlier_writes else ins).add(dependence.variable)
        if dependence.to_task == task:
            (outs if later_writes else ins).add(dependence.variable)
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
    "variables_of_instructions",
)
