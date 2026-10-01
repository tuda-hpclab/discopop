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
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.detailed_hotspot_loader import hotspots_json_path, load_detailed_hotspots
from discopop_library.ProjectManager.configurations.validation import VALIDATE_SCRIPT_NAME
from discopop_library.ProjectManager.gui.plots.data import parse_progress_jsonl
from mcp_server.tools.helpers import (
    APPLICATOR_OK_RETURNCODES,
    ToolContext,
    applicator_failure_details,
    invalid_configuration_name,
    read_application_result,
    read_applied_suggestions,
    run_patch_applicator,
    terminate_process_tree,
)

logger = logging.getLogger("discopop-mcp")

# Preferred algorithm: deterministic and measurement-frugal, but only meaningful with
# hotspot detection results. Without those, the greedy forward search is the fallback:
# it needs no hotspot information and still terminates in O(N) evaluations.
HOTSPOT_GUIDED_ALGORITHM = "hotspot_guided"
FALLBACK_ALGORITHM = "greedy"
# The search algorithms by name, and the -A value of discopop_auto_tuner each one stands for.
# Callers name them; the numbers are an implementation detail of the tuner's command line
# (2 is not assigned there), but are still accepted, as earlier versions of this tool took them.
ALGORITHMS = {
    "independent": 0,
    "linear": 1,
    "evolutionary": 3,
    "greedy": 4,
    "coordinate_descent": 5,
    "hotspot_guided": 6,
}
DEFAULT_TIMEOUT_SECONDS = 3600
# How long the tuner and its children get to shut down after SIGTERM before SIGKILL.
_KILL_GRACE_SECONDS = 10.0
# Only the tail of the tuner's output is kept; it is used for error reporting, the full
# output goes to the server log line by line.
_OUTPUT_TAIL_LINES = 40

TOOL = Tool(
    name="run_auto_tuning",
    description=(
        "Measure which combination of the generated parallelization suggestions is "
        "actually fastest, and return it as a list of suggestion IDs — optionally applying "
        "it in the same call (apply=true).\n\n"
        "This is the answer to 'which of these patches should I apply?'. The autotuner "
        "compiles, executes and validates candidate combinations in throwaway copies of the "
        "project and keeps the fastest one that still produces a valid result, so the "
        "selection is measured rather than guessed. Call it after gather_data.\n\n"
        "By default the tool leaves the sources as it found them and only reports the "
        "selection, which manage_patches(action='apply', suggestion_ids=[...]) then "
        "persists. Pass apply=true to have the selected combination applied right away, "
        "which is the shortest route from profiling data to parallelized code.\n\n"
        "Patches that are already applied are cleared before the search (the tuner has to "
        "measure an un-patched project) and restored afterwards — unless apply=true, where "
        "the new selection replaces them. Nothing has to be cleared by hand.\n\n"
        "Preconditions:\n"
        "  - gather_data must have been run (patches, line mapping and detection results "
        "must exist).\n"
        "  - For the best search, run gather_data with hotspot_config_names set (ideally two "
        "configurations of different input sizes). Omit 'algorithm' and the tool then picks "
        "the hotspot-guided search; without hotspot results it falls back to the greedy "
        "forward search on its own.\n\n"
        "COST: this is a measurement run — one compilation plus one execution of the project "
        "per candidate. The hotspot-guided search evaluates a few candidates per hot code "
        "region, the greedy search roughly one per suggestion. Bound it with "
        "timeout_seconds; when the timeout expires the search stops and the best "
        "combination measured so far is still returned, with status 'timeout'.\n\n"
        "How far the correctness claim reaches depends on the configuration: without a "
        "validate.sh a candidate counts as valid as soon as it exits with code 0, so a "
        "parallelization that corrupts the output is indistinguishable from a correct one. "
        "Define validate.sh via create_execution_configuration(validate_script_body=...) "
        "before tuning whenever the program's output can be checked. The result carries a "
        "'warnings' list whenever the selection rests on weaker evidence than it appears to.\n\n"
        "To measure one given selection instead of searching, pass suggestion_ids (the ids "
        "returned by get_parallelization_patches). The tool then measures exactly that "
        "selection against the un-patched project — no other combination is tried — and "
        "reports its runtime, its speedup and in 'outcome' whether it built, ran and "
        "produced a valid result. apply=true applies it whenever that outcome is 'valid', even "
        "if it is slower than the un-patched project. The "
        "stored result of the last search is kept. "
        "Use it to check a specific combination; to find the fastest one, run the search."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory (the parent of .discopop).",
            },
            "config_name": {
                "type": "string",
                "description": (
                    "Name of the execution configuration to tune. Must match a directory "
                    "under .discopop/project/configs/. Its execute.sh should use an input "
                    "that is representative of a production run — the selection is only as "
                    "meaningful as the workload it was measured on."
                ),
            },
            "algorithm": {
                # the integers are the names' -A values, accepted for earlier callers
                "anyOf": [
                    {"type": "string", "enum": list(ALGORITHMS)},
                    {"type": "integer", "enum": list(ALGORITHMS.values())},
                ],
                "description": (
                    "Search algorithm. Omit this to let the tool choose: hotspot_guided when hotspot "
                    "detection results are available, otherwise greedy. The chosen algorithm and the "
                    "reason are reported back in 'algorithm' and 'algorithm_selection'. "
                    "Pass a value only to override that choice; an explicit hotspot_guided without "
                    "hotspot results is refused rather than silently replaced.\n"
                    "  independent — no combination; measures every suggestion on its own.\n"
                    "  linear — accumulates suggestions that keep the result valid.\n"
                    "  evolutionary — uses randomness, so it is not reproducible.\n"
                    "  greedy — forward search; one pass over all suggestions, O(N) evaluations. "
                    "Needs no hotspot information, which is why it is the fallback.\n"
                    "  coordinate_descent — repeated bit-flip passes until no pass improves.\n"
                    "  hotspot_guided — region descent; deterministic and measurement-frugal, "
                    "but requires hotspot detection results."
                ),
            },
            "suggestion_ids": {
                "type": "array",
                "items": {"type": ["string", "integer"]},
                "description": (
                    "Measure exactly this selection of suggestions instead of running a search. "
                    "IDs are the pattern_id values returned by get_parallelization_patches; "
                    "unknown IDs are rejected before anything is measured. Cannot be combined with "
                    "'algorithm'. The result reports the selection's 'runtime', its 'speedup' over "
                    "the un-patched project and an 'outcome': valid, invalid (the result failed "
                    "the validation), failed (build or execution failed) or not_applied (a patch "
                    "could not be applied)."
                ),
            },
            "apply": {
                "type": "boolean",
                "description": (
                    "Apply the selected combination to the source files once the search is "
                    "done, instead of only reporting it. Default: false. With suggestion_ids, the "
                    "given selection is applied whenever its outcome is 'valid', whether or not it is "
                    "faster; an invalid or failed one never is. With apply=true the "
                    "result carries 'applied' with the ids that reached the code; the "
                    "selection can be undone afterwards with "
                    "manage_patches(action='rollback', suggestion_ids=[...])."
                ),
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Maximum wall clock time for the whole search. Default: 3600. When it "
                    "expires the tuner is stopped and the best combination measured so far "
                    "is returned with status 'timeout'. With suggestion_ids, a timeout before "
                    "the selection was measured is an error."
                ),
            },
        },
        "required": ["project_path", "config_name"],
        "additionalProperties": False,
    },
    # Not read-only (it compiles and executes the project, and applies patches when asked)
    # but it destroys nothing: with apply=false the sources end up as they were, and an
    # applied selection is reversible with manage_patches. Not idempotent: a repeated
    # search re-measures, and runtime noise can make it select a different combination.
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)


