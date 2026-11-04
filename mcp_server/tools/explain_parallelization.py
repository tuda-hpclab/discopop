# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools import task_groups
from mcp_server.tools.helpers import ToolContext
from mcp_server.tools.hotspot_text import display_path, resolve_source_path

logger = logging.getLogger("discopop-mcp")

TOOL_NAME = "explain_parallelization"

# A query over a whole file can match every analysed region in it; the innermost ones come
# first, and are the ones a question about a line is usually about.
MAX_REGIONS = 5
# The same region can be rejected for many dependencies; the first ones are enough to see why.
# Counted in lines of the answer: the dependencies on one variable share a line (_grouped_reasons).
MAX_REASONS_PER_REGION = 5
# the locations listed on such a line
MAX_LOCATIONS_PER_REASON = 5

TOOL = Tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Explain why DiscoPoP did or did not suggest a parallelization for the code at the given lines. "
        "The answer is a text with one paragraph per code region that pattern detection considered and "
        "that overlaps them, innermost first: either the suggestion for it, or the reasons it was "
        "rejected, e.g. 'RAW dependency to md.cpp:306 via variable f from md.cpp:306 prevents "
        "parallelization' (the dependency from the first location to the second, between iterations). "
        "Lines no region covers were not considered at all, e.g. because they were never executed during "
        "profiling, and the answer says so. "
        f"The first {MAX_REGIONS} regions are explained, and the last line says how many are not."
        "\n\n"
        "Requires gather_data to have been run first. Cheap to call."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "file_path": {
                "type": "string",
                "description": "The source file (absolute, or relative to the project).",
            },
            "start_line": {
                "type": "integer",
                "description": "Line to explain, or the first line of a range (inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line of the range (inclusive). Default: start_line.",
            },
        },
        "required": ["project_path", "file_path", "start_line"],
        "additionalProperties": False,
    },
)


def _decisions_path(project_path: str) -> Path:
    return Path(project_path) / ".discopop" / "explorer" / "pattern_decisions.json"


def _location(line_id: Optional[str], file_mapping: dict[int, Path], project_path: str) -> Optional[str]:
    """'md.cpp:306' for a 'file id:line' of the decision log."""
    if line_id is None:
        return None
    try:
        file_id, line = (int(part) for part in line_id.split(":")[:2])
    except ValueError:
        return None
    return f"{display_path(project_path, file_mapping.get(file_id))}:{line}"


def _dependency_sentence(reason: Any, file_mapping: dict[int, Path], project_path: str) -> str:
    """'RAW dependency to md.cpp:306 via variable f from md.cpp:306 prevents parallelization (observed ...)'."""
    # imported here: the server starts without discopop_explorer installed
    from discopop_explorer.classes.patterns.PatternDecisions import UNPRIVATIZABLE_STATIC_DEPENDENCY

    dep = reason.dependency
    text = f"{dep.type or 'Data'} dependency"
    sink = _location(dep.sink_line, file_mapping, project_path)
    if sink is not None:
        text += f" to {sink}"
    text += _via(dep)
    source = _location(dep.source_line, file_mapping, project_path)
    if source is not None:
        text += f" from {source}"
    text += " prevents parallelization"
    if reason.kind == UNPRIVATIZABLE_STATIC_DEPENDENCY:
        text += UNPRIVATIZABLE_EXPLANATION
    return text + _origin(dep) + "."


UNPRIVATIZABLE_EXPLANATION = (
    ": the variable cannot be privatized, as it is neither written before it is read in each iteration "
    "nor a reduction variable"
)


def _via(dep: Any) -> str:
    if not dep.variable:
        return ""
    return f" via {'elements of ' if dep.element_access else ''}variable {dep.variable}"


def _origin(dep: Any) -> str:
    origin = {"dynamic": "observed during profiling", "static": "found by static analysis"}.get(dep.origin or "")
    return f" ({origin})" if origin else ""


def _reason_text(reason: Any, file_mapping: dict[int, Path], project_path: str) -> str:
    if reason.dependency is not None:
        return _dependency_sentence(reason, file_mapping, project_path)
    return str(reason.message)


def _grouped_reasons(reasons: list[Any]) -> list[list[Any]]:
    """The reasons, with the dependencies of one kind on one variable - differing only in their
    locations - collected into one group, in the order the first of each group was recorded. The
    detector records every dependency which prevents a loop, so a variable updated on several lines
    would otherwise take several lines of the answer and push the other variables out of it."""
    groups: dict[Any, list[Any]] = {}
    for reason in reasons:
        dep = reason.dependency
        key = (
            ("reason", id(reason))
            if dep is None
            else ("dependency", reason.kind, dep.type, dep.variable, dep.element_access, dep.origin)
        )
        groups.setdefault(key, []).append(reason)
    return list(groups.values())


