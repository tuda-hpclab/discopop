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

from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

# A query over a whole file can match every analysed region in it; the innermost ones come
# first, and are the ones a question about a line is usually about.
MAX_REGIONS = 20
# The same region can be rejected for many dependencies; the first ones are enough to see why.
MAX_REASONS_PER_REGION = 10

TOOL = Tool(
    name="explain_parallelization",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Explain why DiscoPoP did or did not suggest a parallelization for the code at the given "
        "lines. Returns every code region that pattern detection considered and that overlaps "
        "them, innermost first, with its outcome: 'accepted' (with the ids of the suggestions, "
        "for get_parallelization_patches), 'rejected' (with the reasons, e.g. the data dependency "
        "between iterations that prevents it, with variable and source/sink lines), or "
        "'not_reported' (it passed the checks, but no suggestion for it is part of the result, e.g. "
        "because its pattern type was not enabled; reasons, if present, say why). "
        "Lines no region covers were not considered at all, e.g. because they were never executed "
        "during profiling."
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
                "description": "Absolute path to the source file.",
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


def _location(line_id: Optional[str], file_mapping: dict[int, Path]) -> Optional[dict[str, Any]]:
    if line_id is None:
        return None
    try:
        file_id, line = (int(part) for part in line_id.split(":")[:2])
    except ValueError:
        return None
    path = file_mapping.get(file_id)
    return {"file": str(path) if path is not None else None, "line": line}


def _reason(reason: Any, file_mapping: dict[int, Path]) -> dict[str, Any]:
    entry: dict[str, Any] = {"kind": reason.kind, "message": reason.message}
    dep = reason.dependency
    if dep is not None:
        dependency: dict[str, Any] = {"type": dep.type, "variable": dep.variable}
        if dep.element_access:
            dependency["element_access"] = True
        dependency["source"] = _location(dep.source_line, file_mapping)
        dependency["sink"] = _location(dep.sink_line, file_mapping)
        dependency["origin"] = dep.origin
        entry["dependency"] = dependency
    if reason.details:
        details = dict(reason.details)
        # the same forms as the rest of the answer: string suggestion ids, file paths
        if "pattern_id" in details:
            details["pattern_id"] = str(details["pattern_id"])
        if "file_id" in details:
            path = file_mapping.get(details.pop("file_id"))
            details["file"] = str(path) if path is not None else None
        entry["details"] = details
    return entry


def _region(decision: Any, file_mapping: dict[int, Path]) -> dict[str, Any]:
    region = decision.region
    path = file_mapping.get(region.file_id)
    entry: dict[str, Any] = {
        "file": str(path) if path is not None else None,
        "start_line": region.start_line,
        "end_line": region.end_line,
        "kind": region.kind,
        "considered_for": list(decision.pattern_types),
        "outcome": decision.outcome,
    }
    if decision.patterns:
        # strings, as get_parallelization_patches takes and returns them
        entry["suggestions"] = [{"type": p["type"], "pattern_id": str(p["pattern_id"])} for p in decision.patterns]
    if decision.reasons:
        entry["reasons"] = [_reason(r, file_mapping) for r in decision.reasons[:MAX_REASONS_PER_REGION]]
        if len(decision.reasons) > MAX_REASONS_PER_REGION:
            entry["num_reasons"] = len(decision.reasons)
    return entry


def _next_step(decisions: list[Any], file_path: str) -> Optional[str]:
    from discopop_explorer.classes.patterns.PatternDecisions import (
        LOOP_CARRIED_DEPENDENCY,
        TOO_FEW_ITERATIONS,
        UNPRIVATIZABLE_STATIC_DEPENDENCY,
    )

    dependency_kinds = {LOOP_CARRIED_DEPENDENCY, UNPRIVATIZABLE_STATIC_DEPENDENCY}
    kinds = {r.kind for d in decisions for r in d.reasons}
    steps = []
    if kinds & dependency_kinds:
        # the innermost region a dependency prevents, not just any rejected one
        innermost = next(d for d in decisions if any(r.kind in dependency_kinds for r in d.reasons))
        steps.append(
            f"get_data_dependencies(file_path='{file_path}', start_line={innermost.region.start_line}, "
            f"end_line={innermost.region.end_line}) lists all dependencies of the region, e.g. to judge "
            "whether a restructuring of the code removes the one that prevents it."
        )
    if TOO_FEW_ITERATIONS in kinds:
        steps.append(
            "Too few iterations were observed to judge the region: profile with an input that executes "
            "it more often (create_execution_configuration, then gather_data)."
        )
    if any(d.outcome == "accepted" for d in decisions):
        steps.append("get_parallelization_patches(pattern_ids=[...]) shows an accepted suggestion.")
    return " ".join(steps) if steps else None


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        file_path: str = arguments.get("file_path", "")
        start_line = int(arguments.get("start_line", 0))
        end_line = int(arguments.get("end_line", start_line))
        if end_line < start_line:
            return ctx.error("end_line must not be smaller than start_line.", project_path, "explain_parallelization")

        decisions_path = _decisions_path(project_path)
        if not decisions_path.exists():
            patterns_path = decisions_path.parent / "patterns.json"
            message = (
                "The project was analysed by a DiscoPoP version that does not record why code was "
                "(not) parallelized. Run gather_data again."
                if patterns_path.exists()
                else "No pattern detection result found. Run gather_data first."
            )
            return ctx.error(message, project_path, "explain_parallelization")

        file_mapping = ctx.get_file_mapping(project_path)
        if file_mapping is None:
            return ctx.error(
                "FileMapping.txt not found. Run gather_data first.", project_path, "explain_parallelization"
            )
        resolved_request = Path(file_path).resolve()
        file_id = next((fid for fid, path in file_mapping.items() if path.resolve() == resolved_request), None)
        if file_id is None:
            return ctx.error(
                f"file_path is not part of the analysed program: {file_path}", project_path, "explain_parallelization"
            )

        from discopop_explorer.classes.patterns.PatternDecisions import PatternDecisionLog

        log = PatternDecisionLog.load(str(decisions_path))
        matches = log.query(file_id, start_line, end_line)

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "num_regions": len(matches),
            "regions": [_region(d, file_mapping) for d in matches[:MAX_REGIONS]],
        }
        if len(matches) > MAX_REGIONS:
            result["truncated"] = True
        patterns_path = decisions_path.parent / "patterns.json"
        if patterns_path.exists() and patterns_path.stat().st_mtime > decisions_path.stat().st_mtime:
            result["warning"] = (
                "The suggestions were produced after this explanation was recorded, e.g. by loading "
                "existing patterns; it may not match them. Run gather_data to bring both up to date."
            )
        if not matches and log.detectors is not None and not log.detectors:
            result["next_step"] = (
                "The last pattern detection ran no detector that records why code was (not) "
                "parallelized, so nothing can be explained. Run gather_data(force=true) to repeat it "
                "with the default pattern detection."
            )
        elif not matches:
            result["next_step"] = (
                "Pattern detection considered no code region at these lines. Either they were never "
                "executed during profiling (run gather_data with a configuration whose input reaches "
                "them), or they were left out of the analysis as not being a hotspot, or they contain "
                "nothing DiscoPoP's patterns apply to."
            )
        else:
            next_step = _next_step(matches[:MAX_REGIONS], file_path)
            if next_step is not None:
                result["next_step"] = next_step

        ctx.log_response("explain_parallelization", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error explaining the parallelization: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]
