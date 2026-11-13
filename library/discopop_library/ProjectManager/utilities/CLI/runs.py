# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``--list-runs``, ``--delete-runs`` and ``--activate-run`` of the project manager."""

import os
import sys
import time
from typing import List

from tabulate import tabulate  # type: ignore

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.runs import (
    ActivationError,
    activate_run,
    delete_runs,
    disk_usage,
    latest_successful_run,
    list_all_runs,
)
from discopop_library.ProjectManager.utilities.CLI.builds import format_size


def show_runs(arguments: ProjectManagerArguments) -> None:
    runs = list_all_runs(arguments)
    if not runs:
        print("No runs. A dp or hd run of a configuration in a build (without --inplace) creates one.")
        return
    active = _active_run_id(arguments)
    table: List[List[str]] = [["Run", "Build", "Mode", "Threads", "Started", "Result", "Size", "Active"]]
    for run in runs:
        table.append(
            [
                run.run_id,
                run.build_id,
                run.mode,
                str(run.thread_count),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(run.started_at)),
                "running/aborted" if run.return_code is None else ("ok" if run.return_code == 0 else "failed"),
                format_size(disk_usage(run.dot_discopop)) if os.path.isdir(run.dot_discopop) else "-",
                "yes" if run.run_id == active else "",
            ]
        )
    print(tabulate(table, headers="firstrow", tablefmt="grid"))


def _active_run_id(arguments: ProjectManagerArguments) -> str:
    import json

    try:
        with open(os.path.join(arguments.dot_dp, "active_run.json")) as f:
            return str(json.load(f).get("run_id", ""))
    except (OSError, ValueError):
        return ""


def delete_runs_from_cli(arguments: ProjectManagerArguments) -> None:
    requested = (arguments.delete_runs or "all").strip()
    ids = None if requested == "all" else [name.strip() for name in requested.split(",") if name.strip()]
    known = {run.run_id for run in list_all_runs(arguments)}
    for unknown in sorted(set(ids or []) - known):
        print("WARNING: no run named " + unknown + " (see --list-runs)")
    deleted = delete_runs(arguments, ids)
    print("Deleted " + str(len(deleted)) + " run(s)" + (": " + ", ".join(deleted) if deleted else "") + ".")


def activate_run_from_cli(arguments: ProjectManagerArguments) -> None:
    """Put the run into the project's .discopop (``latest`` / no id: the latest successful dp run)."""
    requested = (arguments.activate_run or "latest").strip()
    if requested == "latest":
        run = latest_successful_run(arguments)
        if run is None:
            print("ERROR: there is no successful dp run (see --list-runs)")
            sys.exit(1)
    else:
        candidates = [r for r in list_all_runs(arguments) if r.run_id == requested]
        if not candidates:
            print("ERROR: no run named " + requested + " (see --list-runs)")
            sys.exit(1)
        run = candidates[0]
    try:
        replaced = activate_run(arguments, run)
    except ActivationError as error:
        print("ERROR: " + str(error))
        sys.exit(1)
    print(
        "Activated the run "
        + run.run_id
        + " of "
        + run.build_id
        + " in "
        + arguments.dot_dp
        + " ("
        + ", ".join(replaced)
        + ")."
    )
