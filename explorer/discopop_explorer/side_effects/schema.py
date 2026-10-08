# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Format of the side effect export (``.discopop/explorer/side_effects.json.gz``).

Written by ``export.write_export`` at the end of an explorer run, read by
``load_export``. The writer and the reader share this module so that the format
cannot drift; bump ``FORMAT_VERSION`` on every incompatible change.

Ids: functions are identified by their PET function node id (``"1:5"``),
function instances and work contexts by integers local to one export, and
instructions by the profiler's instruction ids (as ``int``). Lines are LineIDs
(``"<file id>:<line>"``).
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypedDict, Union

FORMAT_VERSION = 1
EXPORT_FILE_NAME = "side_effects.json.gz"

# The dependency types the export carries. The access kind of each end follows from
# the type: the first-column instruction is a write for INIT, WAR and WAW and a read
# for RAW; the other end is a write for RAW and WAW and a read for WAR.
RECORD_TYPES = ("RAW", "WAR", "WAW", "INIT")


def export_path(project_path: Union[str, Path]) -> Path:
    """Location of the export inside a project."""
    return Path(project_path) / ".discopop" / "explorer" / EXPORT_FILE_NAME


class DependencyFileInfo(TypedDict):
    """mtime and size of the dynamic_dependencies.txt the export was built from, to detect a stale export."""

    mtime: float
    size: int


class GlobalVariable(TypedDict):
    # display name, as it appears in the profiler's variable names
    name: str
    # const-qualified: reading it does not depend on mutable state
    const: bool


class Parameter(TypedDict):
    name: str
    # pointer, reference or array type (also behind a typedef), a class type passed by value (its copy
    # may hold pointers into the caller's memory, e.g. std::shared_ptr, iterators, user structs), or
    # ``this``: accesses through it can reach the caller's memory
    reachable: bool


class LocalVariable(TypedDict):
    """A local declaration. A name declared more than once (e.g. in sibling blocks) has one entry per
    distinct declaration; the reader merges them (pointer and static win)."""

    name: str
    # pointer, reference or array-of-pointer type (also behind a typedef), or a pointer wrapper such as
    # std::shared_ptr, std::span or an iterator: accesses through it may reach outside memory. A local
    # struct or array by value is local storage
    pointer: bool
    # static or thread_local storage: persistent state, classified like a global
    static: bool


class GlobalReference(TypedDict):
    """A reference to a global in the function body, from the AST (static fallback)."""

    name: str
    line: int
    # "read", "write" or "unknown" (address taken, argument bound to a reference, object of a member call)
    access: str


class Function(TypedDict):
    # PET function node id
    id: str
    # name as in the PET (usually mangled)
    name: str
    # demangled name with signature, e.g. "write_global(int)"; equal to ``name`` if unknown
    display_name: str
    file_id: int
    start_line: int
    end_line: int
    # the AST knows this function; if false, params/locals/member_accesses/global_refs are empty
    ast_facts: bool
    params: List[Parameter]
    locals: List[LocalVariable]
    # line (as string) -> member name -> name of the MemberExpr's base (or "" if not a plain name)
    member_accesses: Dict[str, Dict[str, str]]
    performs_file_io: bool
    # PET function node ids of the functions called in the body (static call graph)
    static_callees: List[str]
    # names of called functions that have no definition in the project; a call is matched by the linker
    # name of the declaration it refers to where the AST names it, by base name otherwise
    unprofiled_calls: List[str]
    global_refs: List[GlobalReference]
    # the profiling run executed this function (BGN func / START records)
    executed: bool


class Instance(TypedDict):
    """A FunctionContext copy of a function in the TaskGraph."""

    id: int
    # PET function node id
    function: str
    # closest enclosing instance, None for main's top-level instance
    parent: Optional[int]
    # call instruction of the enclosing InlinedFunctionContext, None for main
    call_instruction_id: Optional[int]


# [instruction id, state id, line id]
RecordEnd = Tuple[int, int, str]


class Record(TypedDict):
    """One dynamic dependency of the profiler, mapped to work contexts."""

    # one of RECORD_TYPES
    type: str
    # the variable name at the first-column instruction
    var: str
    # the first-column end of the profiler's line (the later access, Dependency.sink_line)
    first: RecordEnd
    # the other end; None for INIT
    other: Optional[RecordEnd]
    # (first work context, other work context) pairs, filtered exactly like the edges of the
    # TaskGraph's dependency insertion (same lookup, same-state rule); empty for INIT. Used to
    # decide whether a record crosses a function instance.
    pairs: List[Tuple[int, int]]
    # work contexts each end maps to on its own (no same-state filter), for the per-access rules;
    # an end that matched no exported context has an empty list
    first_contexts: List[int]
    other_contexts: List[int]


class ExecutedCall(TypedDict):
    # PET function node id of the calling function, None if unknown
    caller: Optional[str]
    # call instruction id of the BGN func record (its fifth column; the first one in older runtimes);
    # None for main's START record. When the runtime logged no call (callbacks from library code) it
    # prints the last processed instruction instead, which then matches no InlinedFunctionContext
    call_instruction_id: Optional[int]
    # PET function node id of the callee
    callee: str


class SideEffectExport(TypedDict):
    format_version: int
    discopop_version: str
    # always false since the explorer writes no export with --ignore-dependency-states; kept for readers
    ignore_dependency_states: bool
    dependency_file: Optional[DependencyFileInfo]
    # file id (as string) -> absolute path
    files: Dict[str, str]
    globals: List[GlobalVariable]
    functions: List[Function]
    instances: List[Instance]
    # work context id (as string) -> instance id
    work_contexts: Dict[str, int]
    records: List[Record]
    # instruction id (as string) -> variable names recorded with it as first column
    instruction_names: Dict[str, List[str]]
    executed_calls: List[ExecutedCall]
    # PET function node id -> number of record ends located in the function that matched no work context
    unmapped_records: Dict[str, int]
    # linker name -> source name of variables the profiler records under their linker name
    # (function-static locals, static data members), e.g. "_ZZ11count_callsvE5calls" -> "calls"
    linker_names: Dict[str, str]


class ExportFormatError(Exception):
    """The export is missing, unreadable, or written in another format version."""


def dependency_file_info(dependency_file: Union[str, Path]) -> Optional[DependencyFileInfo]:
    try:
        stat = os.stat(dependency_file)
    except OSError:
        return None
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def save_export(export: SideEffectExport, path: Union[str, Path]) -> None:
    """Write the export atomically, so a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(export, f, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_export(path: Union[str, Path]) -> SideEffectExport:
    """Read an export; raises ExportFormatError if it is missing, unreadable or of another format version."""
    path = Path(path)
    if not path.exists():
        raise ExportFormatError(f"{path} does not exist")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ExportFormatError(f"{path} is not readable: {e}") from e
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        found = data.get("format_version") if isinstance(data, dict) else None
        raise ExportFormatError(f"{path} has format version {found}, expected {FORMAT_VERSION}")
    return data  # type: ignore[return-value]
