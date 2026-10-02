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
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from mcp_server.tools.helpers import (
    ToolContext,
    invalid_configuration_name,
    recorded_applied_suggestions,
    tail_of_output,
    unknown_configuration_message,
)

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="gather_data",
    # Overwrites the previous analysis results and rebuilds the project in place. A
    # repeated call skips every step whose outputs are current, hence idempotent.
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
    description=(
        "Run the complete DiscoPoP data collection pipeline and detect parallelization patterns. "
        "Call this after set_compile_script and create_execution_configuration. "
        "\n\n"
        "The pipeline consists of two phases:\n"
        "\n"
        "OPTIONAL — Hotspot detection (enabled when hotspot_config_names is non-empty):\n"
        "  1. Compile with hotspot instrumentation (hd_settings.json).\n"
        "  2. Run the binary once per config in hotspot_config_names to accumulate timing data.\n"
        "     Use at least 2 configs with different input sizes for accurate classification.\n"
        "  3. Analyse timing data to classify regions as YES/MAYBE/NO hotspots.\n"
        "  If hotspot detection is enabled, pattern analysis focuses on hotspot regions.\n"
        "  If omitted, pattern analysis covers the entire codebase.\n"
        "\n"
        "REQUIRED — Data collection and pattern detection:\n"
        "  4. Compile with DiscoPoP instrumentation (dp_settings.json).\n"
        "  5. Run the instrumented binary to collect runtime dependency traces.\n"
        "     NOTE: significant runtime overhead expected — use small inputs.\n"
        "  6. Analyse with discopop_explorer to detect parallelization opportunities.\n"
        "\n"
        "Each step is automatically skipped when its outputs are already current "
        "relative to the source files. Use force=true to re-run all steps unconditionally. "
        "\n\n"
        "Steps 1 and 4 compile in the project itself, so the project's build directory is "
        "rebuilt plainly (par_settings.json) before this tool returns: a build left over "
        "from instrumentation produces binaries that are orders of magnitude slower than "
        "the program and may abort, so building and running the program by hand afterwards "
        "is safe. "
        "\n\n"
        "On success, call run_auto_tuning to measure which combination of the generated "
        "suggestions is fastest (apply=true also applies it); get_parallelization_patches lists them."
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
                    "Optional. List of configuration names for hotspot profiling runs (step 2). "
                    "At least 1 name is required to enable hotspot detection. "
                    "Using ≥2 configs with different input sizes improves classification accuracy, "
                    "but a single config is accepted (results may be less accurate). "
                    "If omitted, hotspot detection is skipped entirely."
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


def _record_profiled_configuration(hotspot_dir: Path, config_name: str) -> None:
    names = _profiled_configurations(hotspot_dir)
    if config_name not in names:
        (hotspot_dir / PROFILED_CONFIGURATIONS_FILE).write_text(json.dumps(names + [config_name]))


def _hotspot_instrument(
    project_path: str,
    config_name: str,
    hotspot_config_names: list[str],
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
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
    compile_sh = Path(resolve_compile_script_path(str(configs_dir), config_name))
    if not compile_sh.exists():
        return {"status": "error", "message": "compile.sh not found. Run set_compile_script first."}
    if not hd_settings.exists():
        return {"status": "error", "message": "hd_settings.json not found. Run initialize_discopop_directory first."}

    # Skipped only when the results cover exactly the requested configurations: the plain
    # rebuild at the end of every call leaves no instrumented binary behind, so profiling a
    # configuration that is missing needs this step, and re-instrumenting clears the results
    # of every other configuration as well.
    if not force and private_dir.exists() and set(_profiled_configurations(hotspot_dir)) == set(hotspot_config_names):
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

    if hotspot_dir.exists():
        shutil.rmtree(str(hotspot_dir))
        ctx.log_action(project_path, "gather_data", "Deleted stale .discopop/hotspot_detection/")

    pm_args = ctx.make_pm_args(project_path, timeout_seconds)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot instrumentation: {compile_sh} via hd_settings, config='{config_name}', "
        f"timeout={timeout_seconds}s",
    )
    original_cwd = os.getcwd()
    try:
        exec_result = execute_configuration(
            arguments=pm_args,
            project_copy_root_path=project_path,
            config_path=str(config_dir),
            settings_path=str(hd_settings),
            script_path=str(compile_sh),
            thread_count=1,
            timeout=float(timeout_seconds),
            process_started_callback=ctx.track_process,
        )
    finally:
        os.chdir(original_cwd)

    # From here on the project's own build directory has been reconfigured for
    # instrumentation, whatever the outcome -- which is what `_restore_plain_build`
    # has to know, and cannot tell from a status alone: a pre-flight error never
    # touched the build, a failed compile did.
    if exec_result is None:
        return {
            "status": "error",
            "message": "execute_configuration returned None for hd_settings.json.",
            "compiled_in_place": True,
        }

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, "hotspot_instrument", stdout, ctx)

    if returncode != 0:
        return {
            "status": "error",
            "message": f"Hotspot instrumentation failed (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
            "compiled_in_place": True,
        }
    ctx.log_action(project_path, "gather_data", f"Hotspot instrumentation succeeded in {elapsed}s")
    return {"status": "success", "elapsed_time": elapsed, "compiled_in_place": True}


