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
THREAD_LOCAL_NOTE = (
    "Thread-local data (thread_local storage) exists once per thread: each thread accesses its own copy."
)
# the coverage of a copy of a definition, best first, to pick the copy whose place describes the merged copies
_COVERAGE_RANK = {"executed": 3, "partial": 2, "untracked": 1, "not_executed": 0}
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
    kind = _KIND_TEXT.get(effect.kind, effect.kind)
    qualifiers = ["thread-local " + kind if getattr(effect, "thread_local", False) else kind]
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
    if any(getattr(effect, "thread_local", False) for effect in shown):
        notes.append(THREAD_LOCAL_NOTE)
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
        copies_note = ""
        merged: Optional[SideEffects] = None
        if len(narrowed) > 1 and _copies_of_one_definition(narrowed):
            # e.g. an inline or template function of a header, compiled into several files: one definition in the
            # source, so the agent cannot pick one. Each copy saw other calls: described is what any copy did.
            merged = merge_copies([index.compute(info.id) for info in narrowed])
            copies_note = (
                f"Note: the definition was compiled {len(narrowed)} times (e.g. a header included by several files); "
                "described are the effects of all copies together."
            )
            narrowed = [merged.function]
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

        effects = merged if merged is not None else index.compute(narrowed[0].id)
        text = build_text(project_path, effects, _file_table(index), limit)
        if copies_note:
            text = text + "\n" + copies_note
        ctx.log_action(project_path, TOOL_NAME, f"Described the side effects of {narrowed[0].display_name}")
        return [TextContent(type="text", text=text)]

    except Exception as e:
        error_msg = f"Error computing side effects: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ctx.error(error_msg, arguments.get("project_path", ""), TOOL_NAME)


def merge_copies(copies: list[SideEffects]) -> SideEffects:
    """The copies of one definition as one function: the union of their effects (a read in one copy and a write in
    another both stay), and caveats that hold for the union. A copy never executed adds what its code references, but
    does not make the others' observation incomplete: then the definition was observed through the other copies."""
    from discopop_explorer.side_effects.result import Effect, SideEffects

    executed = [c for c in copies if c.coverage != "not_executed"]
    kinds = {c.coverage for c in executed}
    if not executed:
        coverage = "not_executed"
    elif len(kinds) == 1:
        # e.g. every copy untracked: its caveat holds for the union
        coverage = executed[0].coverage
    else:
        # some copies fully observed, others not: effects of the union may be missing
        coverage = "partial"
    judged = executed or copies
    purity: Optional[bool]
    if any(c.pure_on_observed_inputs is False for c in judged):
        purity = False
    elif all(c.pure_on_observed_inputs is True for c in judged) and coverage == "executed":
        purity = True
    else:
        purity = None

    merged_effects: dict[tuple[Any, ...], Effect] = {}
    for copy in copies:
        for effect in copy.effects:
            key = (effect.name, effect.kind, effect.access, effect.source, effect.through_pointer, effect.member_of)
            known = merged_effects.get(key)
            if known is None:
                merged_effects[key] = Effect(
                    name=effect.name,
                    kind=effect.kind,
                    access=effect.access,
                    source=effect.source,
                    through_pointer=effect.through_pointer,
                    member_of=effect.member_of,
                    sites=list(effect.sites),
                    outside_names=list(effect.outside_names),
                    thread_local=effect.thread_local,
                )
                continue
            known.sites = sorted(set(known.sites) | set(effect.sites), key=lambda s: (s.file_id, s.line, s.via))
            known.outside_names = list(dict.fromkeys(known.outside_names + effect.outside_names))
            # one copy per thread only if it is so in every copy
            known.thread_local = known.thread_local and effect.thread_local
    best = max(copies, key=lambda c: (_COVERAGE_RANK.get(c.coverage, 0), len(c.effects)))
    return SideEffects(
        function=best.function,
        coverage=coverage,  # type: ignore[arg-type]
        pure_on_observed_inputs=purity,
        performs_file_io=any(c.performs_file_io for c in copies),
        unprofiled_calls=list(dict.fromkeys(name for c in copies for name in c.unprofiled_calls)),
        effects=list(merged_effects.values()),
        unmapped_records=sum(c.unmapped_records for c in copies),
        contributing_callees=list(dict.fromkeys(name for c in copies for name in c.contributing_callees)),
        ast_facts=all(c.ast_facts for c in copies),
        notes=list(dict.fromkeys(note for c in copies for note in c.notes)),
    )


def _copies_of_one_definition(functions: list[FunctionInfo]) -> bool:
    """whether the functions are copies of one definition: the same name, file and lines"""
    return len({(f.display_name, f.file, f.start_line, f.end_line) for f in functions}) == 1


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