def best_from_measurements(events: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], Optional[float]]:
    """The fastest usable measurement of a progress stream, plus the baseline runtime.

    Used when the tuner was stopped before it wrote its own ``result`` event. Only
    configurations that were actually executed and passed every check are eligible: an
    entry whose patches never reached the code (``application_failed``) carries no
    runtime at all, and an invalid or crashing run must never be reported as the best
    configuration no matter how fast it was.
    """
    baseline_runtime: Optional[float] = None
    best: Optional[dict[str, Any]] = None
    for event in events:
        if event.get("event") == "baseline":
            runtime = event.get("runtime")
            if isinstance(runtime, (int, float)) and runtime > 0:
                baseline_runtime = float(runtime)
            continue
        if event.get("event") != "measurement":
            continue
        if event.get("application_failed"):
            continue
        if event.get("return_code") != 0 or not event.get("valid") or not event.get("tsan"):
            continue
        runtime = event.get("runtime")
        if not isinstance(runtime, (int, float)) or runtime <= 0:
            continue
        if best is None or float(runtime) < float(best["runtime"]):
            best = event
    return best, baseline_runtime


def _validate_preconditions(project_path: str, config_name: str, dot_dp: str) -> Optional[str]:
    """Check every artefact the autotuner needs, reusing its own validation.

    ``AutotunerArguments.__post_init__`` runs the same check the CLI runs and raises
    ``FileNotFoundError`` for the first missing path. Constructing it here has no side
    effects — the tuner itself runs as a subprocess.
    """
    try:
        AutotunerArguments(
            log_level="WARNING",
            write_log=False,
            dot_dp_path=dot_dp,
            skip_cleanup=False,
            sanitize=False,
            configuration=config_name,
            suggestions=None,
            allow_plots=False,
            thread_count=1,
        )
    except FileNotFoundError as e:
        missing = str(e)
        if os.path.basename(missing) == config_name or f"configs/{config_name}" in missing:
            return (
                f"Configuration '{config_name}' is incomplete or does not exist (missing: {missing}). "
                "Use get_configurations to list the available configurations, or "
                "create_execution_configuration to create one."
            )
        return (
            f"The project is not ready for auto tuning (missing: {missing}). "
            "Run gather_data first so that the profiler results, detection results and "
            "patch files exist."
        )
    return None


def hotspot_loops_available(dot_dp: str) -> bool:
    """Whether the hotspot-guided search has anything to work with.

    ``execute_hotspot_guided_combination`` returns right after the baseline measurement
    when no hot loops are known, so a run without them would burn one compile-and-execute
    cycle and report that nothing could be improved.
    """
    if not os.path.exists(hotspots_json_path(dot_dp)):
        return False
    return any(region.node_type == HotspotNodeType.LOOP for region in load_detailed_hotspots(dot_dp))


def _hotspot_requirement_error(dot_dp: str) -> str:
    """Why hotspot_guided cannot run here, for a caller that asked for it explicitly."""
    remedy = (
        "Re-run gather_data with hotspot_config_names set (ideally two configurations with "
        "different input sizes), choose a different algorithm (greedy or coordinate_descent) which "
        "does not need hotspot information, or omit 'algorithm' to let the tool fall back automatically."
    )
    hotspots_file = hotspots_json_path(dot_dp)
    if not os.path.exists(hotspots_file):
        return (
            f"algorithm hotspot_guided requires hotspot detection results, but {hotspots_file} does not exist. "
            + remedy
        )
    return "algorithm hotspot_guided requires hot loops, but the hotspot detection results contain none. " + remedy