def _group_text(group: list[Any], file_mapping: dict[int, Path], project_path: str) -> str:
    """One reason as _reason_text words it; several dependencies on one variable as one sentence
    listing their locations: 'RAW dependencies via variable f prevent parallelization (observed during
    profiling): to md.cpp:306 from md.cpp:306, to md.cpp:310 from md.cpp:306.'"""
    if len(group) == 1:
        return _reason_text(group[0], file_mapping, project_path)
    from discopop_explorer.classes.patterns.PatternDecisions import UNPRIVATIZABLE_STATIC_DEPENDENCY

    dep = group[0].dependency
    text = f"{dep.type or 'Data'} dependencies{_via(dep)} prevent parallelization"
    if group[0].kind == UNPRIVATIZABLE_STATIC_DEPENDENCY:
        text += UNPRIVATIZABLE_EXPLANATION
    locations = []
    for reason in group[:MAX_LOCATIONS_PER_REASON]:
        sink = _location(reason.dependency.sink_line, file_mapping, project_path)
        source = _location(reason.dependency.source_line, file_mapping, project_path)
        locations.append(
            " ".join(part for part in (f"to {sink}" if sink else "", f"from {source}" if source else "") if part)
        )
    text += _origin(dep) + ": " + ", ".join(locations)
    if len(group) > MAX_LOCATIONS_PER_REASON:
        text += f", and {len(group) - MAX_LOCATIONS_PER_REASON} more"
    return text + "."


def _reason_lines(reasons: list[Any], file_mapping: dict[int, Path], project_path: str) -> list[str]:
    groups = _grouped_reasons(reasons)
    shown = groups[:MAX_REASONS_PER_REGION]
    lines = [f"- {_group_text(group, file_mapping, project_path)}" for group in shown]
    hidden = sum(len(group) for group in groups[len(shown) :])
    if hidden:
        lines.append(f"- {hidden} more reasons.")
    return lines


def _atomic_update_line(reasons: list[Any], file_mapping: dict[int, Path], project_path: str) -> Optional[str]:
    """For a loop rejected only for dependencies which are commutative updates of shared memory (x += e,
    x++, see the explorer's commutative_updates): which statements `#pragma omp atomic` would have to
    protect to make it parallel. None for every other loop."""
    if not reasons:
        return None
    # one operation per updated memory, but different memory may be updated with different operations
    sites: set[str] = set()
    for reason in reasons:
        details = reason.details.get("atomic_update") if isinstance(reason.details, dict) else None
        if not isinstance(details, dict) or not details.get("fixable"):
            return None
        sites.update(str(site) for site in details.get("sites", []))
    if not sites:
        return None
    locations = sorted((_location(site, file_mapping, project_path) or site for site in sites), key=lambda text: text)
    return (
        "- The dependencies that prevent this loop are all commutative updates of shared memory: "
        "`#pragma omp atomic update` before the update at " + ", ".join(locations) + " would make them safe. "
        "This is no guarantee that the loop is parallel then: the other conditions (variables that must be "
        "private, dependencies that need no atomics) are checked only by the analysis with --atomic-updates. "
        "Atomic updates also change the order of the operations, so floating-point results may differ in the "
        "last digits."
    )


def _region_text(decision: Any, file_mapping: dict[int, Path], project_path: str) -> list[str]:
    notes = [f"- Note: {note.message}" for note in getattr(decision, "notes", [])]
    return _region_lines(decision, file_mapping, project_path) + notes


def _region_lines(decision: Any, file_mapping: dict[int, Path], project_path: str) -> list[str]:
    region = decision.region
    path = display_path(project_path, file_mapping.get(region.file_id))
    lines_text = (
        f"{region.start_line}-{region.end_line}" if region.end_line != region.start_line else f"{region.start_line}"
    )
    title = f"{region.kind.capitalize() or 'Code'} {path}:{lines_text}"
    if decision.patterns:
        suggested = ", ".join(f"suggestion {p['pattern_id']} ({p['type']})" for p in decision.patterns)
        return [f"{title}: {suggested}."]
    if decision.outcome == "rejected":
        lines = [f"{title}: not parallelizable."] + _reason_lines(decision.reasons, file_mapping, project_path)
        atomic = _atomic_update_line(decision.reasons, file_mapping, project_path)
        return lines + ([atomic] if atomic is not None else [])
    # passed the checks without being part of the result
    lines = [f"{title}: passed the checks, but no suggestion is reported for it."]
    return lines + _reason_lines(decision.reasons, file_mapping, project_path)


