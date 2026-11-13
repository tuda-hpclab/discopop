# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``--list-builds`` and ``--delete-builds`` of the project manager."""

import os
import time
from typing import List

from tabulate import tabulate  # type: ignore

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
from discopop_library.ProjectManager.services.modes import settings_path as mode_settings_path


def build_state_of(arguments: ProjectManagerArguments, record: BuildRecord) -> str:
    """``current``, ``stale (<why>)`` or ``missing`` for the build of ``record``."""
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


def disk_usage(path: str) -> int:
    """The size of the files below ``path`` in bytes."""
    total = 0
    for directory, _subdirectories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def format_size(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (size, unit)
        size /= 1024
    return "%.1f TiB" % size


def show_builds(arguments: ProjectManagerArguments) -> None:
    records = list_builds(arguments.project_dir)
    if not records:
        print("No builds. A run of a configuration in a project copy (without --inplace) creates one.")
        return
    table: List[List[str]] = [["Build", "Mode", "Suggestions", "Built", "Compile time", "Size", "State"]]
    for record in records:
        table.append(
            [
                record.build_id,
                record.mode,
                ",".join(record.suggestions) or "-",
                time.strftime("%Y-%m-%d %H:%M", time.localtime(record.built_at)),
                "%.1f s" % record.compile_seconds,
                format_size(disk_usage(record.tree)) if os.path.isdir(record.tree) else "-",
                build_state_of(arguments, record),
            ]
        )
    print(tabulate(table, headers="firstrow", tablefmt="grid"))


def delete_builds_from_cli(arguments: ProjectManagerArguments) -> None:
    requested = (arguments.delete_builds or "all").strip()
    ids = None if requested == "all" else [name.strip() for name in requested.split(",") if name.strip()]
    known = {record.build_id for record in list_builds(arguments.project_dir)}
    for unknown in sorted(set(ids or []) - known):
        print("WARNING: no build named " + unknown + " (see --list-builds)")
    deleted = delete_builds(arguments, ids)
    print("Deleted " + str(len(deleted)) + " build(s)" + (": " + ", ".join(deleted) if deleted else "") + ".")