def _algorithm_name(requested: Any) -> Optional[str]:
    """The name of a requested algorithm, given by name or by its -A value; None if unknown."""
    if isinstance(requested, str) and requested in ALGORITHMS:
        return requested
    if isinstance(requested, int) and not isinstance(requested, bool):
        return next((name for name, number in ALGORITHMS.items() if number == requested), None)
    return None


def normalize_suggestion_ids(raw: Any) -> tuple[list[str], Optional[str]]:
    """The requested selection as the string ids used throughout this server, or an error.

    Integers are accepted as well, since a suggestion id is a number in every other
    respect; duplicates are dropped, keeping the order of their first occurrence.
    """
    if not isinstance(raw, list):
        return [], f"'suggestion_ids' must be a list of suggestion IDs, got {raw!r}."
    ids: list[str] = []
    invalid: list[str] = []
    for entry in raw:
        text = str(entry).strip() if isinstance(entry, (str, int)) and not isinstance(entry, bool) else ""
        if not text.isdigit():
            invalid.append(repr(entry))
            continue
        text = str(int(text))
        if text not in ids:
            ids.append(text)
    if invalid:
        return [], (
            "'suggestion_ids' must contain suggestion IDs as returned by get_parallelization_patches; "
            "not an ID: " + ", ".join(invalid) + "."
        )
    if not ids:
        return [], (
            "'suggestion_ids' is empty. Name at least one suggestion to measure, or omit "
            "'suggestion_ids' to run a search."
        )
    return ids, None


def unknown_suggestion_ids(dot_dp: str, suggestion_ids: list[str]) -> list[str]:
    """The requested ids that name no generated suggestion.

    Checked against the patch directories, the same source get_parallelization_patches
    lists its ids from, so an id that tool returned is never rejected here.
    """
    patch_generator = Path(dot_dp) / "patch_generator"
    try:
        known = {entry.name for entry in patch_generator.iterdir() if entry.is_dir() and entry.name.isdigit()}
    except OSError:
        known = set()
    return [suggestion_id for suggestion_id in suggestion_ids if suggestion_id not in known]


def _selection_outcome(measurement: dict[str, Any]) -> str:
    """How the measurement of a given selection ended, from the most to the least basic failure."""
    if measurement.get("application_failed"):
        return "not_applied"
    if measurement.get("return_code") != 0:
        return "failed"
    if not measurement.get("valid") or not measurement.get("tsan", True):
        return "invalid"
    return "valid"


def selection_result_from_events(events: list[dict[str, Any]], selection: list[str]) -> Optional[dict[str, Any]]:
    """The measurement of the given selection as the tool's result; None if it was not measured.

    The tuner's own ``result`` event is not used: it names the best *valid*
    configuration, which is the un-patched reference whenever the selection fails,
    and would then report a speedup of 1 for a selection that never ran correctly.
    """
    wanted = sorted(int(s) for s in selection)
    measurement = next(
        (
            event
            for event in events
            if event.get("event") == "measurement" and sorted(int(s) for s in event.get("suggestions", [])) == wanted
        ),
        None,
    )
    if measurement is None:
        return None
    baseline = next((e for e in events if e.get("event") == "baseline"), None)
    baseline_runtime = baseline.get("runtime") if baseline else None
    thread_count = baseline.get("thread_count") if baseline else None

    outcome = _selection_outcome(measurement)
    runtime = None if outcome == "not_applied" else measurement.get("runtime")
    speedup: Optional[float] = None
    # Only a valid run has a speedup: a crashing or wrong program is fast for the wrong reason.
    if outcome == "valid" and isinstance(runtime, (int, float)) and runtime > 0:
        measured_speedup = measurement.get("speedup")
        if isinstance(measured_speedup, (int, float)):
            speedup = float(measured_speedup)
        elif isinstance(baseline_runtime, (int, float)) and baseline_runtime > 0:
            speedup = round(float(baseline_runtime) / float(runtime), 4)

    result: dict[str, Any] = {
        "status": "success" if outcome == "valid" else "rejected",
        "mode": "selection",
        "suggestion_ids": list(selection),
        "outcome": outcome,
        # None where the output was never checked: nothing ran, or the run itself failed
        "result_valid": outcome == "valid" if outcome in ("valid", "invalid") else None,
        "return_code": measurement.get("return_code"),
        "runtime": runtime,
        "baseline_runtime": baseline_runtime,
        "speedup": speedup,
        "thread_count": thread_count,
    }
    if speedup is not None and isinstance(thread_count, int) and thread_count > 0:
        result["efficiency"] = round(speedup / thread_count, 4)
    failed = [str(s) for s in measurement.get("failed_suggestions", [])]
    if failed:
        result["not_applied"] = failed

    if outcome == "valid":
        result["message"] = (
            f"The selection built, ran and produced a valid result in {runtime}s, against "
            f"{baseline_runtime}s for the un-patched project (speedup {speedup})."
        )
        if speedup is not None and speedup <= 1:
            result["message"] += (
                " It is not faster than the un-patched project; run_auto_tuning without "
                "suggestion_ids searches for a combination that is."
            )
    elif outcome == "invalid":
        result["message"] = (
            "The selection built and ran, but its result failed the validation: the program "
            "does not compute the same result with these suggestions applied. Do not apply it."
        )
    elif outcome == "failed":
        result["message"] = (
            f"The selection failed to build or to execute (return code {measurement.get('return_code')}). "
            "An execution that takes longer than twice the un-patched project's is stopped and "
            "counts as failed as well."
        )
    else:
        result["message"] = (
            "The patches of the suggestions "
            + ", ".join(failed or selection)
            + " could not be applied, so the selection was not measured."
        )
    return result


