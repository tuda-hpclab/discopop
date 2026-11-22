# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.building import (
    BuildLockAborted,
    BuildResult,
    build_lock,
    ensure_build,
)
from discopop_library.ProjectManager.configurations.build_sharing import build_owner_of
from discopop_library.ProjectManager.configurations.builds import BuildKey, BuildPolicy, build_tree_path_of
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.running import execute_in_build
from discopop_library.ProjectManager.configurations.runs import (
    ActivationError,
    RunRecord,
    activate_run,
    activate_runs,
    active_runs,
)
from discopop_library.ProjectManager.services.build_overview import storage_warning
from mcp_server.tools.helpers import (
    ToolContext,
    invalid_configuration_name,
    tail_of_output,
    warning_fields,
    unknown_configuration_message,
)

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="gather_data",
    # Overwrites the previous analysis results (the compilations happen in builds next to the project, the
    # project's sources are not touched). A repeated call skips every step whose outputs are current, hence
    # idempotent.
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
    description=(
        "Run the complete DiscoPoP data collection pipeline and detect parallelization patterns. "
        "Call this after set_compile_script and create_execution_configuration. "
        "\n\n"
        "The pipeline consists of two phases:\n"
        "\n"
        "Hotspot detection (always runs; the call fails if it does, as the suggestions are ranked by it):\n"
        "  1. Compile with hotspot instrumentation (hd_settings.json).\n"
        "  2. Run the binary once per config in hotspot_config_names (default: config_name) to\n"
        "     accumulate timing data. Use 2 configs with different input sizes for accurate\n"
        "     classification.\n"
        "  3. Analyse timing data to classify regions as YES/MAYBE/NO hotspots.\n"
        "  Pattern analysis focuses on hotspot regions.\n"
        "\n"
        "Data collection and pattern detection:\n"
        "  4. Compile with DiscoPoP instrumentation (dp_settings.json).\n"
        "  5. Run the instrumented binary to collect runtime dependency traces.\n"
        "     NOTE: significant runtime overhead expected — use small inputs.\n"
        "  6. Analyse with discopop_explorer to detect parallelization opportunities (doall, reduction and\n"
        "     task parallelism).\n"
        "\n"
        "Each step is automatically skipped when its outputs are already current "
        "relative to the source files. Use force=true to re-run all steps unconditionally. "
        "\n\n"
        "Steps 1 and 4 compile in a copy of the project, a build in <project>_discopop_builds, which stays and is "
        "used again as long as nothing it was compiled from changed (sources, compile script, settings): "
        "the project's own build directory is never touched, so building and running the program by hand is "
        "safe at any time, and a repeated call does not compile again. Each profiling run writes its results "
        "to a run directory of its own, which is then put into the project's .discopop. Builds and runs are "
        "never deleted automatically; if they pile up, the result carries a warning with their number and "
        "the storage they occupy, which the user can act on (discopop_project_manager --list-builds, "
        "--delete-builds, --list-runs, --delete-runs). "
        "\n\n"
        "A step that succeeded lists the warnings of its build or run under 'warnings'; a step that failed "
        "carries the end of its error output under 'stderr'. "
        "On success, get_parallelization_suggestions lists the suggestions, hottest first."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root.",
            },
            "config_name": {
                "type": "string",
                "description": (
                    "Name of the execution configuration to use for compilation and profiling "
                    "(steps 4 and 5). Must match a directory under .discopop/project/configs/."
                ),
            },
            "hotspot_config_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional. Configuration names for the hotspot profiling runs (step 2). "
                    "Using 2 configs with different input sizes improves classification accuracy, "
                    "since growth with the input can only be judged then. "
                    "Default: [config_name], i.e. a single run."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": ("Maximum time in seconds for each individual pipeline step. Default: 3600."),
            },
            "force": {
                "type": "boolean",
                "description": ("Set to true to re-run all steps even if outputs are already current. Default: false."),
            },
        },
        "required": ["project_path", "config_name"],
        "additionalProperties": False,
    },
)


def _log_stdout(project_path: str, step: str, stdout: str, ctx: ToolContext) -> None:
    """Log stdout lines to daemon console only — stdout is never returned to the LLM."""
    if stdout and stdout.strip():
        for line in stdout.strip().splitlines():
            ctx.log_action(project_path, "gather_data", f"[{step}] stdout: {line}")


def _stderr_fields(stderr: Any) -> dict[str, Any]:
    """A step's stderr for its result: the tail, plus `stderr_length` when it was cut.

    A real project's build or profiling run easily writes hundreds of KB to stderr;
    the errors that explain a failure are at its end.
    """
    tail, full_length = tail_of_output(stderr)
    fields: dict[str, Any] = {"stderr": tail}
    if full_length is not None:
        fields["stderr_length"] = full_length
    return fields


# Which configurations the hotspot results in .discopop/hotspot_detection/private/ were
# profiled with. The result files themselves do not say, and the classification compares
# them across inputs: results from other configurations than the requested ones, or from
# only some of them, would classify silently on the wrong data.
PROFILED_CONFIGURATIONS_FILE = "profiled_configurations.json"


