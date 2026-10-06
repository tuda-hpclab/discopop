# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""get_side_effects: the data a function was observed to read and write outside of itself.

The analysis (discopop_explorer.side_effects.analysis) returns every effect, unranked
and uncut; this tool filters, ranks, cuts and words them for an agent. See
DESIGN_get_side_effects.md, section 3.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools.helpers import ToolContext

if TYPE_CHECKING:
    # imported for annotations only: the server starts without discopop_explorer installed
    from discopop_explorer.side_effects.result import Effect, EffectSite, FunctionInfo, SideEffects

logger = logging.getLogger("discopop-mcp")

TOOL_NAME = "get_side_effects"

# A function high up in the call tree (main, a solver driver) can touch hundreds of
# globals and buffers; beyond this many entries the answer costs more than it helps.
MAX_EFFECTS = 100
# Sites listed per entry; more when var_name asks for one variable. num_sites has the total.
MAX_SITES = 3
MAX_VAR_SITES = 50
# Entries of summary.contributing_callees and of unprofiled_calls; num_* fields have the totals.
MAX_LISTED = 20
# Candidates listed for an ambiguous name.
MAX_CANDIDATES = 20

ACCESSES = ("read", "write")
KINDS = ("global", "parameter", "other")
# Ranking order, see _rank_key.
_ACCESS_RANK = {"write": 0, "read": 1, "unknown": 2}
_KIND_RANK = {"global": 0, "parameter": 1, "other": 2}
_SOURCE_RANK = {"observed": 0, "static": 1}
# Output list per access; "unknown" holds statically found references whose access could not be derived.
_BUCKETS = {"write": "writes", "read": "reads", "unknown": "unknown_access"}

PROFILED_INPUTS_NOTE = (
    "Effects were observed on the profiled inputs only; other inputs can reach other code and data. "
    "Accesses inside library code that was not compiled with DiscoPoP are not observed (see unprofiled_calls)."
)
# Only added if the analysis' own note on missing source-level facts is absent.
NO_AST_NOTE = (
    "No source-level facts are available for this function or a contributing callee, so its names "
    "could not be classified and are reported as kind 'other'."
)
_NO_AST_NOTE_MARKER = "No source-level"

COVERAGE_NEXT_STEPS = {
    "not_executed": (
        "The profiling run never executed this function, so only globals it references in the code "
        "(source 'static') are listed, and absent effects mean nothing. To observe it, run gather_data "
        "with an execution configuration whose input calls it."
    ),
    "untracked": (
        "The function was executed, but none of its calls could be attributed to it (e.g. called through "
        "a function pointer, from library code, or nested deeper than the analysis follows calls), so no "
        "observed effect is reported; only globals it references in the code are listed. Treat absent "
        "effects as unknown; get_data_dependencies on the function's line range shows the raw observed "
        "dependencies."
    ),
    "partial": (
        "Some calls of this function, or of functions it calls, could not be followed (e.g. recursion, "
        "deep call chains, function pointers), or some recorded accesses could not be attributed to a call "
        "(unmapped_records), so effects may be missing. Treat absent effects as unknown; "
        "get_data_dependencies on the line range of interest shows the raw observed dependencies."
    ),
}

