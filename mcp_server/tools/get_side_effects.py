# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""get_side_effects: the data a function was observed to read and write outside of itself.

The analysis (discopop_explorer.side_effects.analysis) returns every effect, unranked
and uncut; this tool ranks and cuts them and words the most significant ones as text
for an agent. See design/get_side_effects.md, section 3.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools.helpers import ToolContext
from mcp_server.tools.hotspot_text import display_path, resolve_source_path

if TYPE_CHECKING:
    # imported for annotations only: the server starts without discopop_explorer installed
    from discopop_explorer.side_effects.result import Effect, EffectSite, FunctionInfo, OutsideName, SideEffects

logger = logging.getLogger("discopop-mcp")

TOOL_NAME = "get_side_effects"

# A function high up in the call tree (main, a solver driver) can touch hundreds of
# globals and buffers; beyond this many entries the answer costs more than it helps.
DEFAULT_LIMIT = 20
# Sites listed per entry; the rest is counted.
MAX_SITES = 3
# Names listed in a sentence (unprofiled calls, written names of the verdict).
MAX_LISTED = 5
# Candidates listed for an ambiguous name.
MAX_CANDIDATES = 20

# Ranking order, see _rank_key.
_ACCESS_RANK = {"write": 0, "read": 1, "unknown": 2}
_KIND_RANK = {"global": 0, "parameter": 1, "other": 2}
_SOURCE_RANK = {"observed": 0, "static": 1}
_KIND_TEXT = {"global": "global", "parameter": "parameter", "other": "other memory"}

PROFILED_INPUTS_NOTE = "Valid for the profiled inputs only."
# Only added if the analysis' own note on missing source-level facts is absent.
NO_AST_NOTE = (
    "No source-level facts are available for this function or a callee, so its names could not be classified "
    "and are reported as other memory."
)
_NO_AST_NOTE_MARKER = "No source-level"

COVERAGE_TEXT = {
    "not_executed": (
        "Never executed during profiling: only globals it references in the code are listed, and absent effects "
        "mean nothing. Run gather_data with an execution configuration whose input calls it to observe it."
    ),
    "untracked": (
        "Executed, but none of its calls could be attributed to it (e.g. called through a function pointer, from "
        "library code, or nested deeper than the analysis follows calls), so no observed effect is reported and "
        "absent effects are unknown; only globals it references in the code are listed."
    ),
    "partial": (
        "Some calls could not be followed (e.g. recursion, deep call chains, function pointers) or some accesses "
        "could not be attributed, so effects may be missing and absent effects are unknown."
    ),
}

TOOL = Tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Describe the data a C/C++ function was observed to read and write outside of itself during "
        "profiling, including through the functions it calls: globals (also static locals and static "
        "members), memory reached through its pointer, reference, array or class-type parameters, and other "
        "memory that outlives the call. Use it to judge whether a call is pure, safe to run concurrently, to "
        "reorder or to memoize, e.g. during a review or a refactoring.\n\n"
        "The answer is a text: whether the function is pure on the profiled inputs, then its writes and reads, "
        "writes first, each with its name, kind, the lines of the accesses and, for an access in a called "
        "function, the call chain (via). A name is the one at the access; the caller's name for the same data "
        "is given as 'also called', with its file when that differs from the function's. "
        "'referenced in the code' marks data the code names but profiling did not "
        "observe. Caveats say what profiling cannot see (functions never executed, calls it could not "
        "follow, library code), as then absent effects are unknown, not absent.\n\n"
        f"By default the first {DEFAULT_LIMIT} effects are listed (most significant first), and the last line says "
        "how many are not; raise limit for more.\n\n"
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
                "description": "Source file of the definition (absolute, or relative to project_path), to "
                "disambiguate.",
            },
            "line": {
                "type": "integer",
                "description": "Any line inside the function's definition, to disambiguate.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of effects to list. Default: {DEFAULT_LIMIT}.",
            },
        },
        "required": ["project_path", "function"],
        "additionalProperties": False,
    },
)


def _same_file(a: Optional[str], b: Path) -> bool:
    if a is None:
        return False
    try:
        return Path(a).resolve() == b
    except OSError:
        return False


def _place(project_path: str, info: FunctionInfo) -> str:
    path = display_path(project_path, Path(info.file) if info.file else None)
    return f"{info.display_name} ({path}:{info.start_line}-{info.end_line})"


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


def _site_text(site: EffectSite, function: FunctionInfo, files: dict[int, Optional[str]], project_path: str) -> str:
    """'line 12', 'util.h:7' for another file; 'via a > b' for an access in a called function."""
    if site.file_id != function.file_id and files.get(site.file_id):
        text = f"{display_path(project_path, Path(str(files[site.file_id])))}:{site.line}"
    else:
        text = f"line {site.line}"
    if site.via:
        text += f" via {' > '.join(_collapse_via(site.via))}"
    return text


def _outside_text(
    outside: OutsideName, function: FunctionInfo, files: dict[int, Optional[str]], project_path: str
) -> str:
    """The other name; 'pos (in util.h)' when it is used in another file than the function's."""
    if outside.file_id != function.file_id and files.get(outside.file_id):
        return f"{outside.name} (in {display_path(project_path, Path(str(files[outside.file_id])))})"
    return outside.name


