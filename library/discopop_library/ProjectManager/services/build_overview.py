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
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.build_sharing import build_owner_of, members_of
from discopop_library.ProjectManager.configurations.builds import (
    BuildAcceptError,
    BuildChanges,
    BuildInUseError,
    BuildKey,
    BuildRecord,
    BuildState,
    ROLE_VALIDATE,
    accept_build,
    accepted_changes_text,
    build_status,
    build_trees_dir_of,
    delete_builds,
    key_of,
    list_builds,
)
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.runs import (
    ACTIVE_RUN_FILE,
    ActivationError,
    RunRecord,
    activate_run,
    active_run_ids,
    active_runs,
    delete_runs,
    disk_usage,
    list_all_runs,
)
from discopop_library.ProjectManager.services import fingerprint_ignore
from discopop_library.ProjectManager.services.hotspot_session import forget_build_states
from discopop_library.ProjectManager.services.explorer_state import explorer_prerequisites_met, required_explorer_files
from discopop_library.ProjectManager.services.modes import settings_path as mode_settings_path


def format_size(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (size, unit)
        size /= 1024
    return "%.1f TiB" % size


def format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _status_inputs(arguments: ProjectManagerArguments, record: BuildRecord) -> Optional[Tuple[BuildKey, str, str]]:
    """The key, compile script and settings file the state of the build of ``record`` is checked with; None if its
    configuration or the settings of its mode do not exist any more."""
    settings = mode_settings_path(arguments.project_config_dir, record.mode)
    config_dir = os.path.join(arguments.project_config_dir, record.configuration)
    if settings is None or not os.path.isdir(config_dir):
        return None
    key = key_of(record)
    return key, resolve_compile_script_path(arguments.project_config_dir, record.configuration), settings


_GONE = "the configuration or its settings do not exist any more"


def build_state_of(arguments: ProjectManagerArguments, record: BuildRecord) -> str:
    """``current``, ``stale (<why>)`` or ``missing (<why>)`` for the build of ``record``. Reads the whole project."""
    inputs = _status_inputs(arguments, record)
    if inputs is None:
        return "stale (" + _GONE + ")"
    status = build_status(arguments, *inputs)
    if status.state == BuildState.CURRENT:
        return "current"
    if status.state == BuildState.NONE:
        return "missing (" + status.reason + ")"
    return "stale (" + status.reason + ")"


@dataclass(frozen=True)
class BuildReview:
    """What the user sees before deciding about a stale build: rebuild, accept the changes, or ignore paths."""

    build_id: str
    state: BuildState
    reason: str
    changes: Optional[BuildChanges] = None
    # ignore patterns that would leave the changed files out (top-level directories git does not track)
    suggested_patterns: Tuple[str, ...] = ()
    # the changes accepted for the build before, if any
    accepted_before: str = ""
    # the ignore patterns of the project now
    patterns: Tuple[str, ...] = ()

    def file_lines(self, limit: int = 2000) -> List[str]:
        """One line per changed file (``M``odified, ``A``dded, ``D``eleted), at most ``limit``."""
        files = self.changes.files if self.changes is not None else None
        if files is None:
            return []
        marked = sorted(
            [(path, "M") for path in files.modified]
            + [(path, "A") for path in files.added]
            + [(path, "D") for path in files.removed]
        )
        lines = [mark + "  " + path for path, mark in marked[:limit]]
        if len(marked) > limit:
            lines.append("... and " + str(len(marked) - limit) + " more")
        return lines


def _tracked_top_level(project_root: str) -> Optional[Set[str]]:
    """The top-level names below which git tracks a file (the project may lie inside a larger work tree); None if
    the project is in no git work tree."""
    try:
        completed = subprocess.run(
            ["git", "-C", project_root, "ls-files", "-z", "--cached"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    names = completed.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return {name.split("/", 1)[0] for name in names if name}


# files that mark a build directory (CMake, Ninja, Meson, CACHEDIR.TAG of cargo and others)
_BUILD_DIRECTORY_MARKERS = ("CMakeCache.txt", "build.ninja", "meson-info", "CACHEDIR.TAG")


def _suggestions(arguments: ProjectManagerArguments, changes: Optional[BuildChanges]) -> Tuple[str, ...]:
    """Top-level directories with changed files that look like build directories: git tracks nothing in them, or,
    without git, they hold the marker of a build system. Code that git tracks is never proposed (its changes
    matter)."""
    if changes is None or changes.files is None or not changes.files:
        return ()
    tracked = _tracked_top_level(arguments.project_root)
    suggestions: List[str] = []
    for pattern in fingerprint_ignore.suggest_patterns(changes.files.paths):
        if not pattern.endswith("/"):
            continue
        name = pattern.rstrip("/")
        if tracked is not None:
            if name not in tracked:
                suggestions.append(pattern)
        elif any(os.path.exists(os.path.join(arguments.project_root, name, m)) for m in _BUILD_DIRECTORY_MARKERS):
            suggestions.append(pattern)
    return tuple(suggestions)


def review_build(arguments: ProjectManagerArguments, build_id: str) -> BuildReview:
    """What changed since the build ``build_id``. Reads the whole project."""
    record = next((r for r in list_builds(arguments.project_dir) if r.build_id == build_id), None)
    if record is None:
        return BuildReview(build_id, BuildState.NONE, "No such build.")
    inputs = _status_inputs(arguments, record)
    if inputs is None:
        return BuildReview(build_id, BuildState.STALE, _GONE[0].upper() + _GONE[1:] + ".")
    status = build_status(arguments, *inputs)
    return BuildReview(
        build_id,
        status.state,
        status.reason,
        status.changes,
        _suggestions(arguments, status.changes),
        accepted_changes_text(arguments.project_dir, inputs[0]),
        tuple(fingerprint_ignore.load_fingerprint_ignore(arguments.project_dir)),
    )


def accept_build_changes(arguments: ProjectManagerArguments, build_id: str) -> str:
    """Accept the changes since the build ``build_id`` (:func:`accept_build`); returns "" or why it was not done."""
    record = next((r for r in list_builds(arguments.project_dir) if r.build_id == build_id), None)
    if record is None:
        return "There is no build " + build_id + "."
    inputs = _status_inputs(arguments, record)
    if inputs is None:
        return "The build cannot be checked: " + _GONE + "."
    try:
        status = accept_build(arguments, *inputs)
    except BuildInUseError:
        return "The build " + build_id + " is in use by a run or a compilation; try again when it has finished."
    except BuildAcceptError as error:
        return str(error)
    finally:
        forget_build_states()
    if status.state == BuildState.CURRENT:
        return "The build " + build_id + " is current: there is nothing to accept."
    if status.state == BuildState.NONE:
        return status.reason
    return ""


def ignore_and_review(arguments: ProjectManagerArguments, build_id: str, patterns: Sequence[str]) -> BuildReview:
    """Add ``patterns`` to the ignore patterns of the project, then check the build ``build_id`` again."""
    fingerprint_ignore.add_patterns(arguments.project_dir, patterns)
    forget_build_states()
    return review_build(arguments, build_id)


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
    # the configurations that run in this build besides its own (see configurations/build_sharing.py)
    used_by: str = ""


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
            ", ".join(members_of(arguments.project_config_dir, record.configuration)),
        )
        for record in list_builds(arguments.project_dir)
    ]


def run_rows(
    arguments: ProjectManagerArguments, with_sizes: bool = False, modes: Optional[Sequence[str]] = None
) -> List[RunRow]:
    """One row per run, of the ``modes`` given (all if None)."""
    active = active_run_ids(arguments.dot_dp)
    return [
        RunRow(
            run.run_id,
            run.build_id,
            run.mode,
            run.thread_count,
            format_time(run.started_at),
            "running/aborted" if run.return_code is None else ("ok" if run.return_code == 0 else "failed"),
            _size_text(run.dot_discopop, with_sizes),
            run.run_id in active,
        )
        for run in list_all_runs(arguments)
        if modes is None or run.mode in modes
    ]


def last_build_text(arguments: ProjectManagerArguments, configuration: Optional[str], mode: str) -> str:
    """One line about the builds of ``configuration`` in ``mode`` for a panel (reads the manifests only)."""
    owner = build_owner_of(arguments.project_config_dir, configuration) if configuration else configuration
    records = [
        r
        for r in list_builds(arguments.project_dir)
        if r.configuration == owner and r.mode == mode and r.role != ROLE_VALIDATE
    ]
    if not records:
        return "No build yet."
    newest = max(records, key=lambda r: r.built_at)
    shared = " (shared: built from " + str(owner) + ")" if owner != configuration else ""
    return "Compiled " + format_time(newest.built_at) + " (" + newest.build_id + ")" + shared + "."


def active_profiling_run(arguments: ProjectManagerArguments) -> Optional[RunRecord]:
    """The dp run whose data the pattern detection reads (the project's ``.discopop/profiler``), or None if the data
    is not that of a kept run: it was never activated, or profiled in place or by another tool since (the profiling
    files are newer than the note of the activation)."""
    entry = active_runs(arguments.dot_dp).get("dp")
    if not entry or not entry.get("run_ids"):
        return None
    try:
        noted = os.path.getmtime(os.path.join(arguments.dot_dp, ACTIVE_RUN_FILE))
        newest = max(
            [os.path.getmtime(path) for path in required_explorer_files(arguments.dot_dp) if os.path.exists(path)]
            or [0.0]
        )
    except OSError:
        return None
    if newest > noted + 1.0:
        return None
    return find_run(arguments, str(entry["run_ids"][0]))


def profiling_basis_text(arguments: ProjectManagerArguments) -> str:
    """Which profiling data the pattern detection is based on, for its panel."""
    if not explorer_prerequisites_met(arguments.dot_dp):
        return "No profiling data."
    run = active_profiling_run(arguments)
    if run is None:
        return "The profiling data in the project (profiled in place or by another tool, not a kept run)."
    return "Run %s of the configuration %s, started %s (build %s)." % (
        run.run_id,
        run.configuration,
        format_time(run.started_at),
        run.build_id,
    )


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


def storage_of(path: str) -> int:
    """The bytes the files below ``path`` occupy; a file with several hard links (the runs link the static data of
    their build) counts once, which is what the disk holds."""
    seen: Set[Tuple[int, int]] = set()
    total = 0
    for directory, _subdirectories, files in os.walk(path):
        for name in files:
            try:
                info = os.lstat(os.path.join(directory, name))
            except OSError:
                continue
            if info.st_nlink > 1:
                if (info.st_dev, info.st_ino) in seen:
                    continue
                seen.add((info.st_dev, info.st_ino))
            total += info.st_size
    return total


def storage_warning(arguments: ProjectManagerArguments, expected_builds: Sequence[str]) -> Optional[str]:
    """A warning that builds and runs pile up in ``<project>_discopop_builds``, or None while they do not.

    ``expected_builds`` are the ids of the builds the caller works with. Builds beyond them and runs whose data is not
    in the project (see :func:`active_runs`) are what accumulates (every rebuild, every further input, every
    configuration leaves one), so only they trigger the warning; it then states the totals, the number of builds and runs and the
    storage they occupy. Nothing is ever deleted automatically: the text names the commands for that. The size is
    only computed if there is something to warn about, as it reads every file of the trees.
    """
    builds = list_builds(arguments.project_dir)
    runs = list_all_runs(arguments)
    # the runs whose data is in the project are the ones in use; the others (older runs of inputs that were
    # profiled again, failed runs, runs of builds that were built again) accumulate
    in_use = active_run_ids(arguments.dot_dp)
    extra_builds = [build for build in builds if build.build_id not in expected_builds]
    extra_runs = [run for run in runs if run.run_id not in in_use]
    if not extra_builds and not extra_runs:
        return None
    trees = build_trees_dir_of(arguments.project_root)
    return (
        "%d builds and %d runs of this project occupy %s in %s: %d builds beyond those used here and %d older runs. "
        "Builds and runs are never deleted automatically; the user can list them with `discopop_project_manager "
        "--list-builds` / `--list-runs` and remove what is no longer needed with `--delete-builds` / "
        '`--delete-runs` (or in the GUI card "Builds and runs"). Do not delete them yourself.'
        % (len(builds), len(runs), format_size(storage_of(trees)), trees, len(extra_builds), len(extra_runs))
    )