TOOL = Tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Return the data a C/C++ function was observed to read and write outside of itself during "
        "profiling, including through the functions it calls: globals (also static locals and static "
        "members), memory reached through its pointer, reference, array or class-type parameters, and other "
        "memory that outlives the call. Use it to judge whether a call is pure, safe to run concurrently, to "
        "reorder or to memoize, e.g. during a review or a refactoring.\n\n"
        "Effects are split into writes and reads (unknown_access: static references of unknown access). "
        "Each entry has name, kind (global, parameter, other), source (observed, or static: referenced in "
        "the code, not observed), through_pointer and sites with line and via, the call chain to the "
        "function containing the access (null: the function itself; recursion shown as 'f(int) x5'). "
        "Names are those at the access: a parameter reached through a callee has the parameter name of the "
        "last via function. outside_names are other names of the same data, e.g. the caller's argument.\n\n"
        "coverage: executed, partial, untracked or not_executed; anything but executed means absent effects "
        "are unknown, not absent. pure_on_observed_inputs: true = no writes, and reads only through its own "
        "parameters or of constants (for memoizing, the pointed-to contents belong to the key); false = an "
        "observed write or file I/O; null = undecided. performs_file_io and unprofiled_calls (calls whose "
        "accesses were not observed) flag what profiling cannot see; unmapped_records counts recorded "
        "accesses in the function or its callees that could not be attributed to a call (coverage is then "
        "partial).\n\n"
        "Order: writes before reads; global, parameter, other; own accesses before callees', shallower "
        f"first; observed before static; by name. At most {MAX_EFFECTS} entries and {MAX_SITES} sites each "
        f"({MAX_VAR_SITES} with var_name); num_* fields give totals, summary counts every match, "
        "truncated=true marks a cut.\n\n"
        "Valid only for the profiled inputs. Requires gather_data. Cheap: cached after the first load."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "function": {
                "type": "string",
                "description": (
                    "Function name, with or without signature ('scale', 'scale(double*, int)', "
                    "'ns::Cls::scale'), or its mangled name."
                ),
            },
            "file_path": {
                "type": "string",
                "description": "Source file of the definition (absolute, or relative to project_path), to disambiguate.",
            },
            "line": {
                "type": "integer",
                "description": "Any line inside the function's definition, to disambiguate.",
            },
            "access": {
                "type": "string",
                "enum": list(ACCESSES),
                "description": (
                    "Only return reads or only writes. Entries of unknown access are kept with either. "
                    "Default: both."
                ),
            },
            "kinds": {
                "type": "array",
                "items": {"type": "string", "enum": list(KINDS)},
                "description": "Kinds of data to return. Default: all.",
            },
            "var_name": {
                "type": "string",
                "description": (
                    "Only return entries for this name (also matched against member_of and outside_names), "
                    f"with up to {MAX_VAR_SITES} sites each."
                ),
            },
            "include_callees": {
                "type": "boolean",
                "description": "Also report accesses made by called functions. Default: true.",
            },
        },
        "required": ["project_path", "function"],
        "additionalProperties": False,
    },
)


def _strip_prefix(name: str) -> str:
    return name[len("GEPRESULT_") :] if name.startswith("GEPRESULT_") else name


def _same_file(a: Optional[str], b: Path) -> bool:
    if a is None:
        return False
    try:
        return Path(a).resolve() == b
    except OSError:
        return False


def _candidate(info: FunctionInfo) -> dict[str, Any]:
    return {"name": info.display_name, "file": info.file, "start_line": info.start_line, "end_line": info.end_line}


def _matches_var(effect: Effect, var_name: str) -> bool:
    wanted = _strip_prefix(var_name)
    names = [effect.name] + ([effect.member_of] if effect.member_of else []) + list(effect.outside_names)
    return any(_strip_prefix(name) == wanted for name in names)


def _filter(
    effects: list[Effect],
    access: Optional[str],
    kinds: set[str],
    var_name: Optional[str],
    include_callees: bool,
) -> list[Effect]:
    """The effects matching the filters; without callees, only the sites in the function itself remain."""
    matched: list[Effect] = []
    for effect in effects:
        # an entry of unknown access may be either, so it is kept by both access filters
        if access is not None and effect.access not in (access, "unknown"):
            continue
        if effect.kind not in kinds:
            continue
        if var_name is not None and not _matches_var(effect, var_name):
            continue
        if not include_callees:
            own_sites = [site for site in effect.sites if not site.via]
            if not own_sites:
                continue
            effect = dataclasses.replace(effect, sites=own_sites)
        matched.append(effect)
    return matched


def _rank_key(effect: Effect) -> tuple[Any, ...]:
    """writes before reads; global > parameter > other; own before callee, shallower callee first;
    observed before static; then name."""
    return (
        _ACCESS_RANK.get(effect.access, len(_ACCESS_RANK)),
        _KIND_RANK.get(effect.kind, len(_KIND_RANK)),
        0 if effect.is_own else 1,
        effect.min_via_depth,
        _SOURCE_RANK.get(effect.source, len(_SOURCE_RANK)),
        effect.name,
        effect.member_of or "",
    )


def _collapse_via(via: tuple[str, ...]) -> list[str]:
    """Runs of the same function (recursion) as one element: ('r(int)',) * 5 -> ['r(int) x5']."""
    collapsed: list[str] = []
    i = 0
    while i < len(via):
        j = i
        while j + 1 < len(via) and via[j + 1] == via[i]:
            j += 1
        count = j - i + 1
        collapsed.append(via[i] if count == 1 else f"{via[i]} x{count}")
        i = j + 1
    return collapsed