def _effect_text(effect: Effect, function: FunctionInfo, files: dict[int, Optional[str]], project_path: str) -> str:
    qualifiers = [_KIND_TEXT.get(effect.kind, effect.kind)]
    if effect.through_pointer:
        qualifiers.append("through pointer")
    if effect.source == "static":
        qualifiers.append("referenced in the code, not observed")
    if effect.member_of:
        qualifiers.append(f"member of {effect.member_of}")
    text = f"{effect.name} ({', '.join(qualifiers)})"
    if effect.outside_names:
        aliases = [_outside_text(outside, function, files, project_path) for outside in effect.outside_names]
        text += f", also called {', '.join(aliases)}"
    # the function's own sites first, then its file, then by line
    sites = sorted(effect.sites, key=lambda s: (len(s.via), s.file_id != function.file_id, s.file_id, s.line, s.via))
    listed = [_site_text(site, function, files, project_path) for site in sites[:MAX_SITES]]
    if len(sites) > MAX_SITES:
        listed.append(f"{len(sites) - MAX_SITES} more")
    return f"{text}: {'; '.join(listed)}"


def _names(names: list[str]) -> str:
    shown = names[:MAX_LISTED]
    return ", ".join(shown) + (f" and {len(names) - len(shown)} more" if len(names) > len(shown) else "")


def _verdict(effects: SideEffects) -> str:
    written = sorted({effect.name for effect in effects.effects if effect.access == "write"})
    if effects.pure_on_observed_inputs is True:
        return "Pure on the profiled inputs: it writes nothing and reads only its own parameters or constants."
    if effects.pure_on_observed_inputs is False:
        reasons = ([f"it writes {_names(written)}"] if written else []) + (
            ["it performs file I/O"] if effects.performs_file_io else []
        )
        return f"Not pure: {' and '.join(reasons)}." if reasons else "Not pure."
    return "Purity is undecided." + (" It performs file I/O." if effects.performs_file_io else "")


def build_text(
    project_path: str,
    effects: SideEffects,
    files: Optional[dict[int, Optional[str]]] = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """The tool's answer for one function: ranked, cut and worded."""
    function = effects.function
    files = dict(files or {})
    files.setdefault(function.file_id, function.file)

    ranked = sorted(effects.effects, key=_rank_key)
    shown = ranked[: max(limit, 0)]

    lines = [_place(project_path, function), _verdict(effects)]
    sections = (("write", "Writes:"), ("read", "Reads:"), ("unknown", "Referenced in the code, access unknown:"))
    for access, title in sections:
        entries = [effect for effect in shown if effect.access == access]
        if entries:
            lines.append(title)
            lines += [f"- {_effect_text(effect, function, files, project_path)}" for effect in entries]
    if not ranked:
        lines.append("No effects." if effects.coverage == "executed" else "No effects are known.")
    if len(shown) < len(ranked):
        lines.append(f"{len(ranked) - len(shown)} more effects not shown (limit={limit}); pass a larger limit.")

    if effects.coverage in COVERAGE_TEXT:
        lines.append(f"Caveat: {COVERAGE_TEXT[effects.coverage]}")
    if effects.unprofiled_calls:
        calls = list(effects.unprofiled_calls)
        lines.append(f"Caveat: calls whose accesses were not observed (library code): {_names(calls)}.")
    notes = [note for note in effects.notes if note != PROFILED_INPUTS_NOTE]
    if not effects.ast_facts and not any(note.startswith(_NO_AST_NOTE_MARKER) for note in effects.notes):
        notes.append(NO_AST_NOTE)
    lines += [f"Note: {note}" for note in dict.fromkeys(notes)]
    lines.append(PROFILED_INPUTS_NOTE)
    return "\n".join(lines)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        function_name: str = str(arguments.get("function", "") or "").strip()
        file_path: Optional[str] = arguments.get("file_path") or None
        line_arg = arguments.get("line")
        line: Optional[int] = int(line_arg) if line_arg is not None else None
        limit = max(int(arguments.get("limit", DEFAULT_LIMIT)), 0)

        if not function_name:
            return ctx.error("function must name a function.", project_path, TOOL_NAME)

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
            wanted = resolve_source_path(project_path, file_path)
            narrowed = [info for info in narrowed if _same_file(info.file, wanted)]
        if line is not None:
            narrowed = [info for info in narrowed if info.start_line <= line <= info.end_line]
        if not narrowed:
            where = " and ".join(
                part
                for part in (f"in {file_path}" if file_path else "", f"at line {line}" if line is not None else "")
                if part
            )
            definitions = "; ".join(_place(project_path, info) for info in candidates[:MAX_CANDIDATES])
            return ctx.error(
                f"No definition of '{function_name}' {where}. Definitions: {definitions}.",
                project_path,
                TOOL_NAME,
                next_step="Pass the file_path and line of one of the definitions.",
            )
        if len(narrowed) > 1:
            listed = [f"- {_place(project_path, info)}" for info in narrowed[:MAX_CANDIDATES]]
            text = "\n".join(
                [f"'{function_name}' matches {len(narrowed)} functions:"]
                + listed
                + [
                    "Call again with the full signature as function, or with file_path and a line inside the "
                    "definition of the one you mean."
                ]
            )
            return [TextContent(type="text", text=text)]

        effects = index.compute(narrowed[0].id)
        text = build_text(project_path, effects, _file_table(index), limit)
        ctx.log_action(project_path, TOOL_NAME, f"Described the side effects of {narrowed[0].display_name}")
        return [TextContent(type="text", text=text)]

    except Exception as e:
        error_msg = f"Error computing side effects: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ctx.error(error_msg, arguments.get("project_path", ""), TOOL_NAME)


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