def _hotspot_profiling_single(
    project_path: str,
    config_name: str,
    timeout_seconds: int,
    force: bool,
    ctx: ToolContext,
    source_mtime: Optional[float],
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    hd_settings = configs_dir / "hd_settings.json"
    execute_sh = configs_dir / config_name / "execute.sh"
    hotspot_dir = p / ".discopop" / "hotspot_detection"
    private_dir = hotspot_dir / "private"

    if not execute_sh.exists():
        return {"status": "error", "message": f"execute.sh not found for configuration '{config_name}'."}
    if not hd_settings.exists():
        return {"status": "error", "message": "hd_settings.json not found."}

    if not force and private_dir.exists() and config_name in _profiled_configurations(hotspot_dir):
        existing = list(private_dir.glob("hotspot_result_*.txt"))
        if existing:
            last_run_mtime = max(f.stat().st_mtime for f in existing)
            if source_mtime is None or source_mtime <= last_run_mtime:
                return {
                    "status": "skipped",
                    "reason": "results_are_current",
                    "num_runs_accumulated": len(existing),
                }

    results_before = set(private_dir.glob("hotspot_result_*.txt")) if private_dir.exists() else set()
    pm_args = ctx.make_pm_args(project_path, timeout_seconds)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot profiling: execute.sh for config='{config_name}', timeout={timeout_seconds}s",
    )
    original_cwd = os.getcwd()
    try:
        exec_result = execute_configuration(
            arguments=pm_args,
            project_copy_root_path=project_path,
            config_path=str(configs_dir / config_name),
            settings_path=str(hd_settings),
            script_path=str(execute_sh),
            thread_count=1,
            timeout=float(timeout_seconds),
            process_started_callback=ctx.track_process,
        )
    finally:
        os.chdir(original_cwd)

    if exec_result is None:
        return {"status": "error", "message": "execute_configuration returned None."}

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, f"hotspot_profiling[{config_name}]", stdout, ctx)
    result_files = sorted(private_dir.glob("hotspot_result_*.txt")) if private_dir.exists() else []

    if returncode != 0:
        for added in set(result_files) - results_before:
            _discard_partial_output(added, project_path, ctx)
        return {
            "status": "error",
            "message": f"Hotspot profiling failed for '{config_name}' (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    if not result_files:
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
    _record_profiled_configuration(hotspot_dir, config_name)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Hotspot profiling done in {elapsed}s: {len(result_files)} run(s) accumulated",
    )
    return {"status": "success", "elapsed_time": elapsed}


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
    compile_sh = Path(resolve_compile_script_path(str(configs_dir), config_name))
    if not compile_sh.exists():
        return {"status": "error", "message": "compile.sh not found. Run set_compile_script first."}
    if not dp_settings.exists():
        return {"status": "error", "message": "dp_settings.json not found. Run initialize_discopop_directory first."}

    # Skipped only when the profiling output is current as well. If profiling still has
    # to run, it needs the instrumented binary -- and a previous call restored the plain
    # build before returning (`_restore_plain_build`), so skipping here would have
    # profiling run an uninstrumented program that never writes its dependencies.
    dyn_deps = profiler_dir / "dynamic_dependencies.txt"
    if not force and data_xml.exists() and dyn_deps.exists():
        result_mtime = min(data_xml.stat().st_mtime, dyn_deps.stat().st_mtime)
        if source_mtime is None or source_mtime <= result_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(result_mtime),
            }

    if profiler_dir.exists():
        shutil.rmtree(str(profiler_dir))
        ctx.log_action(project_path, "gather_data", "Deleted stale .discopop/profiler/")

    pm_args = ctx.make_pm_args(project_path, timeout_seconds)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Instrumentation: {compile_sh} via dp_settings, config='{config_name}', timeout={timeout_seconds}s",
    )
    original_cwd = os.getcwd()
    try:
        exec_result = execute_configuration(
            arguments=pm_args,
            project_copy_root_path=project_path,
            config_path=str(config_dir),
            settings_path=str(dp_settings),
            script_path=str(compile_sh),
            thread_count=1,
            timeout=float(timeout_seconds),
            process_started_callback=ctx.track_process,
        )
    finally:
        os.chdir(original_cwd)

    # See the note in `_hotspot_instrument`: past this point the build directory
    # is instrumented regardless of how the step ends.
    if exec_result is None:
        return {
            "status": "error",
            "message": "execute_configuration returned None for dp_settings.json.",
            "compiled_in_place": True,
        }

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, "instrument_project", stdout, ctx)

    if returncode != 0:
        return {
            "status": "error",
            "message": f"Instrumentation failed (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
            "compiled_in_place": True,
        }
    if not data_xml.exists():
        return {
            "status": "error",
            "message": "Compilation succeeded but Data.xml was not created. Ensure discopop_cxx is on PATH.",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
            "compiled_in_place": True,
        }
    ctx.log_action(project_path, "gather_data", f"Instrumentation succeeded in {elapsed}s")
    return {"status": "success", "elapsed_time": elapsed, "compiled_in_place": True}


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
) -> dict[str, Any]:
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    dp_settings = configs_dir / "dp_settings.json"
    execute_sh = configs_dir / config_name / "execute.sh"
    data_xml = p / ".discopop" / "profiler" / "Data.xml"
    dyn_deps = p / ".discopop" / "profiler" / "dynamic_dependencies.txt"

    if not execute_sh.exists():
        return {"status": "error", "message": f"execute.sh not found for configuration '{config_name}'."}
    if not data_xml.exists():
        return {"status": "error", "message": "profiler/Data.xml not found — instrumentation step must have failed."}
    if not dp_settings.exists():
        return {"status": "error", "message": "dp_settings.json not found."}

    if not force and dyn_deps.exists():
        result_mtime = dyn_deps.stat().st_mtime
        if source_mtime is None or source_mtime <= result_mtime:
            return {
                "status": "skipped",
                "reason": "results_are_current",
                "last_run": ToolContext.fmt_ts(result_mtime),
            }

    pm_args = ctx.make_pm_args(project_path, timeout_seconds)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Profiling: execute.sh for config='{config_name}', timeout={timeout_seconds}s",
    )
    original_cwd = os.getcwd()
    try:
        exec_result = execute_configuration(
            arguments=pm_args,
            project_copy_root_path=project_path,
            config_path=str(configs_dir / config_name),
            settings_path=str(dp_settings),
            script_path=str(execute_sh),
            thread_count=1,
            timeout=float(timeout_seconds),
            process_started_callback=ctx.track_process,
        )
    finally:
        os.chdir(original_cwd)

    if exec_result is None:
        return {"status": "error", "message": "execute_configuration returned None."}

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, "run_profiling", stdout, ctx)

    if returncode != 0:
        _discard_partial_output(dyn_deps, project_path, ctx)
        return {
            "status": "error",
            "message": f"Profiling failed (rc={returncode}).",
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    if not dyn_deps.exists():
        return {
            "status": "error",
            "message": (
                "Binary ran but dynamic_dependencies.txt was not created. " "Re-run instrumentation and try again."
            ),
            "returncode": returncode,
            "elapsed_time": elapsed,
            **_stderr_fields(stderr),
        }
    ctx.log_action(project_path, "gather_data", f"Profiling complete in {elapsed}s")
    return {"status": "success", "elapsed_time": elapsed}


def _run_pattern_detection(
    project_path: str, timeout_seconds: int, force: bool, ctx: ToolContext, source_mtime: Optional[float]
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

    if not force and patterns_json.exists():
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
        proc = ctx.run_process([explorer], timeout=timeout_seconds, cwd=str(discopop_dir), env=env)
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


def _compiled_in_place(steps: dict[str, Any]) -> bool:
    """Whether any step of this call reconfigured the project's own build.

    Read off the ``compiled_in_place`` marker the two instrumentation steps set
    once their ``execute_configuration`` call has run, rather than guessed from
    a status: a step that failed its pre-flight checks never touched the build,
    while one whose compilation failed left it instrumented and half-built --
    the case most in need of restoring, and the one a status cannot tell apart.
    """
    return any(
        isinstance(steps.get(key), dict) and bool(steps[key].get("compiled_in_place"))
        for key in ("hotspot_instrumentation", "instrumentation")
    )


def _restore_plain_build(
    project_path: str,
    config_name: str,
    timeout_seconds: int,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Rebuild the project plainly, undoing what the instrumented builds left.

    The instrumentation steps above run *in place* (``execute_inplace=True``,
    ``project_copy_root_path=project_path``) rather than in the sibling copy the
    ProjectManager flow uses -- the profiling output has to land in this
    project's ``.discopop``. A compile script normally configures a build
    directory of its own, so when the last thing that ran was ``dp_settings``
    or ``hd_settings``, whatever it left behind is pinned to ``discopop_cc`` /
    ``discopop_cxx``: an ordinary ``make`` in it produces an instrumented
    binary, and running that binary is orders of magnitude slower than the
    program and may abort outright.

    Nobody asked for that state and nothing announces it, so an agent (or a
    person) who builds and runs the program to check their own work measures
    DiscoPoP's instrumentation instead and reads the crash as their bug. One
    observed run lost six minutes to three such executions and then discarded a
    working parallelization because of them. So the build is put back before
    this tool returns, with ``par_settings.json`` -- the configuration the
    parallelized code is measured with, so a hand-run of the program now agrees
    with what the auto-tuner reports -- falling back to ``seq_settings.json``.

    Best effort by design: the data this tool exists to produce is already on
    disk by the time this runs, so a failed rebuild is reported and logged, but
    never turns a successful pipeline into a failed one.
    """
    p = Path(project_path)
    configs_dir = p / ".discopop" / "project" / "configs"
    config_dir = configs_dir / config_name
    compile_sh = Path(resolve_compile_script_path(str(configs_dir), config_name))

    settings = configs_dir / "par_settings.json"
    if not settings.exists():
        settings = configs_dir / "seq_settings.json"
    if not settings.exists():
        return {"status": "skipped", "reason": "no_plain_settings_file"}
    if not compile_sh.exists() or not config_dir.exists():
        return {"status": "skipped", "reason": "compile_script_or_configuration_missing"}

    pm_args = ctx.make_pm_args(project_path, timeout_seconds)
    ctx.log_action(
        project_path,
        "gather_data",
        f"Restoring plain build: {compile_sh} via {settings.name}, config='{config_name}'",
    )
    original_cwd = os.getcwd()
    try:
        exec_result = execute_configuration(
            arguments=pm_args,
            project_copy_root_path=project_path,
            config_path=str(config_dir),
            settings_path=str(settings),
            script_path=str(compile_sh),
            thread_count=1,
            timeout=float(timeout_seconds),
            # not registered: the rebuild undoes the instrumented builds after a cancel, too
            process_started_callback=None,
        )
    except Exception as error:  # a cleanup step may not take the pipeline down
        ctx.log_action(project_path, "gather_data", f"Plain rebuild raised: {error}")
        return {"status": "error", "message": f"Plain rebuild raised: {error}", "settings": settings.name}
    finally:
        os.chdir(original_cwd)

    if exec_result is None:
        return {"status": "error", "message": "execute_configuration returned None.", "settings": settings.name}

    returncode, elapsed, stdout, stderr = exec_result
    _log_stdout(project_path, "restore_plain_build", stdout, ctx)
    if returncode != 0:
        ctx.log_action(
            project_path,
            "gather_data",
            f"Plain rebuild failed (rc={returncode}); the build directory may still be instrumented",
        )
        return {
            "status": "error",
            "message": (
                f"Plain rebuild failed (rc={returncode}). The build directory may still hold an "
                "instrumented binary -- rebuild from scratch before running the program by hand."
            ),
            "returncode": returncode,
            "elapsed_time": elapsed,
            "settings": settings.name,
            **_stderr_fields(stderr),
        }
    ctx.log_action(project_path, "gather_data", f"Plain build restored in {elapsed}s")
    return {"status": "success", "elapsed_time": elapsed, "settings": settings.name}


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
    """What to do with the patches that were just generated."""
    if suggestion_count == 0:
        return (
            "No parallelization suggestion was found. explain_parallelization tells for a given "
            "code region why it was not parallelized, e.g. which data dependency prevents it."
        )
    found = f"{suggestion_count} parallelization suggestions were generated. " if suggestion_count else ""
    return (
        found + "Call run_auto_tuning to have DiscoPoP measure which combination of them is "
        "fastest (add apply=true to apply that combination in the same call) — do this before "
        "applying anything, since the search needs an un-patched project. "
        "get_parallelization_patches lists the suggestions, and get_data_dependencies "
        "explains the dependencies behind an individual one."
    )


def _cancelled_result(project_path: str, hotspot_detection_enabled: bool, steps: dict[str, Any]) -> dict[str, Any]:
    """The result of a call the client cancelled; the steps that ran are kept, since the
    plain rebuild after the pipeline depends on knowing what was compiled in place."""
    return {
        "status": "error",
        "project_path": project_path,
        "message": "Cancelled by the client.",
        "cancelled": True,
        "hotspot_detection_enabled": hotspot_detection_enabled,
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

    Separated from :func:`handle` so that the build directory the instrumented
    steps reconfigure is restored on *every* exit path: the early returns below
    for a failed instrumentation, profiling or detection all leave a project
    whose build produces instrumented binaries, and those are exactly the cases
    where the caller is most likely to go and run the program by hand.
    """
    steps: dict[str, Any] = {}
    hotspot_detection_enabled = len(hotspot_config_names) >= 1
    hotspot_ok = True

    # Compute source mtime once and reuse across all staleness checks.
    source_mtime = ToolContext.newest_source_mtime(project_path)

    num_hd_steps = 3 if hotspot_detection_enabled else 0
    total_steps = num_hd_steps + 3  # instrument + profile + detect
    step = 0

    # === Optional: hotspot detection pipeline ===
    if hotspot_detection_enabled:
        step += 1
        _progress(step, total_steps, "Hotspot instrumentation", ctx)
        hd_instr = _hotspot_instrument(
            project_path, config_name, hotspot_config_names, timeout_seconds, force, ctx, source_mtime
        )
        steps["hotspot_instrumentation"] = hd_instr

        if hd_instr["status"] in ("success", "skipped") and not ctx.cancelled:
            step += 1
            _progress(step, total_steps, f"Hotspot profiling ({len(hotspot_config_names)} config(s))", ctx)
            profiling_runs: list[dict[str, Any]] = []
            for hd_config in hotspot_config_names:
                if ctx.cancelled:
                    break
                run_res = _hotspot_profiling_single(project_path, hd_config, timeout_seconds, force, ctx, source_mtime)
                profiling_runs.append({"config": hd_config, **run_res})
            steps["hotspot_profiling"] = profiling_runs

            if not ctx.cancelled and all(r["status"] in ("success", "skipped") for r in profiling_runs):
                step += 1
                _progress(step, total_steps, "Hotspot analysis", ctx)
                hd_analysis = _hotspot_analysis(project_path, timeout_seconds, force, ctx, source_mtime)
                steps["hotspot_analysis"] = hd_analysis
                if hd_analysis["status"] not in ("success", "skipped"):
                    hotspot_ok = False
            else:
                step += 1
                hotspot_ok = False
                steps["hotspot_analysis"] = {"status": "not_run", "reason": "hotspot_profiling_failed"}
        else:
            step += 2
            hotspot_ok = False
            steps["hotspot_profiling"] = []
            steps["hotspot_analysis"] = {"status": "not_run", "reason": "hotspot_instrumentation_failed"}

    # === Required: instrument project ===
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    step += 1
    _progress(step, total_steps, "DiscoPoP instrumentation (compile)", ctx)
    instr = _instrument_project(project_path, config_name, timeout_seconds, force, ctx, source_mtime)
    steps["instrumentation"] = instr
    # a cancel stops the running step, which then fails; that failure is not the answer
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    if instr["status"] not in ("success", "skipped"):
        result: dict[str, Any] = {
            "status": "error",
            "project_path": project_path,
            "message": "Instrumentation failed. See steps.instrumentation for details.",
            "hotspot_detection_enabled": hotspot_detection_enabled,
            "steps": steps,
        }
        # Only a step that ran and failed has output to look at. One refused by its
        # pre-flight checks, or that exited 0 without producing its output, names the
        # problem in its own message.
        if instr.get("returncode") not in (None, 0):
            result["next_step"] = (
                "steps.instrumentation.stderr holds the build errors; get_execution_results("
                "script='compile.sh', failed_only=true, include_output=true) also shows stdout. Fix the build with set_compile_script (it must use $CC/$CXX and "
                "$CFLAGS/$CXXFLAGS), then call gather_data again."
            )
        return result

    # === Required: run instrumented binary ===
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    step += 1
    _progress(step, total_steps, "Profiling (run instrumented binary)", ctx)
    prof = _run_profiling(project_path, config_name, timeout_seconds, force, ctx, source_mtime)
    steps["profiling"] = prof
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    if prof["status"] not in ("success", "skipped"):
        result = {
            "status": "error",
            "project_path": project_path,
            "message": "Profiling failed. See steps.profiling for details.",
            "hotspot_detection_enabled": hotspot_detection_enabled,
            "steps": steps,
        }
        if prof.get("returncode") not in (None, 0):
            result["next_step"] = (
                "steps.profiling.stderr holds the program's errors; get_execution_results("
                "script='execute.sh', failed_only=true, include_output=true) also shows stdout. Fix execute.sh with create_execution_configuration (a smaller input helps if "
                "the run timed out), then call gather_data again."
            )
        return result

    # === Required: pattern detection ===
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    step += 1
    _progress(step, total_steps, "Pattern detection (discopop_explorer)", ctx)
    detection = _run_pattern_detection(project_path, timeout_seconds, force, ctx, source_mtime)
    steps["pattern_detection"] = detection
    if ctx.cancelled:
        return _cancelled_result(project_path, hotspot_detection_enabled, steps)
    if detection["status"] not in ("success", "skipped"):
        result = {
            "status": "error",
            "project_path": project_path,
            "message": "Pattern detection failed. See steps.pattern_detection for details.",
            "hotspot_detection_enabled": hotspot_detection_enabled,
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
        "status": "success",
        "project_path": project_path,
        "hotspot_detection_enabled": hotspot_detection_enabled,
        "steps": steps,
    }
    if hotspot_detection_enabled and not hotspot_ok:
        result["warning"] = "Hotspot detection failed; pattern analysis covers the entire codebase."
    # What to do with the patches is the question this pipeline exists to raise, and a
    # result is read far more reliably than a tool description. Saying how many there
    # are and which tool decides between them is what keeps the next step from being a
    # guess made out of the source code.
    suggestion_count = count_suggestions(project_path)
    if suggestion_count is not None:
        result["suggestions_found"] = suggestion_count
    result["next_step"] = next_step_hint(suggestion_count)
    return result


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        config_name = arguments.get("config_name", "")
        hotspot_config_names: list[str] = arguments.get("hotspot_config_names") or []
        timeout_seconds: int = arguments.get("timeout_seconds", 3600)
        force: bool = arguments.get("force", False)
        for name in [config_name, *hotspot_config_names]:
            name_error = invalid_configuration_name(name)
            if name_error is not None:
                return ctx.error(name_error, project_path, "gather_data")
        # Profiling patched sources analyses the parallel code, and the pattern detection
        # deletes the applicator's record of what it applied, which a rollback needs.
        applied, _ = recorded_applied_suggestions(project_path)
        if applied:
            return ctx.error(
                f"The suggestions {applied} are applied to the sources. Analysing them would profile the "
                "parallelized code, and re-running the pattern detection deletes the record needed to roll "
                "them back. Roll them back first with manage_patches(action='clear'), then call gather_data "
                "again.",
                project_path,
                "gather_data",
            )

        # A single step (an instrumented run, above all) can take an hour; the heartbeat
        # keeps reporting the step in progress so the client knows the call is alive.
        with ctx.heartbeat():
            result = _pipeline(project_path, config_name, hotspot_config_names, timeout_seconds, force, ctx)

            # Leave the project buildable by hand again. Only when something was
            # actually compiled in place: a call that skipped every instrumentation
            # step because its results were current found -- and leaves -- the build
            # the previous call already restored, and a rebuild would be waste.
            steps = result.get("steps") or {}
            if _compiled_in_place(steps):
                # After the last step: report_progress keeps the value increasing.
                ctx.report_progress(0, None, "Rebuilding the project without instrumentation")
                restore = _restore_plain_build(project_path, config_name, timeout_seconds, ctx)
                steps["build_restore"] = restore
                result["steps"] = steps
                if restore.get("status") == "error":
                    # Reported, never fatal: the data this tool exists to produce is
                    # already on disk.
                    warning = str(restore.get("message") or "The plain rebuild failed.")
                    result["warning"] = f"{result['warning']} {warning}" if result.get("warning") else warning

        ctx.log_response("gather_data", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error in gather_data: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]
