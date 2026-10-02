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
    recorded_applied_suggestions,
    setup_next_step,
)
from mcp_server.tools.run_auto_tuning import progress_mtime, read_progress_events, result_from_events

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
# The steps whose output run_auto_tuning and the query tools depend on.
_ANALYSIS_STEPS = ("instrumentation", "profiling", "pattern_detection", "patch_generation")
# The applicator writes applied_suggestions.json right after it patched the last file;
# the slack covers file systems with coarse timestamps.
_PATCHING_SLACK_SECONDS = 2.0

TOOL = Tool(
    name="get_project_status",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Report where a project stands in the DiscoPoP workflow: whether it is set up, which "
        "pipeline steps have run and whether the sources changed since, how many suggestions "
        "exist, which are applied, and what auto-tuning selected. 'next_step' names the call "
        "to make next. Use it when starting or resuming work on a project, or when unsure "
        "what to do next, instead of probing several tools. Cheap to call; changes nothing."
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


def _patchable_files(dot_dp: Path, ctx: ToolContext, project_path: str) -> set[Path]:
    """The source files some suggestion patches, i.e. those applying or rolling back rewrites."""
    patch_gen_dir = dot_dp / "patch_generator"
    mapping = ctx.get_file_mapping(project_path)
    if mapping is None or not patch_gen_dir.is_dir():
        return set()
    files: set[Path] = set()
    for patch in patch_gen_dir.glob("*/*.patch"):
        if patch.parent.name.isdigit() and patch.stem.isdigit() and int(patch.stem) in mapping:
            files.add(Path(mapping[int(patch.stem)]).resolve())
    return files


def _newest_edit(sources: dict[Path, float], patchable: set[Path], patching_mtime: Optional[float]) -> Optional[float]:
    """The newest mtime of a source file that applying or rolling back suggestions does not explain.

    Only the files a suggestion patches are rewritten, and no later than the applicator's
    record of the selection; any other change is an edit.
    """
    edits = [
        mtime
        for path, mtime in sources.items()
        if patching_mtime is None or path.resolve() not in patchable or mtime > patching_mtime + _PATCHING_SLACK_SECONDS
    ]
    return max(edits, default=None)


def _auto_tuning_state(dot_dp: Path, patterns_mtime: Optional[float]) -> Optional[dict[str, Any]]:
    """The last auto-tuning run, read the way run_auto_tuning reads it."""
    tuned_at = progress_mtime(str(dot_dp))
    if tuned_at is None:
        return None
    events = read_progress_events(str(dot_dp))
    if not events:
        return None
    outcome = result_from_events(events, timed_out=False)
    state: dict[str, Any] = {"at": ToolContext.fmt_ts(tuned_at)}
    config = next((e.get("config") for e in events if e.get("config")), None)
    if config:
        state["config"] = config
    state["complete"] = not outcome.get("partial", False)
    state["suggestion_ids"] = outcome.get("suggestion_ids", [])
    for key in ("speedup", "thread_count"):
        if outcome.get(key) is not None:
            state[key] = outcome[key]
    # Tuning measured the suggestions of an earlier analysis; their ids need not
    # mean the same code any more.
    if patterns_mtime is not None and tuned_at < patterns_mtime:
        state["stale"] = True
    return state


def _next_step(
    configs_dir: Path,
    names: list[str],
    pipeline: dict[str, dict[str, Any]],
    analysis_stale: bool,
    suggestions: Optional[int],
    hotspots: bool,
    applied: list[str],
    tuning: Optional[dict[str, Any]],
) -> str:
    if applied:
        if analysis_stale:
            return (
                f"The suggestions {applied} are applied and the sources were edited afterwards. Roll the "
                "suggestions back with manage_patches(action='rollback', suggestion_ids=[...]) before "
                "re-analysing with gather_data: profiling patched sources analyses the parallel code."
            )
        return (
            f"The suggestions {applied} are applied to the sources. Nothing else is required; "
            "manage_patches(action='rollback', suggestion_ids=[...]) undoes them, and get_execution_results "
            "shows the measured runs."
        )
    if not pipeline["pattern_detection"].get("at") or not pipeline["profiling"].get("at"):
        return "No analysis results exist yet. " + setup_next_step(configs_dir)
    if analysis_stale:
        hotspot_hint = " (with hotspot_config_names again, to refresh the hotspot results)" if hotspots else ""
        return (
            "The sources changed after the last analysis, so its results may not match the code. "
            f"Call gather_data with config_name set to one of {names}{hotspot_hint}; it re-runs only "
            "the stale steps."
        )
    if suggestions is None:
        return (
            "Pattern detection ran but no patches exist. Call gather_data with force=true to "
            "regenerate them, or initialize_discopop_directory(reset=true) first if that fails."
        )
    if suggestions == 0:
        return next_step_hint(0)
    if tuning is None or tuning.get("stale"):
        prefix = "The auto-tuning results predate the current analysis. " if tuning is not None else ""
        hint = prefix + next_step_hint(suggestions) + f" Tune with config_name set to one of {names}."
        if not hotspots:
            hint += (
                " Without hotspot results run_auto_tuning falls back to the greedy search; gather_data with "
                "hotspot_config_names enables the faster hotspot-guided one."
            )
        return hint
    selection = tuning.get("suggestion_ids") or []
    if not tuning.get("complete"):
        return (
            "The last run_auto_tuning did not complete"
            + (f"; its best selection so far is {selection}" if selection else "")
            + ". Call run_auto_tuning again with a larger timeout_seconds for a complete search."
        )
    if selection:
        return (
            f"run_auto_tuning selected {selection}"
            + (f" (speedup {tuning['speedup']})" if tuning.get("speedup") is not None else "")
            + ", but it is not applied. Apply it with manage_patches(action='apply', suggestion_ids=[...])."
        )
    return (
        "run_auto_tuning found no combination faster than the unmodified program, so nothing is "
        "recommended for application. get_hotspots shows where the time goes, and "
        "explain_parallelization tells why a hot region was not parallelized."
    )


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        if not project_path or not Path(project_path).is_dir():
            return ctx.error(f"project_path is not a directory: {project_path!r}")
        dot_dp = Path(project_path) / ".discopop"
        configs_dir = dot_dp / "project" / "configs"

        result: dict[str, Any] = {"status": "success", "project_path": project_path}
        result["initialized"] = configs_dir.is_dir()
        if not result["initialized"]:
            result["next_step"] = setup_next_step(configs_dir)
            return _respond(result, ctx)

        names = configuration_names(configs_dir)
        result["compile_script_configured"] = compile_script_configured(configs_dir)
        result["configurations"] = names
        if not (result["compile_script_configured"] and names):
            result["next_step"] = setup_next_step(configs_dir)
            return _respond(result, ctx)

        sources = ToolContext.source_mtimes(project_path)
        source_mtime = max(sources.values(), default=None)
        if source_mtime is not None:
            result["sources_modified_at"] = ToolContext.fmt_ts(source_mtime)
        pipeline = _pipeline_state(dot_dp, source_mtime)
        result["pipeline"] = pipeline

        suggestions = count_suggestions(project_path)
        if suggestions is not None:
            result["suggestions"] = suggestions
        hotspots = bool(pipeline["hotspot_detection"].get("at"))
        result["hotspot_results"] = hotspots

        applied, applied_error = recorded_applied_suggestions(project_path)
        result["applied_suggestions"] = applied
        if applied_error is not None:
            result["applied_suggestions_error"] = applied_error

        # Applying or rolling back a suggestion rewrites source files, which makes every
        # result look stale although the analysis still describes the un-patched code.
        # So such changes are told apart from edits, which only a re-analysis catches up with.
        analysis_stale = any(pipeline[step].get("stale") for step in _ANALYSIS_STEPS)
        patching_mtime = _mtime(dot_dp / "patch_applicator" / "applied_suggestions.json")
        if analysis_stale and patching_mtime is not None:
            edited_at = _newest_edit(sources, _patchable_files(dot_dp, ctx, project_path), patching_mtime)
            analysis_stale = edited_at is not None and any(
                (step_mtime := _mtime(dot_dp / _PIPELINE_OUTPUTS[step])) is not None and edited_at > step_mtime
                for step in _ANALYSIS_STEPS
            )
        if any(pipeline[step].get("stale") for step in _ANALYSIS_STEPS) and not analysis_stale:
            result["note"] = (
                "The sources were last changed by applying or rolling back suggestions, which is why the "
                "pipeline steps are marked stale; the analysis still describes the un-patched sources."
            )

        tuning = _auto_tuning_state(dot_dp, _mtime(dot_dp / _PIPELINE_OUTPUTS["pattern_detection"]))
        if tuning is not None:
            result["auto_tuning"] = tuning

        result["next_step"] = _next_step(
            configs_dir, names, pipeline, analysis_stale, suggestions, hotspots, applied, tuning
        )
        return _respond(result, ctx)

    except Exception as e:
        error_msg = f"Error determining the project status: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]


def _respond(result: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    ctx.log_response("get_project_status", result)
    return [TextContent(type="text", text=json.dumps(result))]
