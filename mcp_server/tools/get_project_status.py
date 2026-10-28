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

from mcp_server.tools.gather_data import count_suggestions, next_step_hint
from mcp_server.tools.helpers import (
    ToolContext,
    compile_script_configured,
    configuration_names,
    setup_next_step,
)

logger = logging.getLogger("discopop-mcp")

# The file each pipeline step leaves behind, relative to .discopop, in pipeline order.
# Its mtime is when the step last ran; a source file newer than that makes it stale,
# which is the same test gather_data uses to decide what to re-run.
_PIPELINE_OUTPUTS = {
    "hotspot_detection": "hotspot_detection/Hotspots.json",
    "instrumentation": "profiler/Data.xml",
    "profiling": "profiler/dynamic_dependencies.txt",
    "pattern_detection": "explorer/patterns.json",
    "patch_generation": "patch_generator",
}
# The steps whose output the query tools depend on.
_ANALYSIS_STEPS = ("instrumentation", "profiling", "pattern_detection", "patch_generation")

TOOL = Tool(
    name="get_project_status",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Report where a project stands in the DiscoPoP workflow: whether it is set up, which "
        "pipeline steps have run and whether the sources changed since, and how many suggestions "
        "exist. Results prepared earlier or elsewhere count: with current results the queries are cheap and "
        "need no run. 'next_step' names the call to make next. Use it when starting or resuming work on a project, "
        "or when unsure what to do next, instead of probing several tools. Cheap to call; changes nothing."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _pipeline_state(dot_dp: Path, source_mtime: Optional[float]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for step, relative in _PIPELINE_OUTPUTS.items():
        mtime = _mtime(dot_dp / relative)
        if mtime is None:
            state[step] = {"done": False}
        else:
            state[step] = {"at": ToolContext.fmt_ts(mtime), "stale": source_mtime is not None and source_mtime > mtime}
    return state


def _next_step(
    configs_dir: Path,
    names: list[str],
    pipeline: dict[str, dict[str, Any]],
    analysis_stale: bool,
    suggestions: Optional[int],
) -> str:
    if not pipeline["pattern_detection"].get("at") or not pipeline["profiling"].get("at"):
        return "No analysis results exist yet. " + setup_next_step(configs_dir)
    if analysis_stale:
        return (
            "The sources changed after the last analysis, so its results may not match the code. "
            f"Call gather_data with config_name set to one of {names} (and hotspot_config_names as before, to "
            "keep the hotspot configurations); it re-runs only the stale steps."
        )
    if suggestions is None:
        return (
            "Pattern detection ran but no patches exist. Call gather_data with force=true to "
            "regenerate them, or initialize_discopop_directory(reset=true) first if that fails."
        )
    return next_step_hint(suggestions) + " Results exist: the queries are cheap, no run is needed."


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        if not project_path or not Path(project_path).is_dir():
            return ctx.error(f"project_path is not a directory: {project_path!r}")
        dot_dp = Path(project_path) / ".discopop"
        configs_dir = dot_dp / "project" / "configs"

        result: dict[str, Any] = {}
        result["initialized"] = configs_dir.is_dir()
        names = configuration_names(configs_dir) if result["initialized"] else []
        set_up = result["initialized"] and compile_script_configured(configs_dir) and bool(names)
        if result["initialized"]:
            result["compile_script_configured"] = compile_script_configured(configs_dir)
            result["configurations"] = names

        # Results prepared outside of the server (or by an earlier session) are usable without any setup.
        source_mtime = ToolContext.newest_source_mtime(project_path)
        pipeline = _pipeline_state(dot_dp, source_mtime)
        has_results = bool(pipeline["pattern_detection"].get("at") and pipeline["profiling"].get("at"))
        if not (set_up or has_results):
            result["next_step"] = setup_next_step(configs_dir)
            return _respond(result, ctx, project_path)
        if source_mtime is not None:
            result["sources_modified_at"] = ToolContext.fmt_ts(source_mtime)
        result["pipeline"] = pipeline

        suggestions = count_suggestions(project_path)
        if suggestions is not None:
            result["suggestions"] = suggestions
        analysis_stale = any(pipeline[step].get("stale") for step in _ANALYSIS_STEPS)
        result["next_step"] = _next_step(configs_dir, names, pipeline, analysis_stale, suggestions)
        if has_results and not set_up and not analysis_stale:
            result["next_step"] += " The project itself is not set up for gather_data; the queries need no setup."
        return _respond(result, ctx, project_path)

    except Exception as e:
        error_msg = f"Error determining the project status: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]


def _respond(result: dict[str, Any], ctx: ToolContext, project_path: str) -> list[TextContent]:
    ctx.log_response("get_project_status", result, project_path)
    return [TextContent(type="text", text=json.dumps(result))]