def _profiled_configurations(hotspot_dir: Path) -> list[str]:
    try:
        names = json.loads((hotspot_dir / PROFILED_CONFIGURATIONS_FILE).read_text())
    except (OSError, ValueError):
        return []
    return [str(n) for n in names] if isinstance(names, list) else []


@dataclass
class _PipelineState:
    """What the steps of one call hand on to each other."""

    # The configuration whose build the hotspot runs use (the runs of the other hotspot configurations execute
    # their own execute.sh in it).
    build_config: str = ""
    # False once a step has produced new data for the project: what is there is then not the result of an earlier
    # call, and the steps that follow must not take it for a current result.
    hotspot_data_is_current: bool = True
    dp_data_is_current: bool = True
    # the hotspot runs of this call (configuration, run): they are put into the project together
    hotspot_runs: list[tuple[str, RunRecord]] = field(default_factory=list)


def _from_other_configuration(project_path: str, mode: str, config_name: str) -> bool:
    """Whether the ``mode`` data in the project comes from a run of another configuration than ``config_name``.

    Data without a record (made by hand or before the runs were recorded) is taken as the configuration's.
    """
    entry = active_runs(str(Path(project_path) / ".discopop")).get(mode, {})
    configuration = entry.get("configuration")
    return isinstance(configuration, str) and configuration != config_name


def _build_arguments(project_path: str, timeout_seconds: int, ctx: ToolContext) -> ProjectManagerArguments:
    """The arguments for builds: compiled in a copy of the project, never in the project itself."""
    arguments = ctx.make_pm_args(project_path, timeout_seconds)
    arguments.execute_inplace = False
    arguments.skip_cleanup = False
    arguments.apply_suggestions = None
    return arguments


def _log_message(project_path: str, ctx: ToolContext) -> Callable[[str], None]:
    def log(text: str) -> None:
        if text.strip():
            ctx.log_action(project_path, "gather_data", text.strip())

    return log


