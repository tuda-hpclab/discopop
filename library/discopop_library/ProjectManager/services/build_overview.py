# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the GUI and the command line show about the builds and runs of a project, without a toolkit."""

import json
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import (
    BuildKey,
    BuildRecord,
    BuildState,
    build_status,
    delete_builds,
    list_builds,
)
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.runs import (
    ActivationError,
    RunRecord,
    activate_run,
    delete_runs,
    disk_usage,
    list_all_runs,
)
from discopop_library.ProjectManager.services.modes import settings_path as mode_settings_path


def format_size(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (size, unit)
        size /= 1024
    return "%.1f TiB" % size


def format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def build_state_of(arguments: ProjectManagerArguments, record: BuildRecord) -> str:
    """``current``, ``stale (<why>)`` or ``missing (<why>)`` for the build of ``record``. Reads the whole project."""
    settings = mode_settings_path(arguments.project_config_dir, record.mode)
    config_dir = os.path.join(arguments.project_config_dir, record.configuration)
    if settings is None or not os.path.isdir(config_dir):
        return "stale (the configuration or its settings do not exist any more)"
    key = BuildKey(record.configuration, record.mode, tuple(record.suggestions))
    status = build_status(
        arguments, key, resolve_compile_script_path(arguments.project_config_dir, record.configuration), settings
    )
    if status.state == BuildState.CURRENT:
        return "current"
    if status.state == BuildState.NONE:
        return "missing (" + status.reason + ")"
    return "stale (" + status.reason + ")"


def _size_text(path: str, with_sizes: bool) -> str:
    if not os.path.isdir(path):
        return "-"
    return format_size(disk_usage(path)) if with_sizes else "?"


@dataclass(frozen=True)
class BuildRow:
    build_id: str
    mode: str
    suggestions: str
    built: str
    compile_time: str
    size: str


@dataclass(frozen=True)
class RunRow:
    run_id: str
    build_id: str
    mode: str
    threads: int
    started: str
    result: str
    size: str
    active: bool


def build_rows(arguments: ProjectManagerArguments, with_sizes: bool = False) -> List[BuildRow]:
    """One row per build; the state (which reads the project) is asked for with :func:`build_state_of`, the size
    (which reads the whole tree) only if ``with_sizes``."""
    return [
        BuildRow(
            record.build_id,
            record.mode,
            ",".join(record.suggestions) or "-",
            format_time(record.built_at),
            "%.1f s" % record.compile_seconds,
            _size_text(record.tree, with_sizes),
        )
        for record in list_builds(arguments.project_dir)
    ]


def active_run_id(arguments: ProjectManagerArguments) -> str:
    """The run whose data was put into the project's ``.discopop`` last, "" if none."""
    try:
        with open(os.path.join(arguments.dot_dp, "active_run.json")) as f:
            return str(json.load(f).get("run_id", ""))
    except (OSError, ValueError):
        return ""


def run_rows(arguments: ProjectManagerArguments, with_sizes: bool = False) -> List[RunRow]:
    active = active_run_id(arguments)
    return [
        RunRow(
            run.run_id,
            run.build_id,
            run.mode,
            run.thread_count,
            format_time(run.started_at),
            "running/aborted" if run.return_code is None else ("ok" if run.return_code == 0 else "failed"),
            _size_text(run.dot_discopop, with_sizes),
            run.run_id == active,
        )
        for run in list_all_runs(arguments)
    ]


def last_build_text(arguments: ProjectManagerArguments, configuration: Optional[str], mode: str) -> str:
    """One line about the builds of ``configuration`` in ``mode`` for a panel (reads the manifests only)."""
    records = [r for r in list_builds(arguments.project_dir) if r.configuration == configuration and r.mode == mode]
    if not records:
        return "No build yet."
    newest = max(records, key=lambda r: r.built_at)
    return "Compiled " + format_time(newest.built_at) + " (" + newest.build_id + ")."


def find_run(arguments: ProjectManagerArguments, run_id: str) -> Optional[RunRecord]:
    return next((run for run in list_all_runs(arguments) if run.run_id == run_id), None)


def activate(arguments: ProjectManagerArguments, run_id: str) -> str:
    """Activate the run; returns "" or the reason it cannot be activated."""
    run = find_run(arguments, run_id)
    if run is None:
        return "no run named " + run_id
    try:
        activate_run(arguments, run)
    except ActivationError as error:
        return str(error)
    return ""


def delete_selected_builds(arguments: ProjectManagerArguments, build_ids: Sequence[str]) -> List[str]:
    return delete_builds(arguments, list(build_ids))


def delete_selected_runs(arguments: ProjectManagerArguments, run_ids: Sequence[str]) -> List[str]:
    return delete_runs(arguments, list(run_ids))