def _site(site: EffectSite, function: FunctionInfo, files: dict[int, Optional[str]]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if site.file_id != function.file_id:
        entry["file"] = files.get(site.file_id)
    entry["line"] = site.line
    entry["via"] = _collapse_via(site.via) if site.via else None
    return entry


def _entry(effect: Effect, function: FunctionInfo, files: dict[int, Optional[str]], max_sites: int) -> dict[str, Any]:
    # the function's own sites first, then its file, then by line
    sites = sorted(effect.sites, key=lambda s: (len(s.via), s.file_id != function.file_id, s.file_id, s.line, s.via))
    shown = sites[:max_sites]
    entry: dict[str, Any] = {
        "name": effect.name,
        "kind": effect.kind,
        "through_pointer": effect.through_pointer,
        "source": effect.source,
    }
    if effect.member_of:
        entry["member_of"] = effect.member_of
    entry["num_sites"] = len(sites)
    entry["sites"] = [_site(site, function, files) for site in shown]
    if effect.outside_names:
        entry["outside_names"] = list(effect.outside_names)
    return entry


def _summary(matched: list[Effect]) -> dict[str, Any]:
    by_access = {"write": 0, "read": 0, "unknown": 0}
    by_kind = {kind: 0 for kind in KINDS}
    callees: set[str] = set()
    for effect in matched:
        by_access[effect.access] = by_access.get(effect.access, 0) + 1
        by_kind[effect.kind] = by_kind.get(effect.kind, 0) + 1
        callees.update(site.via[-1] for site in effect.sites if site.via)
    return {
        "num_effects": len(matched),
        "by_access": by_access,
        "by_kind": by_kind,
        "num_contributing_callees": len(callees),
        "contributing_callees": sorted(callees)[:MAX_LISTED],
    }


def _resolve_file(project_path: str, file_path: str) -> Path:
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(project_path) / path
    return path.resolve()


def build_result(
    project_path: str,
    effects: SideEffects,
    access: Optional[str] = None,
    kinds: Optional[set[str]] = None,
    var_name: Optional[str] = None,
    include_callees: bool = True,
    files: Optional[dict[int, Optional[str]]] = None,
) -> dict[str, Any]:
    """The tool's answer for one function: filtered, ranked, cut and worded."""
    function = effects.function
    files = dict(files or {})
    files.setdefault(function.file_id, function.file)

    matched = _filter(effects.effects, access, kinds or set(KINDS), var_name, include_callees)
    matched.sort(key=_rank_key)
    shown = matched[:MAX_EFFECTS]

    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in _BUCKETS.values()}
    for effect in shown:
        buckets[_BUCKETS.get(effect.access, "unknown_access")].append(
            _entry(effect, function, files, MAX_VAR_SITES if var_name is not None else MAX_SITES)
        )

    notes = [PROFILED_INPUTS_NOTE]
    for note in effects.notes:
        if note not in notes:
            notes.append(note)
    if not effects.ast_facts and not any(note.startswith(_NO_AST_NOTE_MARKER) for note in effects.notes):
        notes.append(NO_AST_NOTE)

    result: dict[str, Any] = {
        "status": "success",
        "project_path": project_path,
        "function": {
            "name": function.display_name,
            "file": function.file,
            "start_line": function.start_line,
            "end_line": function.end_line,
        },
        "coverage": effects.coverage,
        "pure_on_observed_inputs": effects.pure_on_observed_inputs,
        "performs_file_io": effects.performs_file_io,
        "num_unprofiled_calls": len(effects.unprofiled_calls),
        "unprofiled_calls": list(effects.unprofiled_calls)[:MAX_LISTED],
        "unmapped_records": effects.unmapped_records,
        "summary": _summary(matched),
        "writes": buckets["writes"],
        "reads": buckets["reads"],
    }
    if buckets["unknown_access"]:
        result["unknown_access"] = buckets["unknown_access"]
    result["truncated"] = len(matched) > len(shown)
    result["notes"] = notes

    next_steps: list[str] = []
    if result["truncated"]:
        next_steps.append(
            f"Only the first {MAX_EFFECTS} of {len(matched)} entries are listed (writes first, then by kind, "
            "own accesses before those of callees). To see the rest, narrow the query with access, kinds, "
            "var_name or include_callees=false."
        )
    coverage_step = COVERAGE_NEXT_STEPS.get(effects.coverage)
    if coverage_step:
        next_steps.append(coverage_step)
    if next_steps:
        result["next_step"] = " ".join(next_steps)
    return result


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        function_name: str = str(arguments.get("function", "") or "").strip()
        file_path: Optional[str] = arguments.get("file_path") or None
        line_arg = arguments.get("line")
        line: Optional[int] = int(line_arg) if line_arg is not None else None
        access: Optional[str] = arguments.get("access") or None
        # An omitted or empty list means "no restriction".
        kinds: set[str] = set(arguments.get("kinds") or KINDS)
        var_name: Optional[str] = arguments.get("var_name") or None
        include_callees: bool = bool(arguments.get("include_callees", True))

        if not function_name:
            return ctx.error("function must name a function.", project_path, TOOL_NAME)
        if access is not None and access not in ACCESSES:
            return ctx.error(f"access must be one of {list(ACCESSES)}, not {access!r}.", project_path, TOOL_NAME)
        unknown_kinds = sorted(kinds - set(KINDS))
        if unknown_kinds:
            return ctx.error(f"Unknown kinds {unknown_kinds}; known: {list(KINDS)}.", project_path, TOOL_NAME)

        index, problem = ctx.get_side_effect_index(project_path)
        if index is None:
            message = problem.message if problem else "No side effect data found for this project."
            next_step = problem.next_step if problem else "Run gather_data first."
            return ctx.error(message, project_path, TOOL_NAME, next_step=next_step)

        # Narrowed here rather than by find_functions, so that a file or line that excludes
        # every definition can name the definitions that exist.
        candidates = index.find_functions(function_name)
        if not candidates:
            return ctx.error(
                f"No profiled function named '{function_name}'.",
                project_path,
                TOOL_NAME,
                next_step=(
                    "Check the spelling: names are matched with or without signature ('f', 'f(int)'), "
                    "qualified as 'ns::f', or mangled. Only functions in files compiled with DiscoPoP's "
                    "instrumentation are known."
                ),
            )
        narrowed = candidates
        if file_path is not None:
            wanted = _resolve_file(project_path, file_path)
            narrowed = [info for info in narrowed if _same_file(info.file, wanted)]
        if line is not None:
            narrowed = [info for info in narrowed if info.start_line <= line <= info.end_line]
        if not narrowed:
            where = " and ".join(
                part
                for part in (f"in {file_path}" if file_path else "", f"at line {line}" if line is not None else "")
                if part
            )
            message = f"No definition of '{function_name}' {where}. Definitions: " + json.dumps(
                [_candidate(info) for info in candidates[:MAX_CANDIDATES]]
            )
            return ctx.error(
                message, project_path, TOOL_NAME, next_step="Pass the file_path and line of one of the definitions."
            )
        if len(narrowed) > 1:
            result: dict[str, Any] = {
                "status": "ambiguous",
                "project_path": project_path,
                "message": f"'{function_name}' matches {len(narrowed)} functions.",
                "num_candidates": len(narrowed),
                "candidates": [_candidate(info) for info in narrowed[:MAX_CANDIDATES]],
                "next_step": (
                    "Call again with the full signature as function, or with file_path and a line inside "
                    "the definition of the one you mean."
                ),
            }
            ctx.log_response(TOOL_NAME, result)
            return [TextContent(type="text", text=json.dumps(result))]

        effects = index.compute(narrowed[0].id)
        files = _file_table(index)
        result = build_result(project_path, effects, access, kinds, var_name, include_callees, files)
        ctx.log_response(TOOL_NAME, result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error computing side effects: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]


def _file_table(index: Any) -> dict[int, Optional[str]]:
    """file id -> path, from the export the index was built from (for sites in other files)."""
    export = getattr(index, "export", None)
    raw = export.get("files", {}) if isinstance(export, dict) else {}
    table: dict[int, Optional[str]] = {}
    for key, path in raw.items():
        try:
            table[int(key)] = path
        except (TypeError, ValueError):
            continue
    return table