def _compile_in_build(
    project_path: str,
    config_name: str,
    mode: str,
    label: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Compile ``config_name`` in ``mode`` in its build, unless a current build exists (``force``: in any case).

    The build is a copy of the project in ``<project>_discopop_builds``, so the project itself is never touched and
    a build that is still current is not compiled again.
    """
    configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
    # a configuration that builds from another one is compiled in the build of that one
    config_name = build_owner_of(str(configs_dir), config_name)
    compile_sh = resolve_compile_script_path(str(configs_dir), config_name)
    key = BuildKey(config_name, mode, ())
    arguments = _build_arguments(project_path, timeout_seconds, ctx)
    log = _log_message(project_path, ctx)
    ctx.log_action(
        project_path,
        "gather_data",
        f"{label}: {compile_sh} via {mode}_settings, config='{config_name}', timeout={timeout_seconds}s, "
        + ("rebuild" if force else "compiled unless a current build exists"),
    )
    original_cwd = os.getcwd()
    try:
        with build_lock(
            arguments,
            key,
            should_abort=lambda: ctx.cancelled,
            on_wait=lambda: log(f"Waiting for another process that uses the build {key.build_id}"),
        ):
            outcome = ensure_build(
                arguments,
                key,
                str(configs_dir / config_name),
                str(configs_dir / f"{mode}_settings.json"),
                compile_sh,
                1,
                BuildPolicy.REBUILD if force else BuildPolicy.AUTO,
                float(timeout_seconds),
                process_started_callback=ctx.track_process,
                message=log,
            )
    except BuildLockAborted:
        return {"status": "error", "message": f"Cancelled while waiting for the build {key.build_id}."}
    finally:
        os.chdir(original_cwd)

    if outcome.result == BuildResult.REUSED:
        ctx.log_action(project_path, "gather_data", f"{label}: the build {key.build_id} is current, not compiled")
        return {"status": "skipped", "reason": "build_is_current", "build_id": key.build_id}
    if outcome.result == BuildResult.BUILT and outcome.compile_result is not None:
        _returncode, elapsed, stdout, stderr = outcome.compile_result
        _log_stdout(project_path, label.lower().replace(" ", "_"), stdout, ctx)
        ctx.log_action(project_path, "gather_data", f"{label} succeeded in {elapsed}s ({key.build_id})")
        return {
            "status": "success",
            "elapsed_time": elapsed,
            "build_id": key.build_id,
            **warning_fields(stdout, stderr),
        }
    if outcome.result == BuildResult.COMPILE_FAILED and outcome.compile_result is not None:
        returncode, elapsed, stdout, stderr = outcome.compile_result
        _log_stdout(project_path, label.lower().replace(" ", "_"), stdout, ctx)
        return {
            "status": "error",
            "message": f"{label} failed (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    return {"status": "error", "message": outcome.message or f"{label} failed: no build {key.build_id}."}


def _run_in_build(
    project_path: str,
    build_config: str,
    run_config: str,
    mode: str,
    timeout_seconds: int,
    ctx: ToolContext,
) -> tuple[Optional[tuple[int, float, str, str]], Optional[RunRecord], str]:
    """Run the ``execute.sh`` of ``run_config`` in the build of ``build_config``; its results go to a run of their own.

    Returns what the script returned, the run and an error text for a build that is not available. The build is
    checked again under its lock (the project may have changed since it was compiled; a build that is not current
    any more is an error, never compiled here), which also refreshes the scripts in its tree.
    """
    configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
    key = BuildKey(build_config, mode, ())
    arguments = _build_arguments(project_path, timeout_seconds, ctx)
    settings = str(configs_dir / f"{mode}_settings.json")
    log = _log_message(project_path, ctx)
    original_cwd = os.getcwd()
    try:
        with build_lock(
            arguments,
            key,
            should_abort=lambda: ctx.cancelled,
            on_wait=lambda: log(f"Waiting for another process that uses the build {key.build_id}"),
        ):
            outcome = ensure_build(
                arguments,
                key,
                str(configs_dir / build_config),
                settings,
                resolve_compile_script_path(str(configs_dir), build_config),
                1,
                # the build of the step before: one that changed meanwhile (the sources were edited during a long run)
                # is no reason to compile silently, and the runs of one call have to come from one binary
                BuildPolicy.REUSE,
                float(timeout_seconds),
                process_started_callback=ctx.track_process,
                message=log,
            )
            if not outcome.usable or outcome.record is None:
                return (
                    None,
                    None,
                    (outcome.message or f"The build {key.build_id} is not available.")
                    + " Call gather_data again (force=true compiles anew).",
                )
            result, run = execute_in_build(
                arguments,
                outcome.record,
                str(configs_dir / run_config),
                settings,
                1,
                float(timeout_seconds),
                None,
                1,
                process_started_callback=ctx.track_process,
            )
    except BuildLockAborted:
        return None, None, f"Cancelled while waiting for the build {key.build_id}."
    finally:
        os.chdir(original_cwd)
    return result, run, ""


def _hotspot_instrument(
    project_path: str,
    config_name: str,
    hotspot_config_names: list[str],
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
    state: Optional[_PipelineState] = None,
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    hd_settings = configs_dir / "hd_settings.json"
    hotspot_dir = p / ".discopop" / "hotspot_detection"
    private_dir = hotspot_dir / "private"
    config_dir = configs_dir / config_name

    if not config_dir.exists():
        return {"status": "error", "message": unknown_configuration_message(configs_dir, config_name)}
    # honours a per-configuration compile.sh override, falling back to the shared script
    compile_sh = Path(resolve_compile_script_path(str(configs_dir), build_owner_of(str(configs_dir), config_name)))
    if not compile_sh.exists():
        return {"status": "error", "message": "compile.sh not found. Run set_compile_script first."}
    if not hd_settings.exists():
        return {"status": "error", "message": "hd_settings.json not found. Run initialize_discopop_directory first."}

    # Skipped only when the results cover exactly the requested configurations: the data of the project is
    # replaced by the runs of all of them together, so a configuration that is missing needs every run again.
    if (
        not force
        and private_dir.exists()
        and set(_profiled_configurations(hotspot_dir)) == set(hotspot_config_names)
        and not _from_other_configuration(project_path, "hd", config_name)
    ):
        result_files = list(private_dir.glob("hotspot_result_*.txt"))
        if result_files:
            last_run_mtime = max(f.stat().st_mtime for f in result_files)
            if source_mtime is None or source_mtime <= last_run_mtime:
                return {
                    "status": "skipped",
                    "reason": "results_are_current",
                    "last_run": ToolContext.fmt_ts(last_run_mtime),
                    "num_runs_accumulated": len(result_files),
                }

    # the runs that follow produce the data of the project anew, even where the build is reused
    if state is not None:
        state.hotspot_data_is_current = False
    return _compile_in_build(project_path, config_name, "hd", "Hotspot instrumentation", timeout_seconds, force, ctx)


def _hotspot_profiling_single(
    project_path: str,
    config_name: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
    state: Optional[_PipelineState] = None,
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    hd_settings = configs_dir / "hd_settings.json"
    execute_sh = configs_dir / config_name / "execute.sh"
    hotspot_dir = p / ".discopop" / "hotspot_detection"
    private_dir = hotspot_dir / "private"
    state = state if state is not None else _PipelineState()

    if not execute_sh.exists():
        return {"status": "error", "message": f"execute.sh not found for configuration '{config_name}'."}
    if not hd_settings.exists():
        return {"status": "error", "message": "hd_settings.json not found."}
    if any(name == config_name for name, _run in state.hotspot_runs):
        return {"status": "skipped", "reason": "already_profiled_in_this_call"}

    if (
        not force
        and state.hotspot_data_is_current
        and private_dir.exists()
        and config_name in _profiled_configurations(hotspot_dir)
    ):
        existing = list(private_dir.glob("hotspot_result_*.txt"))
        if existing:
            last_run_mtime = max(f.stat().st_mtime for f in existing)
            if source_mtime is None or source_mtime <= last_run_mtime:
                return {
                    "status": "skipped",
                    "reason": "results_are_current",
                    "num_runs_accumulated": len(existing),
                }

    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot profiling: execute.sh for config='{config_name}', timeout={timeout_seconds}s",
    )
    exec_result, run, unavailable = _run_in_build(
        project_path, state.build_config or config_name, config_name, "hd", timeout_seconds, ctx
    )
    if exec_result is None or run is None:
        return {"status": "error", "message": unavailable or "The hotspot profiling run did not start."}

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, f"hotspot_profiling[{config_name}]", stdout, ctx)
    if returncode != 0:
        return {
            "status": "error",
            "message": f"Hotspot profiling failed for '{config_name}' (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    results = list((Path(run.dot_discopop) / "hotspot_detection" / "private").glob("hotspot_result_*.txt"))
    if not results:
        return {
            "status": "error",
            "message": (
                f"Binary ran for '{config_name}' but no hotspot_result_*.txt files were created. "
                "Re-run hotspot instrumentation."
            ),
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    state.hotspot_runs.append((config_name, run))
    ctx.log_action(project_path, "gather_data", f"Hotspot profiling done in {elapsed}s: run {run.run_id}")
    return {"status": "success", "elapsed_time": elapsed, "run_id": run.run_id, **warning_fields(stderr)}


def _hotspot_activate(
    project_path: str, timeout_seconds: int, ctx: ToolContext, state: _PipelineState
) -> dict[str, Any]:
    """Put the hotspot runs of this call into the project, where the analysis reads them.

    The runs replace the hotspot data of the project together (their results accumulate for the classification);
    nothing of the project changes if that fails. Without runs, the data of the project is current already.
    """
    if not state.hotspot_runs:
        return {"status": "skipped", "reason": "results_are_current"}
    if ctx.cancelled:
        return {"status": "error", "message": "Cancelled before the hotspot runs were put into the project."}
    arguments = _build_arguments(project_path, timeout_seconds, ctx)
    runs = [run for _name, run in state.hotspot_runs]
    try:
        activate_runs(arguments, runs)
    except ActivationError as error:
        return {
            "status": "error",
            "message": (
                f"The hotspot runs could not be put into the project: {error}. "
                "Call gather_data with force=true to compile and profile again."
            ),
        }
    hotspot_dir = Path(project_path) / ".discopop" / "hotspot_detection"
    names: list[str] = []
    for name, _run in state.hotspot_runs:
        if name not in names:
            names.append(name)
    (hotspot_dir / PROFILED_CONFIGURATIONS_FILE).write_text(json.dumps(names))
    ctx.log_action(project_path, "gather_data", f"Put the hotspot runs {[run.run_id for run in runs]} into the project")
    return {"status": "success", "run_ids": [run.run_id for run in runs]}


def _hotspot_analysis(
    project_path: str, timeout_seconds: int, force: bool, ctx: ToolContext, source_mtime: Optional[float]
) -> dict[str, Any]:
    p = Path(project_path)
    discopop_dir = p / ".discopop"
    private_dir = discopop_dir / "hotspot_detection" / "private"
    hotspots_json = discopop_dir / "hotspot_detection" / "Hotspots.json"

    if not private_dir.exists():
        return {"status": "error", "message": "No hotspot profiling data found (.discopop/hotspot_detection/private/)."}
    result_files = list(private_dir.glob("hotspot_result_*.txt"))
    if not result_files:
        return {"status": "error", "message": "No hotspot_result_*.txt files found."}

    if not force and hotspots_json.exists():
        analysis_mtime = hotspots_json.stat().st_mtime
        if source_mtime is None or source_mtime <= analysis_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(analysis_mtime),
            }

    venv_bin = os.path.dirname(sys.executable)
    env = os.environ.copy()
    if venv_bin not in env.get("PATH", ""):
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    analyzer = shutil.which("discopop_hotspot_analyzer", path=env["PATH"])
    if not analyzer:
        return {"status": "error", "message": "discopop_hotspot_analyzer not found on PATH."}

    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot analysis: invoking discopop_hotspot_analyzer ({len(result_files)} run(s))",
    )
    try:
        proc = ctx.run_process([analyzer], timeout=timeout_seconds, cwd=str(discopop_dir), env=env)
    except subprocess.TimeoutExpired:
        _discard_partial_output(hotspots_json, project_path, ctx)
        return {"status": "error", "message": f"discopop_hotspot_analyzer timed out after {timeout_seconds}s."}

    _log_stdout(project_path, "hotspot_analysis", proc.stdout, ctx)

    if proc.returncode != 0:
        _discard_partial_output(hotspots_json, project_path, ctx)
        return {
            "status": "error",
            "message": f"discopop_hotspot_analyzer failed (rc={proc.returncode}).",
            "returncode": proc.returncode,
            **_stderr_fields(proc.stderr),
        }

    hotness_summary: dict[str, int] = {"YES": 0, "MAYBE": 0, "NO": 0}
    hotspots_found = 0
    if hotspots_json.exists():
        try:
            data = json.loads(hotspots_json.read_text())
            for region in data.get("code_regions", []):
                hotness = region.get("hotness", "")
                if hotness in hotness_summary:
                    hotness_summary[hotness] += 1
                hotspots_found += 1
        except Exception:
            pass

    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot analysis complete: {hotspots_found} regions "
        f"(YES={hotness_summary['YES']}, MAYBE={hotness_summary['MAYBE']}, NO={hotness_summary['NO']})",
    )
    return {"status": "success"}


def _instrument_project(
    project_path: str,
    config_name: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
    state: Optional[_PipelineState] = None,
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    dp_settings = configs_dir / "dp_settings.json"
    profiler_dir = p / ".discopop" / "profiler"
    data_xml = profiler_dir / "Data.xml"
    config_dir = configs_dir / config_name

    if not config_dir.exists():
        return {"status": "error", "message": unknown_configuration_message(configs_dir, config_name)}
    # honours a per-configuration compile.sh override, falling back to the shared script
    compile_sh = Path(resolve_compile_script_path(str(configs_dir), build_owner_of(str(configs_dir), config_name)))
    if not compile_sh.exists():
        return {"status": "error", "message": "compile.sh not found. Run set_compile_script first."}
    if not dp_settings.exists():
        return {"status": "error", "message": "dp_settings.json not found. Run initialize_discopop_directory first."}

    # Skipped only when the profiling output is current as well: if profiling still has to run, it needs the build.
    dyn_deps = profiler_dir / "dynamic_dependencies.txt"
    if (
        not force
        and data_xml.exists()
        and dyn_deps.exists()
        and not _from_other_configuration(project_path, "dp", config_name)
    ):
        result_mtime = min(data_xml.stat().st_mtime, dyn_deps.stat().st_mtime)
        if source_mtime is None or source_mtime <= result_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(result_mtime),
            }

    # the run that follows produces the data of the project anew, even where the build is reused
    if state is not None:
        state.dp_data_is_current = False
    result = _compile_in_build(project_path, config_name, "dp", "Instrumentation", timeout_seconds, force, ctx)
    if result["status"] in ("success", "skipped"):
        built_data_xml = (
            Path(build_tree_path_of(project_path, BuildKey(build_owner_of(str(configs_dir), config_name), "dp", ())))
            / ".discopop"
        )
        if not (built_data_xml / "profiler" / "Data.xml").exists():
            return {
                "status": "error",
                "message": "Compilation succeeded but Data.xml was not created. Ensure discopop_cxx is on PATH.",
                "returncode": 0,
                "elapsed_time": result.get("elapsed_time"),
            }
    return result


def _discard_partial_output(path: Path, project_path: str, ctx: ToolContext) -> None:
    """Delete the output of a step that did not complete.

    A step stopped by a failure, a timeout or a cancel may have written its output
    already, and the next call would take it for a current result and skip the step.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
    ctx.log_action(project_path, "gather_data", f"Discarded the output of an incomplete step: {path}")


def _run_profiling(
    project_path: str,
    config_name: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
    state: Optional[_PipelineState] = None,
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    dp_settings = configs_dir / "dp_settings.json"
    execute_sh = configs_dir / config_name / "execute.sh"
    dyn_deps = p / ".discopop" / "profiler" / "dynamic_dependencies.txt"
    data_is_current = state is None or state.dp_data_is_current

    if not execute_sh.exists():
        return {"status": "error", "message": f"execute.sh not found for configuration '{config_name}'."}
    if not dp_settings.exists():
        return {"status": "error", "message": "dp_settings.json not found."}

    if not force and data_is_current and dyn_deps.exists():
        result_mtime = dyn_deps.stat().st_mtime
        if source_mtime is None or source_mtime <= result_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(result_mtime),
            }

    ctx.log_action(
        project_path,
        "gather_data",
        f"Profiling: execute.sh for config='{config_name}', timeout={timeout_seconds}s",
    )
    exec_result, run, unavailable = _run_in_build(
        project_path, build_owner_of(str(configs_dir), config_name), config_name, "dp", timeout_seconds, ctx
    )
    if exec_result is None or run is None:
        return {"status": "error", "message": unavailable or "The profiling run did not start."}

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, "run_profiling", stdout, ctx)

    if returncode != 0:
        return {
            "status": "error",
            "message": f"Profiling failed (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    if not (Path(run.dot_discopop) / "profiler" / "dynamic_dependencies.txt").exists():
        return {
            "status": "error",
            "message": (
                "Binary ran but dynamic_dependencies.txt was not created. " "Re-run instrumentation and try again."
            ),
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    if ctx.cancelled:
        return {"status": "error", "message": "Cancelled before the run was put into the project."}
    try:
        activate_run(_build_arguments(project_path, timeout_seconds, ctx), run)
    except ActivationError as error:
        return {
            "status": "error",
            "message": (
                f"The profiling run succeeded, but its data could not be put into the project: {error}. "
                "Call gather_data with force=true to compile and profile again."
            ),
            "elapsed_time": elapsed,
        }
    # The static files of the run carry the time of the compilation. The data is as current as this run: a source
    # newer than the build (but not newer than the run) must not make the next call (and get_project_status)
    # take the instrumentation for outdated again.
    try:
        os.utime(p / ".discopop" / "profiler" / "Data.xml", None)
    except OSError:
        pass
    ctx.log_action(project_path, "gather_data", f"Profiling complete in {elapsed}s (run {run.run_id})")
    return {"status": "success", "elapsed_time": elapsed, "run_id": run.run_id, **warning_fields(stderr)}


# the pattern types gather_data detects
DETECTED_PATTERNS = ["task", "doall", "reduction"]


def _detected_patterns(patterns_json: Path) -> set[str]:
    """The pattern types a patterns.json was detected for; none for results which do not say."""
    try:
        with open(patterns_json) as f:
            return set(json.load(f).get("enabled_patterns") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def _run_pattern_detection(
    project_path: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
) -> dict[str, Any]:
    p = Path(project_path)
    discopop_dir = p / ".discopop"
    data_xml = discopop_dir / "profiler" / "Data.xml"
    dyn_deps = discopop_dir / "profiler" / "dynamic_dependencies.txt"
    patterns_json = discopop_dir / "explorer" / "patterns.json"

    if not data_xml.exists():
        return {"status": "error", "message": "profiler/Data.xml not found — instrumentation step must have failed."}
    if not dyn_deps.exists():
        return {
            "status": "error",
            "message": "profiler/dynamic_dependencies.txt not found — profiling step must have failed.",
        }

    if not force and patterns_json.exists() and _detected_patterns(patterns_json) >= set(DETECTED_PATTERNS):
        result_mtime = patterns_json.stat().st_mtime
        if source_mtime is None or source_mtime <= result_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(result_mtime),
            }

    venv_bin = os.path.dirname(sys.executable)
    env = os.environ.copy()
    if venv_bin not in env.get("PATH", ""):
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    explorer = shutil.which("discopop_explorer", path=env["PATH"])
    if not explorer:
        return {"status": "error", "message": "discopop_explorer not found on PATH."}

    ctx.log_action(project_path, "gather_data", "Pattern detection: invoking discopop_explorer")
    try:
        proc = ctx.run_process(
            [explorer, "--enable-patterns", ",".join(DETECTED_PATTERNS)],
            timeout=timeout_seconds,
            cwd=str(discopop_dir),
            env=env,
        )
    except subprocess.TimeoutExpired:
        _discard_partial_output(patterns_json, project_path, ctx)
        return {"status": "error", "message": f"discopop_explorer timed out after {timeout_seconds}s."}

    _log_stdout(project_path, "pattern_detection", proc.stdout, ctx)

    if proc.returncode != 0:
        # it writes patterns.json before it generates the patches
        _discard_partial_output(patterns_json, project_path, ctx)
        return {
            "status": "error",
            "message": f"discopop_explorer failed (rc={proc.returncode}).",
            "returncode": proc.returncode,
            **_stderr_fields(proc.stderr),
        }

    ctx.log_action(project_path, "gather_data", "Pattern detection complete")
    return {"status": "success"}


def _progress(step: int, total: int, label: str, ctx: ToolContext) -> None:
    # Steps completed so far, so the client sees the fraction that is done.
    ctx.report_progress(step - 1, total, f"[{step}/{total}] {label}")
    from termcolor import colored

    prefix = colored(f"[gather_data {step}/{total}]", "cyan", attrs=["bold"])
    sys.stderr.write(f"\r{prefix} {label}...\n")
    sys.stderr.flush()


def count_suggestions(project_path: str) -> Optional[int]:
    """How many parallelization suggestions the explorer produced, or None if unknown."""
    patch_gen_dir = Path(project_path) / ".discopop" / "patch_generator"
    if not patch_gen_dir.is_dir():
        return None
    try:
        return len([entry for entry in patch_gen_dir.iterdir() if entry.is_dir() and entry.name.isdigit()])
    except OSError:
        return None


def next_step_hint(suggestion_count: Optional[int]) -> str:
    """What to do with the suggestions that were just generated."""
    if suggestion_count == 0:
        return (
            "No parallelization suggestion was found. explain_parallelization tells for a given "
            "code region why it was not parallelized, e.g. which data dependency prevents it."
        )
    found = f"{suggestion_count} parallelization suggestions were generated. " if suggestion_count else ""
    return (
        found + "get_parallelization_suggestions lists them, hottest first, and explain_parallelization tells why "
        "a code region has none. Apply a suggestion by editing the source yourself."
    )


def _failed_hotspot_step(steps: dict[str, Any]) -> str:
    """The step of the hotspot detection to look at: the first that did not succeed."""
    if steps["hotspot_instrumentation"]["status"] not in ("success", "skipped"):
        return "hotspot_instrumentation"
    if any(run["status"] not in ("success", "skipped") for run in steps.get("hotspot_profiling", [])):
        return "hotspot_profiling"
    if steps.get("hotspot_activation", {}).get("status") == "error":
        return "hotspot_activation"
    return "hotspot_analysis"


def _cancelled_result(project_path: str, steps: dict[str, Any]) -> dict[str, Any]:
    """The result of a call the client cancelled; the steps that ran are kept."""
    return {
        "status": "error",
        "message": "Cancelled by the client.",
        "cancelled": True,
        "steps": steps,
    }


def _pipeline(
    project_path: str,
    config_name: str,
    hotspot_config_names: list[str],
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
) -> dict[str, Any]:
    """The data collection pipeline itself, as a result dict.

    Separated from :func:`handle`, which adds what belongs to every exit path of the pipeline
    (the early returns below for a failed instrumentation, profiling or detection).
    """
    steps: dict[str, Any] = {}
    hotspot_ok = True
    state = _PipelineState(
        build_config=build_owner_of(str(Path(project_path) / ".discopop" / "project" / "configs"), config_name)
    )

    # Compute source mtime once and reuse across all staleness checks.
    source_mtime = ToolContext.newest_source_mtime(project_path)
    # an edited execute.sh (another input) means the runs are due again, which does not compile again: the build
    # does not depend on it
    configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
    for name in {config_name, *hotspot_config_names}:
        try:
            mtime = (configs_dir / name / "execute.sh").stat().st_mtime
        except OSError:
            continue
        source_mtime = mtime if source_mtime is None else max(source_mtime, mtime)

    total_steps = 6  # 3 hotspot steps, instrument + profile + detect
    step = 0

    # === Hotspot detection ===
    step += 1
    _progress(step, total_steps, "Hotspot instrumentation", ctx)
    hd_instr = _hotspot_instrument(
        project_path, config_name, hotspot_config_names, timeout_seconds, force, ctx, source_mtime, state
    )
    steps["hotspot_instrumentation"] = hd_instr

    if hd_instr["status"] in ("success", "skipped") and not ctx.cancelled:
        step += 1
        _progress(step, total_steps, f"Hotspot profiling ({len(hotspot_config_names)} config(s))", ctx)
        profiling_runs: list[dict[str, Any]] = []
        for hd_config in hotspot_config_names:
            if ctx.cancelled:
                break
            run_res = _hotspot_profiling_single(
                project_path, hd_config, timeout_seconds, force, ctx, source_mtime, state
            )
            profiling_runs.append({"config": hd_config, **run_res})
        steps["hotspot_profiling"] = profiling_runs

        if not ctx.cancelled and all(r["status"] in ("success", "skipped") for r in profiling_runs):
            # the runs of all hotspot configurations are put into the project together
            activation = _hotspot_activate(project_path, timeout_seconds, ctx, state)
            if activation.get("status") != "skipped":
                steps["hotspot_activation"] = activation
            step += 1
            if activation["status"] in ("success", "skipped"):
                _progress(step, total_steps, "Hotspot analysis", ctx)
                hd_analysis = _hotspot_analysis(project_path, timeout_seconds, force, ctx, source_mtime)
                steps["hotspot_analysis"] = hd_analysis
                if hd_analysis["status"] not in ("success", "skipped"):
                    hotspot_ok = False
            else:
                hotspot_ok = False
                steps["hotspot_analysis"] = {"status": "not_run", "reason": "hotspot_activation_failed"}
        else:
            step += 1
            hotspot_ok = False
            steps["hotspot_analysis"] = {"status": "not_run", "reason": "hotspot_profiling_failed"}
    else:
        step += 2
        hotspot_ok = False
        steps["hotspot_profiling"] = []
        steps["hotspot_analysis"] = {"status": "not_run", "reason": "hotspot_instrumentation_failed"}

    # The suggestions are ranked by the hotspots, so there is nothing to continue with.
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    if not hotspot_ok and _failed_hotspot_step(steps) == "hotspot_activation":
        return {
            "status": "error",
            "message": "Hotspot detection failed. See steps.hotspot_activation for details.",
            "steps": steps,
            "next_step": (
                "The hotspot runs succeeded, but their data could not be put into the project (see "
                "steps.hotspot_activation.message). Call gather_data again with force=true, which compiles and "
                "profiles anew."
            ),
        }
    if not hotspot_ok:
        failed_step = _failed_hotspot_step(steps)
        return {
            "status": "error",
            "message": f"Hotspot detection failed. See steps.{failed_step} for details.",
            "steps": steps,
            "next_step": (
                f"steps.{failed_step} names the problem, and its stderr, if present, holds the errors. Fix the "
                "build (compile.sh) with set_compile_script (it must use $CC/$CXX and $CFLAGS/$CXXFLAGS) or the "
                "configurations passed as hotspot_config_names with create_execution_configuration (a smaller "
                "input helps if a run timed out), then call gather_data again."
            ),
        }

    # === Required: instrument project ===
    step += 1
    _progress(step, total_steps, "DiscoPoP instrumentation (compile)", ctx)
    instr = _instrument_project(project_path, config_name, timeout_seconds, force, ctx, source_mtime, state)
    steps["instrumentation"] = instr
    # a cancel stops the running step, which then fails; that failure is not the answer
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    if instr["status"] not in ("success", "skipped"):
        result: dict[str, Any] = {
            "status": "error",
            "message": "Instrumentation failed. See steps.instrumentation for details.",
            "steps": steps,
        }
        # Only a step that ran and failed has output to look at. One refused by its
        # pre-flight checks, or that exited 0 without producing its output, names the
        # problem in its own message.
        if instr.get("returncode") not in (None, 0):
            result["next_step"] = (
                "steps.instrumentation.stderr holds the build errors. Fix the build with "
                "set_compile_script (it must use $CC/$CXX and "
                "$CFLAGS/$CXXFLAGS), then call gather_data again."
            )
        return result

    # === Required: run instrumented binary ===
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    step += 1
    _progress(step, total_steps, "Profiling (run instrumented binary)", ctx)
    prof = _run_profiling(project_path, config_name, timeout_seconds, force, ctx, source_mtime, state)
    steps["profiling"] = prof
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    if prof["status"] not in ("success", "skipped"):
        result = {
            "status": "error",
            "message": "Profiling failed. See steps.profiling for details.",
            "steps": steps,
        }
        if prof.get("returncode") not in (None, 0):
            result["next_step"] = (
                "steps.profiling.stderr holds the program's errors. Fix execute.sh with "
                "create_execution_configuration (a smaller input helps if "
                "the run timed out), then call gather_data again."
            )
        return result

    # === Required: pattern detection ===
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    step += 1
    _progress(step, total_steps, "Pattern detection (discopop_explorer)", ctx)
    detection = _run_pattern_detection(project_path, timeout_seconds, force, ctx, source_mtime)
    steps["pattern_detection"] = detection
    if ctx.cancelled:
        return _cancelled_result(project_path, steps)
    if detection["status"] not in ("success", "skipped"):
        result = {
            "status": "error",
            "message": "Pattern detection failed. See steps.pattern_detection for details.",
            "steps": steps,
            "next_step": (
                "If the profiling data is stale or inconsistent, call initialize_discopop_directory "
                "with reset=true to clear the analysis artefacts, then gather_data again."
            ),
        }
        return result

    from termcolor import colored

    sys.stderr.write(f"\r{colored('[gather_data]', 'green', attrs=['bold'])} Pipeline complete.\n")
    sys.stderr.flush()

    result = {
        "steps": steps,
    }
    # What to do with the patches is the question this pipeline exists to raise, and a
    # result is read far more reliably than a tool description. Saying how many there
    # are and which tool decides between them is what keeps the next step from being a
    # guess made out of the source code.
    suggestion_count = count_suggestions(project_path)
    if suggestion_count is not None:
        result["suggestions_found"] = suggestion_count
    result["next_step"] = next_step_hint(suggestion_count)
    return result


def _storage_warning(project_path: str, config_name: str, ctx: ToolContext) -> Optional[str]:
    """The warning about the builds and runs of the project (see ``storage_warning``); never fails the call."""
    if not (Path(project_path) / ".discopop").is_dir():
        return None  # the arguments of the project manager exit the process for a project without one
    try:
        expected = [
            BuildKey(
                build_owner_of(str(Path(project_path) / ".discopop" / "project" / "configs"), config_name), mode, ()
            ).build_id
            for mode in ("hd", "dp")
        ]
        return storage_warning(ctx.make_pm_args(project_path), expected)
    except Exception as error:
        logger.warning("The storage of the builds could not be determined: %s", error)
        return None


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        config_name = arguments.get("config_name", "")
        hotspot_config_names: list[str] = arguments.get("hotspot_config_names") or [config_name]
        timeout_seconds: int = arguments.get("timeout_seconds", 3600)
        force: bool = arguments.get("force", False)
        for name in [config_name, *hotspot_config_names]:
            name_error = invalid_configuration_name(name)
            if name_error is not None:
                return ctx.error(name_error, project_path, "gather_data")
        # A single step (an instrumented run, above all) can take an hour; the heartbeat
        # keeps reporting the step in progress so the client knows the call is alive.
        with ctx.heartbeat():
            result = _pipeline(project_path, config_name, hotspot_config_names, timeout_seconds, force, ctx)

            # builds and runs pile up: say how much they occupy, once there are more than the call works with
            warning = _storage_warning(project_path, config_name, ctx)
            if warning:
                result["warning"] = f"{result['warning']} {warning}" if result.get("warning") else warning

        ctx.log_response("gather_data", result, project_path)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error in gather_data: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]