def _task_group_lines(decisions_path: Path, file_id: int, start_line: int, end_line: int, place: str) -> list[str]:
    """The task groups at the lines. Task detection records no decisions, so there is nothing to say
    about why code is not in a group, and the groups are not among the regions."""
    try:
        with open(decisions_path.parent / "patterns.json") as f:
            groups = task_groups.task_groups(json.load(f).get("patterns", {}))
    except (OSError, ValueError):
        return []
    found = task_groups.covering(groups, file_id, start_line, end_line)
    lines = []
    for pid, group in sorted(found.items(), key=lambda item: int(item[0])):
        tasks = ", ".join(f"{t.start_line}-{t.end_line}" for t in group.tasks)
        lines.append(
            f"{place} lies in the parallel region of task group {pid} (lines {group.start_line}-{group.end_line}, "
            f"tasks at {tasks}); see suggestion {pid} of get_parallelization_suggestions."
        )
    if lines:
        lines.append("Task detection does not record why code is not part of a task group.")
    return lines


def _hint(decisions: list[Any]) -> Optional[str]:
    from discopop_explorer.classes.patterns.PatternDecisions import TOO_FEW_ITERATIONS

    steps = []
    if any(r.kind == TOO_FEW_ITERATIONS for d in decisions for r in d.reasons):
        steps.append(
            "Too few iterations were observed to judge a region: profile with an input that executes "
            "it more often (create_execution_configuration, then gather_data)."
        )
    if any(d.patterns for d in decisions):
        steps.append("get_parallelization_suggestions lists the suggestions.")
    return " ".join(steps) if steps else None


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        file_path: str = arguments.get("file_path", "")
        start_line = int(arguments.get("start_line", 0))
        end_line = int(arguments.get("end_line", start_line))
        if end_line < start_line:
            return ctx.error("end_line must not be smaller than start_line.", project_path, TOOL_NAME)

        decisions_path = _decisions_path(project_path)
        if not decisions_path.exists():
            patterns_path = decisions_path.parent / "patterns.json"
            message = (
                "The project was analysed by a DiscoPoP version that does not record why code was "
                "(not) parallelized. Run gather_data again."
                if patterns_path.exists()
                else "No pattern detection result found. Run gather_data first."
            )
            return ctx.error(message, project_path, TOOL_NAME)

        file_mapping = ctx.get_file_mapping(project_path)
        if file_mapping is None:
            return ctx.error("FileMapping.txt not found. Run gather_data first.", project_path, TOOL_NAME)
        resolved_request = resolve_source_path(project_path, file_path)
        file_id = next((fid for fid, path in file_mapping.items() if path.resolve() == resolved_request), None)
        if file_id is None:
            return ctx.error(f"file_path is not part of the analysed program: {file_path}", project_path, TOOL_NAME)

        from discopop_explorer.classes.patterns.PatternDecisions import PatternDecisionLog

        log = PatternDecisionLog.load(str(decisions_path))
        matches = log.query(file_id, start_line, end_line)

        place = f"{display_path(project_path, resolved_request)}:{start_line}" + (
            f"-{end_line}" if end_line != start_line else ""
        )
        shown = matches[:MAX_REGIONS]
        task_lines = _task_group_lines(decisions_path, file_id, start_line, end_line, place)
        if not matches and task_lines:
            lines = []
        elif not matches and log.detectors is not None and not log.detectors:
            lines = [
                f"Nothing can be explained for {place}: the last pattern detection ran no detector that records why "
                "code was (not) parallelized. Run gather_data(force=true) to repeat it with the default pattern "
                "detection."
            ]
        elif not matches:
            lines = [
                f"Pattern detection considered no code region at {place}. Either the lines were never executed "
                "during profiling (run gather_data with a configuration whose input reaches them), or they were "
                "left out of the analysis as not being a hotspot, or they contain nothing DiscoPoP's patterns "
                "apply to."
            ]
        else:
            lines = [f"{place} lies in {len(matches)} code region{'s' if len(matches) != 1 else ''}, innermost first:"]
            for decision in shown:
                lines += _region_text(decision, file_mapping, project_path)
            if len(matches) > len(shown):
                lines.append(f"{len(matches) - len(shown)} more regions not explained (the outermost ones).")
            hint = _hint(shown)
            if hint is not None:
                lines.append(hint)
        lines += task_lines
        patterns_path = decisions_path.parent / "patterns.json"
        if patterns_path.exists() and patterns_path.stat().st_mtime > decisions_path.stat().st_mtime:
            lines.append(
                "Note: the suggestions were produced after this explanation was recorded, e.g. by loading existing "
                "patterns; it may not match them. Run gather_data to bring both up to date."
            )
        ctx.log_action(project_path, TOOL_NAME, f"Explained {len(shown)} of {len(matches)} regions at {place}")
        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        error_msg = f"Error explaining the parallelization: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ctx.error(error_msg, arguments.get("project_path", ""), TOOL_NAME)