def _pump_output(stream: Any, tail: Deque[str], project_path: str, ctx: ToolContext) -> None:
    """Forward the tuner's output to the server log, keeping only a bounded tail."""
    try:
        for raw_line in stream:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            tail.append(line)
            ctx.log_action(project_path, "run_auto_tuning", f"[autotuner] {line}")
    except Exception:  # the stream is closed when the process is killed
        pass


def _terminate(proc: "subprocess.Popen[str]") -> None:
    """Stop the tuner and every compile/execute child it started.

    The tuner is launched in its own session, so signalling the process group reaches
    the compile and execute scripts as well; killing only the tuner would leave a
    long-running benchmark behind.
    """
    terminate_process_tree(proc, _KILL_GRACE_SECONDS)


def _cleanup_project_copies(project_path: str, config_name: str, ctx: ToolContext) -> list[str]:
    """Remove the candidate project copies a killed tuner left behind.

    ``copy_configuration`` places every candidate next to the project root, named
    ``<config>_<settings>_<project>_<id>``: par_settings.json for the measured candidates,
    hd_settings.json for the hotspot-instrumented ones the refinement of a -s selection builds. A completed run
    deletes them itself; an interrupted one cannot, and they are full copies of the project.
    """
    project_dir = Path(project_path).resolve()
    prefixes = tuple(
        f"{config_name}_{settings}_{project_dir.name}_" for settings in ("par_settings.json", "hd_settings.json")
    )
    removed: list[str] = []
    try:
        candidates = sorted(project_dir.parent.iterdir())
    except OSError:
        return removed
    for entry in candidates:
        # the id after the prefix keeps a sibling project named "<project>_..." out of it
        prefix = next((p for p in prefixes if entry.name.startswith(p)), None)
        if prefix is None or not entry.name[len(prefix) :].isdigit() or not entry.is_dir():
            continue
        try:
            shutil.rmtree(str(entry))
            removed.append(entry.name)
            ctx.log_action(project_path, "run_auto_tuning", f"Removed leftover project copy {entry}")
        except OSError as e:
            ctx.log_action(project_path, "run_auto_tuning", f"Could not remove leftover project copy {entry}: {e}")
    return removed


def _validation_notes(dot_dp: str, config_name: str, result: dict[str, Any]) -> list[str]:
    """Say how far the tuner's "the result stays valid" claim actually reaches.

    Without a ``validate.sh`` a candidate counts as valid as soon as it exits with code
    0, so a parallelization that silently corrupts the output is indistinguishable from
    a correct one — and it is usually also the fastest candidate. A speedup above the
    thread count is the symptom that shows up first, since no correct parallelization
    can exceed it.
    """
    notes: list[str] = []
    validate_script = Path(dot_dp) / "project" / "configs" / config_name / VALIDATE_SCRIPT_NAME
    if not validate_script.exists():
        notes.append(
            f"Configuration '{config_name}' has no {VALIDATE_SCRIPT_NAME}, so a candidate counted as "
            "valid merely exited with code 0 — its output was never checked. Add one via "
            "create_execution_configuration(validate_script_body=...) to let the tuner verify "
            "correctness, and review the selected patches before trusting them."
        )
    speedup = result.get("speedup")
    threads = result.get("thread_count")
    if isinstance(speedup, (int, float)) and isinstance(threads, (int, float)) and threads > 0:
        if speedup > threads:
            notes.append(
                f"The measured speedup ({speedup}) exceeds the thread count ({int(threads)}), which no "
                "correct parallelization can do. The selected combination most likely skips work "
                "rather than distributing it — verify the program's output before applying it."
            )
    return notes


def _clear_before_measuring(project_path: str, applied: list[str], ctx: ToolContext) -> Optional[str]:
    """Take the applied patches out of the sources, or say why that failed.

    The tuner measures the project as it stands and applies each candidate on top of a
    copy of it, so patches already in the code would be counted into the baseline and
    stacked under every candidate. Clearing them here rather than refusing keeps the
    caller out of a dead end whose only exit was another tool call, and the applicator
    saves the cleared selection so it can be put back afterwards.
    """
    proc, run_error = run_patch_applicator(project_path, ["--clear"])
    if proc is None:
        return run_error
    if proc.returncode not in APPLICATOR_OK_RETURNCODES:
        output, cause = applicator_failure_details(proc)
        message = (
            "The suggestions " + ", ".join(applied) + " are applied to the sources and could not be "
            f"removed for the measurement (discopop_patch_applicator --clear failed with rc={proc.returncode}). "
            "Auto tuning needs an un-patched project, because every candidate is measured on top of "
            "the current state."
        )
        if cause is not None:
            message += " " + cause
        if output:
            message += "\nApplicator output:\n" + output
        return message
    ctx.log_action(project_path, "run_auto_tuning", f"Cleared applied suggestions before measuring: {applied}")
    return None


def _restore_cleared(project_path: str, cleared: list[str], ctx: ToolContext) -> Optional[str]:
    """Put back the selection that was cleared for the measurement.

    Used whenever the caller did not ask for the tuner's own selection to be applied:
    the project then ends the call in the state it started in, which is what makes a
    measurement safe to ask for.
    """
    proc, run_error = run_patch_applicator(project_path, ["--load"])
    if proc is None:
        return run_error
    if proc.returncode not in APPLICATOR_OK_RETURNCODES:
        output, cause = applicator_failure_details(proc)
        message = (
            "The suggestions " + ", ".join(cleared) + " were removed from the sources for the "
            f"measurement and could not be put back (rc={proc.returncode}). The sources are currently "
            "un-patched; re-apply them with manage_patches(action='apply', suggestion_ids=[...])."
        )
        if cause is not None:
            message += " " + cause
        if output:
            message += "\nApplicator output:\n" + output
        return message
    ctx.log_action(project_path, "run_auto_tuning", f"Restored the previously applied suggestions: {cleared}")
    return None


def _apply_selection(project_path: str, suggestion_ids: list[str], ctx: ToolContext) -> dict[str, Any]:
    """Apply the tuner's selection, reporting exactly what reached the code.

    Returns the fields to merge into the result: ``applied`` and, when something did not
    make it, ``not_applied`` plus a warning. A failure here does not invalidate the
    search -- the selection was still measured -- so it is reported rather than raised.
    """
    proc, run_error = run_patch_applicator(project_path, ["--apply"] + suggestion_ids)
    if proc is None:
        return {"applied": [], "apply_error": run_error}
    if proc.returncode not in APPLICATOR_OK_RETURNCODES:
        output, cause = applicator_failure_details(proc)
        message = f"The selection could not be applied (rc={proc.returncode})."
        if cause is not None:
            message += " " + cause
        if output:
            message += "\nApplicator output:\n" + output
        return {"applied": [], "apply_error": message}

    application = read_application_result(project_path)
    if application is None:
        # The applicator reported success but wrote no breakdown; the requested ids are
        # then the best account of what was applied.
        ctx.log_action(project_path, "run_auto_tuning", f"Applied the selection: {suggestion_ids}")
        return {"applied": list(suggestion_ids)}

    applied = [str(entry) for entry in application.get("applied", [])]
    fields: dict[str, Any] = {"applied": applied}
    not_applied = [str(entry) for entry in list(application.get("failed", [])) + list(application.get("unknown", []))]
    if not_applied:
        fields["not_applied"] = not_applied
        fields["apply_error"] = (
            "The following selected suggestions were NOT applied: "
            + ", ".join(not_applied)
            + ". The affected files are unchanged, so the code is not parallelized as measured."
        )
    ctx.log_action(project_path, "run_auto_tuning", f"Applied the selection: {applied}")
    return fields


def _progress_file(dot_dp: str) -> Path:
    return Path(dot_dp) / "auto_tuner" / "progress.jsonl"


def progress_mtime(dot_dp: str) -> Optional[float]:
    """The progress file's mtime, or None when it does not exist.

    Sampled before and after the run so a progress file left over from an earlier
    invocation is never mistaken for this run's output.
    """
    try:
        return _progress_file(dot_dp).stat().st_mtime
    except OSError:
        return None


def read_progress_events(dot_dp: str) -> list[dict[str, Any]]:
    progress_file = _progress_file(dot_dp)
    if not progress_file.exists():
        return []
    try:
        return parse_progress_jsonl(progress_file.read_text())
    except OSError:
        return []


def _tuning_progress(
    dot_dp: str, progress_mtime_before: Optional[float], started: float
) -> tuple[float, Optional[float], str]:
    """How far a running search is, read from the progress file it writes.

    The number of candidates a search evaluates is not known up front, so there is no
    total; the count of measured candidates is what increases.
    """
    elapsed = f"{time.monotonic() - started:.0f}s elapsed"
    if progress_mtime(dot_dp) == progress_mtime_before:
        return 0, None, f"Measuring the baseline ({elapsed})"
    measured = sum(1 for event in read_progress_events(dot_dp) if event.get("event") == "measurement")
    return measured, None, f"{measured} candidate configuration(s) measured ({elapsed})"


def result_from_events(events: list[dict[str, Any]], timed_out: bool) -> dict[str, Any]:
    """Turn the tuner's progress stream into the tool's result payload."""
    baseline = next((e for e in events if e.get("event") == "baseline"), None)
    baseline_runtime = baseline.get("runtime") if baseline else None
    thread_count = baseline.get("thread_count") if baseline else None
    final = next((e for e in reversed(events) if e.get("event") == "result"), None)

    if final is not None and not timed_out:
        return {
            "status": "success",
            "thread_count": thread_count,
            "suggestion_ids": [str(s) for s in final.get("suggestions", [])],
            "speedup": final.get("speedup"),
            "efficiency": final.get("efficiency"),
            "runtime": final.get("runtime"),
            "baseline_runtime": baseline_runtime,
            "evaluated_configurations": final.get("evaluated"),
            "valid_count": final.get("valid_count"),
            "invalid_count": final.get("invalid_count"),
            "failed_count": final.get("failed_count"),
            "not_applied_count": final.get("not_applied_count"),
            "optimization_time_s": final.get("optimization_time_s"),
        }

    best, measured_baseline = best_from_measurements(events)
    reference = baseline_runtime if isinstance(baseline_runtime, (int, float)) else measured_baseline
    speedup = best.get("speedup") if best else None
    if speedup is None and best and reference:
        runtime = best.get("runtime")
        if isinstance(runtime, (int, float)) and runtime > 0:
            speedup = round(float(reference) / float(runtime), 4)
    return {
        "status": "timeout" if timed_out else "success",
        "partial": True,
        "thread_count": thread_count,
        "suggestion_ids": [str(s) for s in best.get("suggestions", [])] if best else [],
        "speedup": speedup,
        "runtime": best.get("runtime") if best else None,
        "baseline_runtime": reference,
        "evaluated_configurations": len([e for e in events if e.get("event") == "measurement"]),
    }


# What the tuner writes to .discopop/ as the result of its run. auto_tuner/results.json is
# what the GUI and `discopop_project_manager --apply-suggestions auto` apply, and the
# others describe the last search to get_project_status, the GUI and the user.
_TUNER_RESULT_FILES = (
    "auto_tuner/results.json",
    "auto_tuner/progress.jsonl",
    "auto_tuner/measurements.json",
    "auto_tuner/compile_results.json",
    "dp_autotuner_statistics.dot",
    "dp_autotuner_statistics.svg",
)
_TunerResults = dict[Path, Optional[tuple[bytes, float]]]


def _snapshot_tuner_results(dot_dp: str) -> _TunerResults:
    """The tuner's result files as they are, with their mtimes; None for a missing one."""
    snapshot: _TunerResults = {}
    for name in _TUNER_RESULT_FILES:
        path = Path(dot_dp) / name
        try:
            snapshot[path] = (path.read_bytes(), path.stat().st_mtime)
        except OSError:
            snapshot[path] = None
    return snapshot


def _restore_tuner_results(snapshot: _TunerResults) -> None:
    """Put the result files back, so that measuring a selection does not replace the last search."""
    for path, saved in snapshot.items():
        try:
            if saved is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(saved[0])
                os.utime(path, (saved[1], saved[1]))
        except OSError as e:
            logger.warning(f"Could not restore {path}: {e}")


