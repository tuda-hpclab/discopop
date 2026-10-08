# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Builds the side effect export at the end of an explorer run (format: ``schema``).

Reads the TaskGraph, the PET and the AST, but changes none of them: the dependency
records are mapped by ``TaskGraph.map_dynamic_dependency_records``, a separate pass
next to the dependency insertion, so pattern detection is unaffected.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Functions.TGStartFunctionNode import TGStartFunctionNode
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.side_effects.schema import (
    FORMAT_VERSION,
    EXPORT_FILE_NAME,
    ExecutedCall,
    Function,
    GlobalReference,
    GlobalVariable,
    Instance,
    LocalVariable,
    Parameter,
    Record,
    SideEffectExport,
    dependency_file_info,
    save_export,
)
from discopop_library.global_data.version.utils import get_version

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
    from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
    from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

logger = logging.getLogger("Explorer")

_FUNCTION_DECL_KINDS = frozenset(
    {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl", "CXXConversionDecl"}
)
# declarations whose VarDecl children are not locals of a function
_SCOPE_KINDS = frozenset({"TranslationUnitDecl", "NamespaceDecl", "LinkageSpecDecl", "CXXRecordDecl", "RecordDecl"})
# nodes that are transparent when looking for the operator a DeclRefExpr is the operand of
_TRANSPARENT_KINDS = frozenset({"ParenExpr", "ArraySubscriptExpr", "MemberExpr"})
# nodes a reference can be an argument of; the callee decides whether it is read or written
_CALL_KINDS = frozenset(
    {"CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr", "CXXConstructExpr", "CXXTemporaryObjectExpr"}
)


def export_file(discopop_dir: str) -> str:
    """Path of the export inside a .discopop directory (the explorer's working directory)."""
    return os.path.join(discopop_dir, "explorer", EXPORT_FILE_NAME)


def write_export(
    discopop_dir: str,
    task_graph: TaskGraph,
    pet: PEGraphX,
    ast_helper: Optional[ASTPatternDetectionHelper],
    file_mapping: Optional[str] = None,
) -> Optional[str]:
    """Build and write the export; returns its path, or None if it was not built.

    Failures are logged and swallowed: the export is an optional by-product of the run.
    ``file_mapping`` is the explorer's --fmap file (default: FileMapping.txt in ``discopop_dir``).
    """
    path = export_file(discopop_dir)
    try:
        if task_graph.ignore_dependency_states:
            # without dependency states every record is static, so no access can be attributed to a
            # call; an export would only claim effects it cannot have observed
            _remove_stale_export(path)
            logger.info("Side effect export skipped: the explorer runs with --ignore-dependency-states")
            return None
        export = build_export(discopop_dir, task_graph, pet, ast_helper, file_mapping)
        save_export(export, path)
        logger.info(
            "Wrote side effect export %s (%d functions, %d instances, %d records)",
            path,
            len(export["functions"]),
            len(export["instances"]),
            len(export["records"]),
        )
        return path
    except Exception as e:  # noqa: BLE001 - the export must never fail the explorer run
        logger.warning("Could not write the side effect export: %s", e, exc_info=True)
        _remove_stale_export(path)
        return None


def _remove_stale_export(path: str) -> None:
    """Remove an export of an earlier run, so that a reader reports the data as missing."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove the stale side effect export %s: %s", path, e)


def build_export(
    discopop_dir: str,
    task_graph: TaskGraph,
    pet: PEGraphX,
    ast_helper: Optional[ASTPatternDetectionHelper],
    file_mapping: Optional[str] = None,
) -> SideEffectExport:
    files = _read_file_mapping(file_mapping or os.path.join(discopop_dir, "FileMapping.txt"))
    pet_functions = sorted(all_nodes(pet, FunctionNode), key=lambda f: (f.file_id, f.start_line, str(f.id)))
    file_ids = _function_file_ids(pet, pet_functions, files)
    pet_functions.sort(key=lambda f: (file_ids[f], f.start_line, str(f.id)))

    instances, work_contexts, context_ids = _collect_instances(task_graph, pet_functions)
    mapped_records = task_graph.map_dynamic_dependency_records()

    line_to_function = _LineToFunction(pet_functions, file_ids)
    records: List[Record] = []
    instruction_names: Dict[str, List[str]] = {}
    unmapped: Dict[str, int] = {}
    for mapped in mapped_records:
        first_instr, first_state, first_line = mapped.first
        names = instruction_names.setdefault(str(first_instr), [])
        if mapped.var_name not in names:
            names.append(mapped.var_name)
        ends = [(first_line, mapped.first_contexts)]
        if mapped.other is not None:
            ends.append((mapped.other[2], mapped.other_contexts))
        for line, contexts in ends:
            if not any(c in context_ids for c in contexts):
                function_id = line_to_function.lookup(line)
                if function_id is not None:
                    unmapped[function_id] = unmapped.get(function_id, 0) + 1
        record: Record = {
            "type": mapped.dep_type,
            "var": mapped.var_name,
            "first": (first_instr, first_state, str(first_line) if first_line is not None else ""),
            "other": (
                (mapped.other[0], mapped.other[1], str(mapped.other[2]) if mapped.other[2] is not None else "")
                if mapped.other is not None
                else None
            ),
            "pairs": [
                (context_ids[first], context_ids[other])
                for first, other in mapped.pairs
                if first in context_ids and other in context_ids
            ],
            "first_contexts": [context_ids[c] for c in mapped.first_contexts if c in context_ids],
            "other_contexts": [context_ids[c] for c in mapped.other_contexts if c in context_ids],
        }
        if len(record["first_contexts"]) == 0 and len(record["other_contexts"]) == 0:
            # neither end could be attributed to a calling context of an exported instance;
            # the record carries nothing the analysis could use but the instruction's name
            continue
        records.append(record)
    for names in instruction_names.values():
        names.sort()

    executed_calls = _read_executed_calls(task_graph.dynamic_dependency_file, pet_functions, line_to_function)
    executed_functions = {call["callee"] for call in executed_calls}

    ast_facts = _AstFacts(ast_helper, files, pet_functions)
    ast_facts.file_ids_of_functions = file_ids
    display_names = _demangle([str(f.name) for f in pet_functions])
    functions: List[Function] = []
    for function in pet_functions:
        facts = ast_facts.function_facts(function)
        functions.append(
            {
                "id": str(function.id),
                "name": str(function.name),
                "display_name": display_names.get(str(function.name), facts.display_name or str(function.name)),
                "file_id": file_ids[function],
                "start_line": int(function.start_line),
                "end_line": int(function.end_line),
                "ast_facts": facts.found,
                "params": facts.params,
                "locals": facts.locals,
                "member_accesses": facts.member_accesses,
                "performs_file_io": _performs_file_io(pet, function),
                "static_callees": _static_callees(pet, function),
                "unprofiled_calls": ast_facts.unprofiled_calls(facts),
                "global_refs": facts.global_refs,
                "executed": str(function.id) in executed_functions,
            }
        )

    dependency_file = task_graph.dynamic_dependency_file
    return {
        "format_version": FORMAT_VERSION,
        "discopop_version": get_version(),
        "ignore_dependency_states": bool(task_graph.ignore_dependency_states),
        "dependency_file": dependency_file_info(dependency_file) if dependency_file is not None else None,
        "files": {str(file_id): str(path) for file_id, path in sorted(files.items())},
        "globals": ast_facts.globals,
        "functions": functions,
        "instances": instances,
        "work_contexts": work_contexts,
        "records": records,
        "instruction_names": instruction_names,
        "executed_calls": executed_calls,
        "unmapped_records": dict(sorted(unmapped.items())),
        "linker_names": dict(sorted(ast_facts.linker_names.items())),
    }


def _read_file_mapping(path: str) -> Dict[int, str]:
    files: Dict[int, str] = {}
    if not os.path.exists(path):
        return files
    with open(path, "r") as f:
        for line in f:
            split = line.rstrip("\n").split("\t")
            if len(split) >= 2 and split[0].strip().isdigit():
                files[int(split[0])] = split[1]
    return files


def _function_file_ids(
    pet: PEGraphX, pet_functions: List[FunctionNode], files: Dict[int, str]
) -> Dict[FunctionNode, int]:
    """File id of every function. The PET takes a node's file id from its node id, which is wrong for
    the node "0:0" (the first function of a module); such functions get the file id their CUs agree on."""
    result: Dict[FunctionNode, int] = {}
    for function in pet_functions:
        file_id = int(function.file_id)
        if file_id not in files:
            votes: Dict[int, int] = {}
            for cu_id in function.children_cu_ids or []:
                cu_file_id = int(pet.node_at(cu_id).file_id)
                if cu_file_id in files:
                    votes[cu_file_id] = votes.get(cu_file_id, 0) + 1
            if len(votes) > 0:
                file_id = max(sorted(votes), key=lambda f: votes[f])
        result[function] = file_id
    return result


def _function_id_of_instance(context: Context) -> Optional[str]:
    for node in context.contained_nodes:
        if isinstance(node, TGStartFunctionNode) and node.pet_node_id is not None:
            return str(node.pet_node_id)
    return None


def _collect_instances(
    task_graph: TaskGraph, pet_functions: List[FunctionNode]
) -> Tuple[List[Instance], Dict[str, int], Dict[Context, int]]:
    """FunctionContext copies below main's top-level copy, and the work contexts inside them.

    Returns (instances, work context id -> instance id, context -> exported id). Work
    contexts and instances share one id space (the position in TaskGraph.contexts).
    """
    contexts = sorted(task_graph.contexts, key=lambda c: c.creation_index)
    context_ids: Dict[Context, int] = {c: i for i, c in enumerate(contexts)}

    def closest_instance(context: Context) -> Tuple[Optional[FunctionContext], Optional[InlinedFunctionContext]]:
        """The closest FunctionContext strictly above ``context`` and the closest InlinedFunctionContext
        on the way to it. Iterative with a visited set: the containment relation may be inconsistent
        (INVARIANTS.md, section 7)."""
        inlined: Optional[InlinedFunctionContext] = None
        visited: Set[Context] = {context}
        current = context.parent_context
        while current is not None and current not in visited:
            visited.add(current)
            if isinstance(current, FunctionContext):
                return current, inlined
            if inlined is None and isinstance(current, InlinedFunctionContext):
                inlined = current
            current = current.parent_context
        return None, inlined

    main_ids = {str(f.id) for f in pet_functions if f.name == "main"}
    function_contexts = [c for c in contexts if isinstance(c, FunctionContext)]
    parent_of: Dict[FunctionContext, Tuple[Optional[FunctionContext], Optional[InlinedFunctionContext]]] = {
        c: closest_instance(c) for c in function_contexts
    }

    # keep the instances whose chain of enclosing instances ends in a top-level copy of main
    kept: Dict[FunctionContext, bool] = {}
    for context in function_contexts:
        chain: List[FunctionContext] = []
        current: Optional[FunctionContext] = context
        result = False
        while current is not None:
            if current in kept:
                result = kept[current]
                break
            if current in chain:
                break  # cycle; not kept
            chain.append(current)
            parent, _ = parent_of[current]
            if parent is None:
                result = _function_id_of_instance(current) in main_ids
                break
            current = parent
        for c in chain:
            kept[c] = result

    instances: List[Instance] = []
    for context in function_contexts:
        if not kept.get(context, False):
            continue
        function_id = _function_id_of_instance(context)
        if function_id is None:
            continue
        parent, inlined = parent_of[context]
        instances.append(
            {
                "id": context_ids[context],
                "function": function_id,
                "parent": context_ids[parent] if parent is not None else None,
                "call_instruction_id": (
                    int(inlined.call_instruction_id)
                    if inlined is not None and inlined.call_instruction_id is not None
                    else None
                ),
            }
        )
    instance_contexts = {c for c in function_contexts if kept.get(c, False)}

    work_contexts: Dict[str, int] = {}
    orphaned = 0
    for work_context in contexts:
        if not isinstance(work_context, WorkContext):
            continue
        instance, _ = closest_instance(work_context)
        if instance is None:
            orphaned += 1
            continue
        if instance in instance_contexts:
            work_contexts[str(context_ids[work_context])] = context_ids[instance]
    if orphaned > 0:
        logger.info("Side effect export: %d work contexts belong to no function context", orphaned)

    exported = {c: i for c, i in context_ids.items() if str(i) in work_contexts}
    return instances, work_contexts, exported


class _LineToFunction:
    """Innermost PET function containing a line id."""

    def __init__(self, pet_functions: List[FunctionNode], file_ids: Dict[FunctionNode, int]) -> None:
        self.by_file: Dict[int, List[Tuple[int, int, str]]] = {}
        for f in pet_functions:
            self.by_file.setdefault(file_ids[f], []).append((int(f.start_line), int(f.end_line), str(f.id)))
        self.cache: Dict[str, Optional[str]] = {}

    def lookup(self, line_id: Optional[str]) -> Optional[str]:
        if line_id is None:
            return None
        if line_id in self.cache:
            return self.cache[line_id]
        result: Optional[str] = None
        try:
            file_part, line_part = str(line_id).split(":")[:2]
            file_id, line = int(file_part), int(line_part)
        except ValueError:
            self.cache[line_id] = None
            return None
        best_span: Optional[int] = None
        for start, end, function_id in self.by_file.get(file_id, []):
            if start <= line <= end and (best_span is None or end - start < best_span):
                best_span = end - start
                result = function_id
        self.cache[line_id] = result
        return result

    def functions_starting_at(self, file_id: int, line: int) -> List[str]:
        return [function_id for start, _end, function_id in self.by_file.get(file_id, []) if start == line]


def _read_executed_calls(
    dependency_file: Optional[str], pet_functions: List[FunctionNode], line_to_function: _LineToFunction
) -> List[ExecutedCall]:
    """Executed call edges from the ``BGN func`` and ``START`` records of dynamic_dependencies.txt.

    ``<call site LID> BGN func <callee start LID> <call instruction id>``; when the runtime logged
    no call (callbacks from library code) it prints the last processed instruction as ``0:N``,
    without a fifth column, instead; that instruction id then matches no InlinedFunctionContext.
    Runtimes before the call site was logged as a location wrote every call that way,
    ``<call instr as 0:N> BGN func <callee start LID>``. ``main`` is taken from
    ``START <main start LID>`` only: a
    ``BGN func`` into main (after instrumented global constructors) would make it look partial.
    Functions sharing a start line cannot be told apart; such an edge is recorded for each of them.
    """
    if dependency_file is None or not os.path.exists(dependency_file):
        return []
    instruction_lines: Dict[str, str] = {}
    mappings_file = os.path.join(Path(dependency_file).parent, "instructionID_to_lineID_mapping.txt")
    if os.path.exists(mappings_file):
        with open(mappings_file, "r") as f:
            for line in f:
                split = line.split()
                if len(split) >= 2 and not split[1].startswith("*"):
                    instruction_lines[split[0]] = ":".join(split[1].split(":")[:2])

    def callees_at(lid: str) -> List[str]:
        try:
            file_part, line_part = lid.split(":")[:2]
            return line_to_function.functions_starting_at(int(file_part), int(line_part))
        except ValueError:
            return []

    main_ids = {str(f.id) for f in pet_functions if getattr(f, "name", None) == "main"}
    seen: Set[Tuple[Optional[str], Optional[int], str]] = set()
    calls: List[ExecutedCall] = []

    def add(caller: Optional[str], instruction: Optional[int], callee: str) -> None:
        key = (caller, instruction, callee)
        if key not in seen:
            seen.add(key)
            calls.append({"caller": caller, "call_instruction_id": instruction, "callee": callee})

    with open(dependency_file, "r") as f:
        for line in f:
            split = line.split()
            if len(split) == 2 and split[0] == "START":
                for callee in callees_at(split[1]):
                    add(None, None, callee)
            elif len(split) in (4, 5) and split[1] == "BGN" and split[2] == "func":
                first = split[0]
                instruction: Optional[int] = None
                caller_line: Optional[str] = first
                if len(split) == 5 and split[4].isdigit():
                    # the call site as a location, and the call's instruction id
                    instruction = int(split[4])
                elif first.startswith("0:") and first[2:].isdigit():
                    # an instruction id in place of the call site: the call (older runtimes) or the
                    # instruction last processed before a callback
                    instruction = int(first[2:])
                    caller_line = instruction_lines.get(first[2:])
                # else: a line id without an instruction id
                caller = line_to_function.lookup(caller_line)
                for callee in callees_at(split[3]):
                    if callee not in main_ids:
                        add(caller, instruction, callee)
    return calls


def _performs_file_io(pet: PEGraphX, function: FunctionNode) -> bool:
    for cu_id in function.children_cu_ids or []:
        node = pet.node_at(cu_id)
        if isinstance(node, CUNode) and node.performs_file_io:
            return True
    return False


def _static_callees(pet: PEGraphX, function: FunctionNode) -> List[str]:
    callees: Set[str] = set()
    for cu_id in function.children_cu_ids or []:
        for _source, target, _dep in out_edges(pet, cu_id, EdgeType.CALLSNODE):
            if isinstance(pet.node_at(target), FunctionNode) and target != function.id:
                callees.add(str(target))
    return sorted(callees)


def _demangle(names: Iterable[str]) -> Dict[str, str]:
    """Demangled names, as far as a c++filt is available; one call for all."""
    mangled = sorted({name for name in names if name.startswith("_Z")})
    tool = shutil.which("llvm-cxxfilt") or shutil.which("c++filt")
    if not mangled or tool is None:
        return {}
    try:
        proc = subprocess.run([tool], input="\n".join(mangled), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    readable = proc.stdout.splitlines()
    if proc.returncode != 0 or len(readable) != len(mangled):
        return {}
    return dict(zip(mangled, readable))


# keywords a builtin (non-class) type is spelled with
_BUILTIN_TYPE_WORDS = frozenset(
    {
        "void", "bool", "_Bool", "char", "wchar_t", "char8_t", "char16_t", "char32_t", "short", "int",
        "long", "float", "double", "signed", "unsigned", "__int128", "_Complex", "__fp16", "_Float16",
        "__bf16", "std::nullptr_t", "nullptr_t", "const", "volatile", "restrict", "__restrict",
    }
)  # fmt: skip
# class templates that hold a pointer to memory they do not own (by name, without namespace)
_POINTER_WRAPPERS = frozenset({"shared_ptr", "unique_ptr", "weak_ptr", "span", "basic_string_view", "string_view"})


def _effective_types(type_name: Optional[str], desugared: Optional[str]) -> List[str]:
    """The written type and, if Clang gives one, the type with typedefs and aliases resolved."""
    return [t for t in (type_name, desugared) if t]


def _has_pointer_syntax(type_name: str, with_arrays: bool) -> bool:
    return any(c in type_name for c in ("*&[" if with_arrays else "*&"))


def _without_template_arguments(type_name: str) -> str:
    """'std::vector<int>::iterator' -> 'std::vector::iterator' (nested arguments removed as well)."""
    result: List[str] = []
    depth = 0
    for c in type_name:
        if c == "<":
            depth += 1
        elif c == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            result.append(c)
    return "".join(result)


def _is_pointer_wrapper(type_name: str) -> bool:
    """std::shared_ptr<T>, std::span<T>, iterators, ...: by value, but referring to memory elsewhere."""
    head = _without_template_arguments(type_name).strip().rstrip("&* ")
    for qualifier in ("const ", "volatile ", "struct ", "class "):
        head = head.replace(qualifier, "")
    base = head.strip().rsplit("::", 1)[-1]
    return base in _POINTER_WRAPPERS or "iterator" in base


def _is_class_type(type_name: str, enum_names: Set[str]) -> bool:
    """Class, struct or union type (incl. template specialisations): anything but a builtin or an enum."""
    stripped = type_name.strip()
    for keyword in ("struct ", "class ", "union "):
        if keyword in stripped:
            return True
    if "<" in stripped:
        return True
    words = stripped.replace("const ", " ").replace("volatile ", " ").split()
    if len(words) == 0 or all(w in _BUILTIN_TYPE_WORDS for w in words):
        return False
    if stripped.startswith("enum ") or (len(words) == 1 and words[0].rsplit("::", 1)[-1] in enum_names):
        return False
    return True


def _is_reachable_type(
    type_name: Optional[str], desugared: Optional[str] = None, enum_names: Optional[Set[str]] = None
) -> bool:
    """Type of a parameter through which accesses can reach memory of the caller: a pointer, reference
    or array (also behind a typedef), or a class type passed by value, whose copy may hold pointers
    into the caller's memory (std::shared_ptr, iterators, spans, user structs)."""
    if any(_has_pointer_syntax(t, with_arrays=True) for t in _effective_types(type_name, desugared)):
        return True
    # the resolved type decides: a typedef of int is no class type
    resolved = desugared or type_name
    return resolved is not None and _is_class_type(resolved, enum_names or set())


def _is_top_level_const(type_name: Optional[str]) -> bool:
    """The variable itself is const: "const int", "const int[4]", "int *const" - not "const int *"."""
    if not type_name:
        return False
    type_name = type_name.strip()
    if type_name.endswith("const"):
        return True
    return type_name.startswith("const ") and "*" not in type_name and "&" not in type_name


def _is_pointer_type(type_name: Optional[str], desugared: Optional[str] = None) -> bool:
    """Type of a local through which accesses may reach outside memory: a pointer or reference (also
    behind a typedef) or a well-known pointer wrapper. A local struct or array by value is local storage."""
    types = _effective_types(type_name, desugared)
    return any(_has_pointer_syntax(t, with_arrays=False) or _is_pointer_wrapper(t) for t in types)


class _FunctionFacts:
    def __init__(self) -> None:
        self.found = False
        self.display_name: Optional[str] = None
        self.params: List[Parameter] = []
        self.locals: List[LocalVariable] = []
        self.member_accesses: Dict[str, Dict[str, str]] = {}
        self.global_refs: List[GlobalReference] = []
        self.called_names: Set[str] = set()
        # (name as in called_names, linker name of the called declaration if the AST names it)
        self.calls: Set[Tuple[str, Optional[str]]] = set()


class _AstFacts:
    """Static facts per function from the explorer's AST graph (empty if no AST is available).

    Clang ids are only unique within one translation unit; a referenced id is therefore
    only trusted if the referenced name matches as well.
    """

    def __init__(
        self,
        ast_helper: Optional[ASTPatternDetectionHelper],
        files: Dict[int, str],
        pet_functions: List[FunctionNode],
    ) -> None:
        self.globals: List[GlobalVariable] = []
        # base names of the defined functions, for calls whose declaration is unknown
        self.defined_function_names: Set[str] = set()
        # linker names of the defined functions, for calls whose declaration is known
        self.defined_linker_names: Set[str] = {str(f.name) for f in pet_functions}
        self.enum_names: Set[str] = set()
        # function declaration id -> (name, linker name); Clang ids are only unique within one
        # translation unit, so a call's referenced id is only trusted if its name matches as well
        self._function_decls: Dict[str, Tuple[str, str]] = {}
        self.file_ids_of_functions: Dict[FunctionNode, int] = {}
        self.linker_names: Dict[str, str] = {}
        self._by_mangled: Dict[str, _FunctionFacts] = {}
        self._by_location: Dict[Tuple[int, int], _FunctionFacts] = {}
        # base names of the profiled functions, e.g. "operator[]" of std::vector in a system header
        for f in pet_functions:
            self.defined_function_names.add(_base_name(str(f.name)))
        for readable in _demangle([str(f.name) for f in pet_functions]).values():
            self.defined_function_names.add(_base_name(readable))
        graph = ast_helper.get_ast_graph() if ast_helper is not None else None
        if graph is None:
            return
        self._file_ids = {os.path.realpath(path): file_id for file_id, path in files.items()}
        self._build(graph)

    def unprofiled_calls(self, facts: _FunctionFacts) -> List[str]:
        """Names of the called functions without a definition in the project. A call is matched by the
        linker name of the declaration it refers to where the AST names it, so that a project's
        Logger::write does not hide POSIX write; otherwise by base name."""
        result: Set[str] = set()
        for name, linker_name in facts.calls:
            if linker_name is not None:
                if linker_name not in self.defined_linker_names:
                    result.add(name)
            elif name not in self.defined_function_names:
                result.add(name)
        return sorted(result)

    def function_facts(self, function: FunctionNode) -> _FunctionFacts:
        facts = self._by_mangled.get(str(function.name))
        if facts is None:
            file_id = self.file_ids_of_functions.get(function, int(function.file_id))
            facts = self._by_location.get((file_id, int(function.start_line)))
        return facts if facts is not None else _FunctionFacts()

    def _file_id(self, attrs: Dict[str, Any]) -> Optional[int]:
        loc = attrs.get("loc")
        file_name = loc.get("file") if isinstance(loc, dict) else None
        if not file_name:
            return None
        return self._file_ids.get(os.path.realpath(file_name))

    @staticmethod
    def _line(attrs: Dict[str, Any]) -> Optional[int]:
        loc = attrs.get("loc")
        line = loc.get("line") if isinstance(loc, dict) else None
        return int(line) if isinstance(line, int) else None

    def _build(self, graph: Any) -> None:
        nodes = graph.nodes

        def children(node_id: str) -> List[str]:
            return list(graph.successors(node_id))

        # pass 1: globals (file/namespace scope, static members) and function definitions
        global_ids: Dict[str, str] = {}  # decl id -> name
        function_decls: List[Tuple[str, Dict[str, Any]]] = []
        roots = [n for n in graph.nodes if graph.in_degree(n) == 0]
        stack: List[Tuple[str, bool]] = [(r, False) for r in roots]
        visited: Set[str] = set()
        while stack:
            node_id, in_function = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            attrs = nodes[node_id]
            kind = attrs.get("kind")
            if kind == "VarDecl" and not in_function and attrs.get("name"):
                name = str(attrs["name"])
                global_ids[node_id] = name
                self._add_linker_name(attrs, name)
                self.globals.append({"name": name, "const": _is_top_level_const(attrs.get("type"))})
            if kind == "EnumDecl" and attrs.get("name"):
                self.enum_names.add(str(attrs["name"]))
            if kind in _FUNCTION_DECL_KINDS:
                if attrs.get("name") and attrs.get("mangled_name"):
                    self._function_decls.setdefault(node_id, (str(attrs["name"]), str(attrs["mangled_name"])))
                if any(nodes[c].get("kind") == "CompoundStmt" for c in children(node_id)):
                    function_decls.append((node_id, attrs))
                    if attrs.get("name"):
                        self.defined_function_names.add(str(attrs["name"]))
                    if attrs.get("mangled_name"):
                        self.defined_linker_names.add(str(attrs["mangled_name"]))
                in_function = True
            for child in children(node_id):
                stack.append((child, in_function))
        # one entry per name; a name declared in several translation units is still one global
        unique: Dict[str, GlobalVariable] = {}
        for g in self.globals:
            if g["name"] not in unique:
                unique[g["name"]] = g
            else:
                unique[g["name"]] = {"name": g["name"], "const": unique[g["name"]]["const"] and g["const"]}
        self.globals = [unique[name] for name in sorted(unique)]

        # pass 2: facts per function definition
        for decl_id, decl_attrs in function_decls:
            facts = _FunctionFacts()
            facts.found = True
            facts.display_name = decl_attrs.get("name")
            local_seen: Set[Tuple[str, bool, bool]] = set()
            if decl_attrs.get("kind") != "FunctionDecl":
                facts.params.append({"name": "this", "reachable": True})
            for child in children(decl_id):
                child_attrs = nodes[child]
                if child_attrs.get("kind") == "ParmVarDecl" and child_attrs.get("name"):
                    reachable = _is_reachable_type(
                        child_attrs.get("type"), child_attrs.get("desugared_type"), self.enum_names
                    )
                    facts.params.append({"name": str(child_attrs["name"]), "reachable": reachable})
            body_stack = [c for c in children(decl_id) if nodes[c].get("kind") == "CompoundStmt"]
            seen: Set[str] = set()
            while body_stack:
                node_id = body_stack.pop()
                if node_id in seen:
                    continue
                seen.add(node_id)
                attrs = nodes[node_id]
                kind = attrs.get("kind")
                if kind in _FUNCTION_DECL_KINDS or kind == "LambdaExpr":
                    continue  # nested definitions have facts of their own
                line = self._line(attrs)
                if kind == "VarDecl" and attrs.get("name"):
                    name = str(attrs["name"])
                    if attrs.get("storage_class") == "static" or attrs.get("tls") is not None:
                        self._add_linker_name(attrs, name)
                    pointer = _is_pointer_type(attrs.get("type"), attrs.get("desugared_type"))
                    # static, thread_local and block-scope extern declarations name persistent
                    # state, which is classified like a global
                    static = attrs.get("storage_class") in ("static", "extern") or attrs.get("tls") is not None
                    # every distinct declaration of a name (e.g. in sibling blocks), so that the
                    # analysis can merge them: the profiler's variable names carry no scope
                    if (name, pointer, static) not in local_seen:
                        local_seen.add((name, pointer, static))
                        facts.locals.append({"name": name, "pointer": pointer, "static": static})
                elif kind == "MemberExpr" and attrs.get("name") and line is not None:
                    facts.member_accesses.setdefault(str(line), {})[str(attrs["name"])] = self._member_base(
                        graph, node_id
                    )
                elif kind == "DeclRefExpr" and line is not None:
                    referenced_id = attrs.get("referenced_id")
                    name = attrs.get("referenced_name")
                    if referenced_id in global_ids and global_ids[referenced_id] == name:
                        access = self._access_of(graph, node_id)
                        # x += 1, ++x: a read and a write
                        for single in ("read", "write") if access == "readwrite" else (access,):
                            facts.global_refs.append({"name": str(name), "line": line, "access": single})
                elif kind in ("CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"):
                    callee = self._callee(graph, node_id)
                    if callee is not None:
                        callee_name, declaration_id = callee
                        facts.called_names.add(callee_name)
                        decl = self._function_decls.get(declaration_id) if declaration_id is not None else None
                        # trusted only if the name matches, see self._function_decls
                        linker_name = decl[1] if decl is not None and decl[0] == callee_name else None
                        facts.calls.add((callee_name, linker_name))
                elif kind in ("CXXConstructExpr", "CXXTemporaryObjectExpr"):
                    # the constructor of a class type, e.g. in library code; its name is the class name
                    type_name = str(attrs.get("type") or "")
                    if type_name:
                        constructor = _base_name(_strip_template_arguments(type_name))
                        facts.called_names.add(constructor)
                        facts.calls.add((constructor, None))
                body_stack.extend(children(node_id))
            facts.global_refs = _unique_refs(facts.global_refs)
            mangled = decl_attrs.get("mangled_name")
            if mangled:
                self._by_mangled.setdefault(str(mangled), facts)
            file_id = self._file_id(decl_attrs)
            line = self._line(decl_attrs)
            if file_id is not None and line is not None:
                self._by_location.setdefault((file_id, line), facts)

    def _add_linker_name(self, attrs: Dict[str, Any], name: str) -> None:
        mangled = attrs.get("mangled_name")
        if mangled and mangled != name:
            self.linker_names.setdefault(str(mangled), name)

    @staticmethod
    def _member_base(graph: Any, member_expr: str) -> str:
        """Name of the variable a member is accessed through ("s" in s->x, "this" in x or this->x)."""
        current = member_expr
        for _ in range(16):
            successors = list(graph.successors(current))
            if len(successors) == 0:
                return ""
            current = successors[0]
            kind = graph.nodes[current].get("kind")
            if kind == "CXXThisExpr":
                return "this"
            if kind == "DeclRefExpr":
                return str(graph.nodes[current].get("referenced_name") or "")
            if kind not in ("ImplicitCastExpr", "ParenExpr", "MemberExpr", "ArraySubscriptExpr"):
                return ""
        return ""

    @staticmethod
    def _access_of(graph: Any, decl_ref: str) -> str:
        """Whether a DeclRefExpr is written ("write"), only read ("read"), read and written ("readwrite",
        compound assignments and increments) or neither is clear ("unknown")."""
        child = decl_ref
        # an array decays to a pointer before it is subscripted: the access is decided further up
        decays = "[" in str(graph.nodes[decl_ref].get("type") or "")
        for _ in range(16):
            parents = list(graph.predecessors(child))
            if len(parents) == 0:
                return "unknown"
            parent = parents[0]
            attrs = graph.nodes[parent]
            kind = attrs.get("kind")
            opcode = attrs.get("opcode")
            if kind == "ImplicitCastExpr":
                if not decays:
                    return "read"  # lvalue-to-rvalue conversion
                decays = False  # the array-to-pointer decay; a later cast is a read
                child = parent
                continue
            if kind in ("CompoundAssignOperator",) or (kind == "UnaryOperator" and opcode in ("++", "--")):
                return "readwrite"
            if kind == "BinaryOperator" and opcode == "=":
                operands = list(graph.successors(parent))
                return "write" if len(operands) > 0 and operands[0] == child else "read"
            if kind == "UnaryOperator" and opcode == "&":
                return "unknown"  # address taken: the access happens elsewhere
            if kind in _CALL_KINDS:
                # an argument bound to a reference (a by-value argument is read by the cast above),
                # an array passed as a pointer, or the object of a member call: the callee decides
                return "unknown"
            if kind == "ArraySubscriptExpr":
                decays = False
            if kind not in _TRANSPARENT_KINDS:
                return "read"
            child = parent
        return "unknown"

    @staticmethod
    def _callee(graph: Any, call: str) -> Optional[Tuple[str, Optional[str]]]:
        """Name of the called function and the id of its declaration (None if the AST does not name it)."""
        successors = list(graph.successors(call))
        current = successors[0] if successors else None
        for _ in range(8):
            if current is None:
                return None
            attrs = graph.nodes[current]
            kind = attrs.get("kind")
            if kind == "DeclRefExpr":
                referenced = attrs.get("referenced_name")
                if not referenced:
                    return None
                if attrs.get("referenced_kind") in ("VarDecl", "ParmVarDecl", "FieldDecl"):
                    return f"{referenced} (call through a function pointer)", None
                referenced_id = attrs.get("referenced_id")
                return str(referenced), str(referenced_id) if referenced_id else None
            if kind == "MemberExpr":
                if not attrs.get("name"):
                    return None
                member_id = attrs.get("referenced_member_id")
                return str(attrs["name"]), str(member_id) if member_id else None
            if kind not in ("ImplicitCastExpr", "ParenExpr"):
                return None
            nxt = list(graph.successors(current))
            current = nxt[0] if nxt else None
        return None


def _base_name(name: str) -> str:
    """'ns::Cls::method(int) const' -> 'method'; 'operator[]' stays 'operator[]'."""
    depth = 0
    end = len(name)
    for i, c in enumerate(name):
        if c == "(" and depth == 0 and not name[:i].endswith("operator"):
            end = i
            break
        if c == "<":
            depth += 1
        elif c == ">":
            depth = max(0, depth - 1)
    head = name[:end]
    return head.rsplit("::", 1)[-1] if "::" in head else head


def _strip_template_arguments(type_name: str) -> str:
    """'std::vector<int, std::allocator<int> >' -> 'std::vector'; also drops qualifiers like 'const'."""
    head = type_name.split("<", 1)[0].strip()
    for qualifier in ("const ", "volatile ", "struct ", "class "):
        if head.startswith(qualifier):
            head = head[len(qualifier) :]
    return head.rstrip("&* ")


def _unique_refs(refs: List[GlobalReference]) -> List[GlobalReference]:
    seen: Set[Tuple[str, int, str]] = set()
    unique: List[GlobalReference] = []
    for ref in sorted(refs, key=lambda r: (r["name"], r["line"], r["access"])):
        key = (ref["name"], ref["line"], ref["access"])
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique
