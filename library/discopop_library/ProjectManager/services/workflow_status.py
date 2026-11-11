# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The state of each stage of the workflow (configure, profile, ...), for the sidebar of the main window.

Everything here is a stat call or the read of a small file: the statuses are recomputed after every project state
event on the GUI thread, so no profiler output is parsed and nothing is run.
"""

import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.services.autotuner_results import autotuner_results_exist
from discopop_library.ProjectManager.services.explorer_state import (
    explorer_prerequisites_met,
    pattern_detection_executed,
    required_explorer_files,
)
from discopop_library.ProjectManager.services.hotspot_build import BUILD_MISMATCH
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession
from discopop_library.ProjectManager.services.patch_repair_view import load_results as load_patch_repair_results
from discopop_library.ProjectManager.services.patches import count_patches, has_patches

# The keys of the stages; they equal the names of the tabs of the main window (qt_gui/tabs.py re-exports them).
STAGE_SETUP = "Setup"
STAGE_EDITOR = "Editor"
STAGE_PROFILING = "Profiling"
STAGE_EXECUTE = "Execute"
STAGE_REPORT = "Report"
STAGE_HOTSPOT = "Hotspot Detection"
STAGE_PATTERN_DETECTION = "Pattern Detection"
STAGE_PATCH_REPAIR = "Patch Repair"
STAGE_AUTOTUNING = "Autotuning"


class StageState(Enum):
    DONE = "done"
    STALE = "stale"
    NOT_RUN = "not run"
    LOCKED = "locked"


@dataclass(frozen=True)
class StageStatus:
    state: StageState
    detail: str  # one short line, e.g. "2 suggestions", "sources changed", "needs profiling data"


# what the autotuner is missing (autotuning_missing)
MISSING_PROFILING_DATA = "profiling data"
MISSING_SUGGESTIONS = "suggestions"


def autotuning_missing(dot_dp: str) -> Optional[str]:
    """The first prerequisite of the autotuner that is missing (``MISSING_*``), or None if it can start."""
    if not explorer_prerequisites_met(dot_dp):
        return MISSING_PROFILING_DATA
    if not has_patches(dot_dp):
        return MISSING_SUGGESTIONS
    return None


def autotuning_ready(dot_dp: str) -> bool:
    """Whether the autotuner can start: profiling data and parallelization suggestions exist."""
    return autotuning_missing(dot_dp) is None


def count_execution_results(project_dir: str) -> int:
    """The number of recorded runs in ``execution_results.json`` (configuration -> script -> settings -> runs)."""
    try:
        with open(os.path.join(project_dir, "execution_results.json"), "r") as f:
            results: Any = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(results, dict):
        return 0
    return sum(
        len(runs)
        for scripts in results.values()
        if isinstance(scripts, dict)
        for settings in scripts.values()
        if isinstance(settings, dict)
        for runs in settings.values()
        if isinstance(runs, list)
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def detection_is_stale(dot_dp: str) -> bool:
    """Whether a profiling file is newer than the last detection result (``explorer/patterns.json``)."""
    detected = _mtime(os.path.join(dot_dp, "explorer", "patterns.json"))
    if detected is None:
        return False
    # FileMapping.txt is left out: every instrumented build rewrites it (the hotspot build too), without changing
    # the profiling data the detection used
    profiling_files = [path for path in required_explorer_files(dot_dp) if os.path.basename(path) != "FileMapping.txt"]
    return any(profiled is not None and profiled > detected for profiled in map(_mtime, profiling_files))


def _setup_status(arguments: ProjectManagerArguments) -> StageStatus:
    """The shared build: compile.sh, the settings of the sequential build and the ones derived from them."""
    for name in ("compile.sh", "seq_settings.json"):
        if not os.path.isfile(os.path.join(arguments.project_config_dir, name)):
            return StageStatus(StageState.NOT_RUN, f"no {name}")
    if not os.path.isfile(os.path.join(arguments.project_config_dir, "dp_settings.json")):
        return StageStatus(StageState.NOT_RUN, "settings not derived")
    return StageStatus(StageState.DONE, "compile.sh, settings")


def _editor_status(arguments: ProjectManagerArguments, config: Optional[str]) -> StageStatus:
    if not config:
        return StageStatus(StageState.NOT_RUN, "no configuration selected")
    if os.path.isfile(os.path.join(arguments.project_config_dir, config, "execute.sh")):
        return StageStatus(StageState.DONE, config)
    return StageStatus(StageState.NOT_RUN, "no execute.sh")


def _profiling_status(arguments: ProjectManagerArguments) -> StageStatus:
    if not explorer_prerequisites_met(arguments.dot_dp):
        return StageStatus(StageState.NOT_RUN, "no profiling data")
    return StageStatus(StageState.DONE, "profiled")


def _execute_status(runs: int) -> StageStatus:
    if not runs:
        return StageStatus(StageState.NOT_RUN, "no measured runs")
    return StageStatus(StageState.DONE, _plural(runs, "measured run"))


# The build state walks the source tree for the newest modification time, the only part of stage_statuses that is
# not a few stat calls. The GUI asks after every burst of events; within this many seconds the last answer is reused
# (forget_build_states() drops it when the GUI knows the build changed).
BUILD_STATE_MAX_AGE_S = 5.0
_build_states: Dict[Tuple[str, Optional[str]], Tuple[float, str]] = {}


def forget_build_states() -> None:
    """Drop the cached build states (call after a hotspot build or measurement)."""
    _build_states.clear()


def _build_state(arguments: ProjectManagerArguments, config: Optional[str]) -> str:
    key = (arguments.dot_dp, config)
    now = time.monotonic()
    cached = _build_states.get(key)
    if cached is not None and now - cached[0] < BUILD_STATE_MAX_AGE_S:
        return cached[1]
    state, _detail = HotspotSession(arguments).build_state(config)
    _build_states[key] = (now, state)
    return state


def _hotspot_status(arguments: ProjectManagerArguments, config: Optional[str]) -> StageStatus:
    if not os.path.exists(hotspot_data.hotspots_json_path(arguments.dot_dp)):
        return StageStatus(StageState.NOT_RUN, "no hotspot results")
    # the same rule as the "Instrumented build" line of the Hotspot panel
    state = _build_state(arguments, config)
    if state == BUILD_MISMATCH:
        return StageStatus(StageState.STALE, "sources changed")
    return StageStatus(StageState.DONE, "")


def _pattern_detection_status(arguments: ProjectManagerArguments) -> StageStatus:
    dot_dp = arguments.dot_dp
    if not explorer_prerequisites_met(dot_dp):
        return StageStatus(StageState.LOCKED, "needs profiling data")
    if not pattern_detection_executed(dot_dp):
        return StageStatus(StageState.NOT_RUN, "")
    suggestions = _plural(count_patches(dot_dp), "suggestion")
    if detection_is_stale(dot_dp):
        return StageStatus(StageState.STALE, "profiling data newer than the results")
    return StageStatus(StageState.DONE, suggestions)


def _patch_repair_status(arguments: ProjectManagerArguments) -> StageStatus:
    dot_dp = arguments.dot_dp
    if not has_patches(dot_dp):
        return StageStatus(StageState.LOCKED, "needs suggestions")
    records = load_patch_repair_results(dot_dp)
    if records is None:
        return StageStatus(StageState.NOT_RUN, "optional")
    return StageStatus(StageState.DONE, _plural(len(records), "result"))


def _autotuning_status(arguments: ProjectManagerArguments) -> StageStatus:
    dot_dp = arguments.dot_dp
    if not explorer_prerequisites_met(dot_dp):
        return StageStatus(StageState.LOCKED, "needs profiling data")
    if not has_patches(dot_dp):
        return StageStatus(StageState.LOCKED, "needs suggestions")
    if autotuner_results_exist(dot_dp):
        return StageStatus(StageState.DONE, "")
    return StageStatus(StageState.NOT_RUN, "")


def stage_statuses(arguments: ProjectManagerArguments, config: Optional[str]) -> Dict[str, StageStatus]:
    """The status of every stage of the workflow, by stage key; cheap enough to call after every project event."""
    runs = count_execution_results(arguments.project_dir)
    return {
        STAGE_SETUP: _setup_status(arguments),
        STAGE_EDITOR: _editor_status(arguments, config),
        STAGE_PROFILING: _profiling_status(arguments),
        STAGE_EXECUTE: _execute_status(runs),
        STAGE_HOTSPOT: _hotspot_status(arguments, config),
        STAGE_PATTERN_DETECTION: _pattern_detection_status(arguments),
        STAGE_PATCH_REPAIR: _patch_repair_status(arguments),
        STAGE_AUTOTUNING: _autotuning_status(arguments),
        STAGE_REPORT: StageStatus(StageState.DONE if runs else StageState.NOT_RUN, _plural(runs, "execution result")),
    }