def _run_tuner(
    cmd: list[str],
    dot_dp: str,
    project_path: str,
    timeout_seconds: int,
    run_description: str,
    progress_mtime_before: Optional[float],
    ctx: ToolContext,
) -> tuple[list[dict[str, Any]], int, bool, Deque[str]]:
    """Run the tuner until it ends, times out or is cancelled; its events, exit code and output tail."""
    tail: Deque[str] = deque(maxlen=_OUTPUT_TAIL_LINES)
    started = time.monotonic()
    # start_new_session puts the tuner into its own process group so a timeout can
    # take down the compile and execute scripts it spawned along with it.
    proc = subprocess.Popen(
        cmd,
        cwd=dot_dp,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    # stops the tuner right away if the cancel came after the caller's last look at it
    ctx.track_process(proc)
    pump = threading.Thread(target=_pump_output, args=(proc.stdout, tail, project_path, ctx), daemon=True)
    pump.start()

    timed_out = False
    try:
        ctx.report_progress(0, None, f"Auto-tuning started ({run_description}), measuring the baseline")
        with ctx.heartbeat(lambda: _tuning_progress(dot_dp, progress_mtime_before, started)):
            returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        ctx.log_action(
            project_path,
            "run_auto_tuning",
            f"Timeout after {timeout_seconds}s — stopping the autotuner",
        )
        _terminate(proc)
        returncode = proc.returncode if proc.returncode is not None else -1
    except BaseException:
        # a tuner left running would keep writing the files the caller is about to restore
        _terminate(proc)
        raise
    pump.join(timeout=5.0)

    # A progress file that this run did not write belongs to an earlier one. Reporting
    # it would present an old run's selection as the result of this one.
    events = read_progress_events(dot_dp) if progress_mtime(dot_dp) != progress_mtime_before else []
    return events, returncode, timed_out, tail


def _cancelled(project_path: str, cleared: list[str], ctx: ToolContext) -> list[TextContent]:
    """The answer to a cancelled call, once the suggestions cleared for it are restored."""
    message = "Cancelled by the client."
    if cleared:
        restore_error = _restore_cleared(project_path, cleared, ctx)
        message += f" {restore_error}" if restore_error is not None else " The applied suggestions were restored."
    return ctx.error(message, project_path, "run_auto_tuning")


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        config_name: str = arguments.get("config_name", "")
        requested_algorithm: Any = arguments.get("algorithm")
        apply_selection: bool = bool(arguments.get("apply", False))
        timeout_seconds: int = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

        name_error = invalid_configuration_name(config_name)
        if name_error is not None:
            return ctx.error(name_error, project_path, "run_auto_tuning")
        dot_dp = str(Path(project_path) / ".discopop")
        if not os.path.exists(dot_dp):
            return ctx.error(
                "DiscoPoP directory not found. Run initialize_discopop_directory and gather_data first.",
                project_path,
                "run_auto_tuning",
            )

        precondition_error = _validate_preconditions(project_path, config_name, dot_dp)
        if precondition_error is not None:
            return ctx.error(precondition_error, project_path, "run_auto_tuning")

        # A given selection replaces the search, so it is checked completely before
        # anything is cleared, compiled or run.
        selection: Optional[list[str]] = None
        if arguments.get("suggestion_ids") is not None:
            if requested_algorithm is not None:
                return ctx.error(
                    "'suggestion_ids' and 'algorithm' cannot be combined: with suggestion_ids the given "
                    "selection is measured and no search runs. Pass only one of them.",
                    project_path,
                    "run_auto_tuning",
                )
            selection, selection_error = normalize_suggestion_ids(arguments["suggestion_ids"])
            if selection_error is not None:
                return ctx.error(selection_error, project_path, "run_auto_tuning")
            unknown = unknown_suggestion_ids(dot_dp, selection)
            if unknown:
                return ctx.error(
                    "Unknown suggestion IDs: "
                    + ", ".join(unknown)
                    + ". get_parallelization_patches lists the IDs of the current suggestions; IDs "
                    "from an earlier analysis are no longer valid after gather_data ran again.",
                    project_path,
                    "run_auto_tuning",
                )

        # Hotspot-guided descent unless there is nothing for it to be guided by. An
        # explicitly requested algorithm is never silently replaced: the caller asked for
        # a specific search, so a missing prerequisite is reported instead. A given
        # selection runs no search, so it needs no algorithm.
        algorithm_selection: Optional[str] = None
        algorithm: Optional[str] = None
        if selection is None and requested_algorithm is None:
            if hotspot_loops_available(dot_dp):
                algorithm = HOTSPOT_GUIDED_ALGORITHM
                algorithm_selection = "hotspot-guided region descent, chosen because hotspot results are available"
            else:
                algorithm = FALLBACK_ALGORITHM
                algorithm_selection = (
                    "greedy forward search, chosen because no hotspot detection results are available. "
                    "Re-run gather_data with hotspot_config_names set to enable the hotspot-guided search, "
                    "which usually needs fewer measurements."
                )
            ctx.log_action(project_path, "run_auto_tuning", f"Selected algorithm {algorithm}: {algorithm_selection}")
        elif selection is None:
            requested_name = _algorithm_name(requested_algorithm)
            if requested_name is None:
                return ctx.error(
                    f"Unknown algorithm {requested_algorithm!r}. Choose one of: {', '.join(ALGORITHMS)}.",
                    project_path,
                    "run_auto_tuning",
                )
            algorithm = requested_name
            if algorithm == HOTSPOT_GUIDED_ALGORITHM and not hotspot_loops_available(dot_dp):
                return ctx.error(_hotspot_requirement_error(dot_dp), project_path, "run_auto_tuning")

        # An un-patched project is what the search has to measure against, so anything
        # applied is cleared here and -- unless the caller wants the tuner's own selection
        # applied instead -- put back once the search is over.
        applied, applied_error = read_applied_suggestions(project_path)
        if applied_error is not None:
            return ctx.error(applied_error, project_path, "run_auto_tuning")
        cleared: list[str] = []
        if applied:
            clear_error = _clear_before_measuring(project_path, applied, ctx)
            if clear_error is not None:
                return ctx.error(clear_error, project_path, "run_auto_tuning")
            cleared = list(applied)

        cmd = [
            sys.executable,
            "-m",
            "discopop_library.EmpiricalAutotuning",
            "--dot-dp-path",
            dot_dp,
            "-c",
            config_name,
            "--log",
            "WARNING",
        ]
        if selection is not None:
            # --skip-removal-pass keeps the tuner from refining the selection afterwards,
            # which would profile it and measure a reduced selection the caller never named.
            cmd += ["-s", ",".join(selection), "--skip-removal-pass"]
            run_description = "measuring the selection " + ", ".join(selection)
        else:
            assert algorithm is not None
            cmd += ["-A", str(ALGORITHMS[algorithm])]
            run_description = f"algorithm {algorithm}"
        ctx.log_action(
            project_path,
            "run_auto_tuning",
            f"config={config_name}, {run_description}, timeout={timeout_seconds}s, cmd={cmd}",
        )

        # A cancel during the clearing above would not stop a tuner started after it.
        if ctx.cancelled:
            return _cancelled(project_path, cleared, ctx)

        progress_mtime_before = progress_mtime(dot_dp)
        saved_results = _snapshot_tuner_results(dot_dp) if selection is not None else None
        try:
            events, returncode, timed_out, tail = _run_tuner(
                cmd, dot_dp, project_path, timeout_seconds, run_description, progress_mtime_before, ctx
            )
        finally:
            # also when running the tuner raised: the files are back whatever happened
            if saved_results is not None:
                _restore_tuner_results(saved_results)

        if ctx.cancelled:
            # ctx.cancel stopped the tuner; what it leaves behind is cleaned up as after a timeout
            _cleanup_project_copies(project_path, config_name, ctx)
            return _cancelled(project_path, cleared, ctx)

        removed_copies = _cleanup_project_copies(project_path, config_name, ctx) if timed_out else []

        selection_result = selection_result_from_events(events, selection) if selection is not None else None
        if not events or (selection is not None and selection_result is None):
            if selection is not None:
                # The baseline alone answers nothing about the selection.
                stopped = (
                    f"the timeout of {timeout_seconds}s expired"
                    if timed_out
                    else f"the autotuner exited (rc={returncode})"
                )
                message = (
                    f"The selection was not measured: {stopped} before its measurement was complete. "
                    "A measurement covers one compilation plus one execution of the un-patched project "
                    "and of the selection" + (" — re-run with a larger timeout_seconds." if timed_out else ".")
                )
            elif timed_out:
                message = (
                    f"The timeout of {timeout_seconds}s expired before the autotuner completed its "
                    "first measurement, so no configuration could be evaluated. A single measurement "
                    "covers one compilation plus one execution of the project — re-run with a "
                    "timeout_seconds large enough for several of those."
                )
            else:
                message = f"The autotuner produced no measurements (rc={returncode})."
            if tail:
                message += " Last output:\n" + "\n".join(tail)
            # A search that produced nothing must not also cost the caller the selection
            # that was in the code when the call started.
            if cleared:
                restore_error = _restore_cleared(project_path, cleared, ctx)
                message += (
                    f"\n{restore_error}"
                    if restore_error is not None
                    else "\nThe suggestions applied before the call (" + ", ".join(cleared) + ") were restored."
                )
            return ctx.error(message, project_path, "run_auto_tuning")

        if selection_result is not None:
            result = selection_result
            result["project_path"] = project_path
            result["config_name"] = config_name
            # The selection's measurement is complete; what the tuner did after it (re-running
            # its best configuration) is not part of the answer, so being stopped there is
            # only mentioned.
            if timed_out or returncode != 0:
                stopped = f"timeout of {timeout_seconds}s" if timed_out else f"exit code {returncode}"
                result["message"] += (
                    f" The autotuner ended with a {stopped} after the selection had been measured; "
                    "the measurement above is complete."
                )
            if removed_copies:
                result["removed_project_copies"] = removed_copies
            # Only a selection that ran correctly may reach the sources.
            to_apply: list[str] = list(result["suggestion_ids"]) if result["outcome"] == "valid" else []
        else:
            result = result_from_events(events, timed_out)
            result["project_path"] = project_path
            result["config_name"] = config_name
            result["algorithm"] = algorithm
            if algorithm_selection is not None:
                result["algorithm_selection"] = algorithm_selection
            to_apply = result["suggestion_ids"]
            if timed_out:
                result["message"] = (
                    f"The search was stopped after {timeout_seconds}s. The reported combination is the "
                    "best one measured so far; the search was not completed and the final pass that "
                    "checks whether an accepted suggestion can be removed again did not run. "
                    "Re-run with a larger timeout_seconds for a complete search."
                )
                if removed_copies:
                    result["removed_project_copies"] = removed_copies
            elif returncode != 0:
                # measurements exist, so the outcome is still usable — but say what happened
                result["status"] = "partial"
                result["returncode"] = returncode
                result["message"] = (
                    f"The autotuner exited with code {returncode}. The reported combination is derived "
                    "from the measurements it had written. Last output:\n" + "\n".join(tail)
                )
            elif not result["suggestion_ids"]:
                result["message"] = (
                    "No combination of suggestions was faster than the unmodified project, so no "
                    "suggestion is recommended for application."
                )

        warnings: list[str] = []
        if cleared:
            result["cleared_before_tuning"] = cleared
        if apply_selection and selection_result is not None and not to_apply:
            warnings.append(
                f"The selection was not applied, because its outcome is '{result['outcome']}' rather than 'valid'."
            )

        # Either the selection replaces what was in the code, or the code goes back to the
        # state the call found it in. Both are stated in the result: which one happened
        # decides what the caller has to do next.
        if apply_selection and to_apply:
            result.update(_apply_selection(project_path, to_apply, ctx))
            apply_error = result.pop("apply_error", None)
            if apply_error is not None:
                warnings.append(apply_error)
                if not result.get("applied"):
                    result["status"] = "partial" if result["status"] == "success" else result["status"]
            if result.get("applied"):
                result["message"] = (result.get("message", "") + " " if result.get("message") else "") + (
                    "The selected suggestions were applied to the source files. Undo them with "
                    "manage_patches(action='rollback', suggestion_ids=[...]) if needed."
                )
        else:
            restored = True
            if cleared:
                restore_error = _restore_cleared(project_path, cleared, ctx)
                if restore_error is not None:
                    warnings.append(restore_error)
                    restored = False
            if to_apply:
                result["message"] = (
                    (result.get("message", "") + " " if result.get("message") else "")
                    + "Pass suggestion_ids to manage_patches(action='apply', suggestion_ids=[...]) to "
                    "persist this selection, or call run_auto_tuning again with apply=true."
                    # Only claimed when it is true: a failed restore left the sources
                    # un-patched, and the warning saying so must not be contradicted here.
                    + (" The sources are as they were before this call." if restored else "")
                )
            result["applied"] = False

        # How much the "the result stays valid" claim is worth depends on the configuration,
        # so the caller is told rather than left to assume the strongest reading.
        if to_apply:
            warnings += _validation_notes(dot_dp, config_name, result)
        if warnings:
            result["warnings"] = warnings

        # The counts say that candidates were rejected, not why; the reason is in the
        # recorded runs, and a caller that wonders whether a rejected suggestion was
        # broken or only slow has to be told where it is.
        rejected = {
            key: result.get(key)
            for key in ("invalid_count", "failed_count", "not_applied_count")
            if isinstance(result.get(key), int) and result[key] > 0
        }
        if rejected:
            result["diagnosis_hint"] = (
                "Some candidates were rejected ("
                + ", ".join(f"{key}={value}" for key, value in rejected.items())
                + "). get_execution_results(config_name=..., failed_only=true, include_output=true) "
                "shows those runs with their applied_suggestions, return code and output, which tells "
                "a broken build or a failed validation apart from a slow run."
            )
        elif selection_result is not None and result["outcome"] in ("invalid", "failed"):
            result["diagnosis_hint"] = (
                "get_execution_results(config_name=..., failed_only=true, include_output=true) shows "
                "the selection's run with its return code and output, which tells why it was rejected."
            )

        ctx.log_response("run_auto_tuning", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error in run_auto_tuning: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]
