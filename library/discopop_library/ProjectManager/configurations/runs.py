# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Runs of an instrumented build: what a profiling run wrote, kept apart from the build and from other runs.

The compilation of a dp or hd build writes static data (code structure, call path tables, file ids) into the
``.discopop`` of its build tree, and the instrumented program reads some of it and writes its results next to it.
Runs of one build with different inputs would overwrite each other's results, and results of a run would
accumulate in the build. Every run therefore gets a ``.discopop`` directory of its own,
``<build trees directory>/<build id>.runs/<run id>``, prepared from the static data of the build, and is
executed with ``DOT_DISCOPOP`` pointing to it. The profiler needs no knowledge of this.
A run does not live in the tree of its build, so that building again does not delete it.

What the pattern detection, the hotspot analysis and the other tools read is the ``.discopop`` of the project.
:func:`activate_run` puts a run there, with the paths of the build tree replaced by those of the project; until
then the data of a run is not touched by anything but its own process.

Runs are never deleted automatically; see :func:`delete_runs`.

This module imports no GUI toolkit.
"""

import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import BuildRecord, build_trees_dir_of

PATH = str

logger = logging.getLogger("ConfigurationManager")

RUNS_DIRECTORY_SUFFIX = ".runs"
MANIFEST_NAME = "run.json"
MANIFEST_VERSION = 1

# the modes whose runs write profiling data
PROFILING_MODES = ("dp", "hd")

# the files of the profiler directory that the instrumented program creates or changes: they are copied into a run,
# everything else is linked (a link shares the data of the build instead of duplicating it; the program never
# opens these files for writing)
_COPIED_PROFILER_FILE_PREFIXES = ("DP_",)
_COPIED_PROFILER_DIRECTORIES = ("statistics", "locking_files")

# how much of a file is read at once when paths are replaced
_CHUNK_SIZE = 8 << 20

# the files below the data of a run that hold paths of the build tree, which are replaced on activation
_REWRITTEN_SUFFIXES = (".txt", ".json", ".xml", ".dot")

# the top level files and directories of a ``.discopop`` that a profiling run needs / produces, per mode
_RUN_FILES = {
    "dp": ("FileMapping.txt", "instrumented_project_directories.json"),
    "hd": ("FileMapping.txt", "instrumented_project_directories.json"),
}
_RUN_DIRECTORIES = {"dp": ("profiler",), "hd": ("hotspot_detection",)}


@dataclass
class RunRecord:
    """The manifest of a run (``run.json`` in its directory)."""

    run_id: str
    build_id: str
    configuration: str
    mode: str
    thread_count: int
    label: str
    started_at: float
    # the directory of the run: its DOT_DISCOPOP
    dot_discopop: PATH
    # the tree the build had when the run was made (its paths are in the data of the run) and its suggestions
    tree: PATH = ""
    suggestions: Optional[List[str]] = None
    # None while the run is going on
    return_code: Optional[int] = None
    finished_at: Optional[float] = None
    version: int = MANIFEST_VERSION


def runs_directory_of(project_root: PATH, build_id: str) -> PATH:
    return os.path.join(build_trees_dir_of(project_root), build_id + RUNS_DIRECTORY_SUFFIX)


def _new_run_id(runs_directory: PATH) -> str:
    base = time.strftime("%Y%m%d-%H%M%S")
    run_id = base
    counter = 1
    while os.path.exists(os.path.join(runs_directory, run_id)):
        counter += 1
        run_id = base + "-" + str(counter)
    return run_id


def _is_runtime_written(relative_path: str) -> bool:
    first = relative_path.split(os.sep, 1)[0]
    return os.path.basename(relative_path).startswith(_COPIED_PROFILER_FILE_PREFIXES) or first in (
        _COPIED_PROFILER_DIRECTORIES
    )


def _link_or_copy(source: PATH, destination: PATH, link: bool) -> None:
    if link:
        try:
            os.link(source, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


def _clone_directory(source: PATH, destination: PATH, link_files: bool) -> None:
    for directory, subdirectories, files in os.walk(source):
        relative = os.path.relpath(directory, source)
        target = destination if relative == "." else os.path.join(destination, relative)
        os.makedirs(target, exist_ok=True)
        for name in files:
            relative_file = name if relative == "." else os.path.join(relative, name)
            _link_or_copy(
                os.path.join(directory, name),
                os.path.join(target, name),
                link_files and not _is_runtime_written(relative_file),
            )


def prepare_run(project_root: PATH, build: BuildRecord, thread_count: int, label: str = "") -> RunRecord:
    """Create the directory of a new run of ``build`` and fill it with the static data of the build."""
    run_mode = build.mode
    runs_directory = runs_directory_of(project_root, build.build_id)
    os.makedirs(runs_directory, exist_ok=True)
    run_id = _new_run_id(runs_directory)
    dot = os.path.join(runs_directory, run_id)
    os.makedirs(dot)
    build_dot = os.path.join(build.tree, ".discopop")
    for name in _RUN_FILES.get(run_mode, ()):
        if os.path.isfile(os.path.join(build_dot, name)):
            shutil.copy2(os.path.join(build_dot, name), os.path.join(dot, name))
    for name in _RUN_DIRECTORIES.get(run_mode, ()):
        if os.path.isdir(os.path.join(build_dot, name)):
            _clone_directory(os.path.join(build_dot, name), os.path.join(dot, name), link_files=name == "profiler")
    record = RunRecord(
        run_id=run_id,
        build_id=build.build_id,
        configuration=build.configuration,
        mode=run_mode,
        thread_count=thread_count,
        label=label,
        started_at=time.time(),
        dot_discopop=dot,
        tree=build.tree,
        suggestions=list(build.suggestions),
    )
    write_run(record)
    return record


def write_run(record: RunRecord) -> None:
    path = os.path.join(record.dot_discopop, MANIFEST_NAME)
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(asdict(record), f, indent=4, sort_keys=True)
    os.replace(temporary, path)


def finish_run(record: RunRecord, return_code: Optional[int]) -> None:
    record.return_code = return_code
    record.finished_at = time.time()
    write_run(record)


def read_run(dot_discopop: PATH) -> Optional[RunRecord]:
    try:
        with open(os.path.join(dot_discopop, MANIFEST_NAME), "r") as f:
            data: Dict[str, Any] = json.load(f)
        if data.get("version") != MANIFEST_VERSION:
            return None
        return RunRecord(**data)
    except (OSError, ValueError, TypeError):
        return None


def list_all_runs(arguments: ProjectManagerArguments) -> List[RunRecord]:
    """The runs of all builds of the project (also of builds that were built again or deleted), oldest first."""
    trees = build_trees_dir_of(arguments.project_root)
    records: List[RunRecord] = []
    if os.path.isdir(trees):
        for entry in sorted(os.listdir(trees)):
            directory = os.path.join(trees, entry)
            if not entry.endswith(RUNS_DIRECTORY_SUFFIX) or not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory)):
                record = read_run(os.path.join(directory, name))
                if record is not None:
                    records.append(record)
    return sorted(records, key=lambda r: (r.started_at, r.run_id))


def latest_successful_run(arguments: ProjectManagerArguments, mode: str = "dp") -> Optional[RunRecord]:
    candidates = [r for r in list_all_runs(arguments) if r.mode == mode and r.return_code == 0]
    return candidates[-1] if candidates else None


def disk_usage(path: PATH) -> int:
    """The size of the files below ``path`` in bytes; files linked to the build count in full."""
    total = 0
    for directory, _subdirectories, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def delete_runs(arguments: ProjectManagerArguments, run_ids: Optional[Sequence[str]] = None) -> List[str]:
    """Delete the runs with the given ids (all if None). Returns the deleted ids.

    Only directories below the run directories of this project's builds are removed. The project's own
    ``.discopop`` (what an activated run put there) is left alone.
    """
    deleted: List[str] = []
    trees = os.path.abspath(build_trees_dir_of(arguments.project_root))
    for record in list_all_runs(arguments):
        if run_ids is not None and record.run_id not in run_ids:
            continue
        target = os.path.abspath(record.dot_discopop)
        parent = os.path.dirname(target)
        if os.path.dirname(parent) != trees or not parent.endswith(RUNS_DIRECTORY_SUFFIX) or not os.path.isdir(target):
            logger.warning("not removing " + target + ": it is no run directory of this project")
            continue
        shutil.rmtree(target)
        deleted.append(record.run_id)
        if not os.listdir(parent):
            os.rmdir(parent)
    return deleted


# ── activation ──────────────────────────────────────────────────────────────


class ActivationError(Exception):
    """A run cannot be put into the project."""


def replace_in_file(source: PATH, destination: PATH, old: str, new: str) -> bool:
    """Copy ``source`` to ``destination`` with every ``old`` replaced by ``new``; True if there was one.

    Streams the file, so a large file (the AST dump) is never held in memory. A file without ``old`` is copied as is.
    """
    old_bytes, new_bytes = old.encode(), new.encode()
    keep = len(old_bytes) - 1
    replaced = False
    with open(source, "rb") as src, open(destination, "wb") as dst:
        carry = b""
        while True:
            chunk = src.read(_CHUNK_SIZE)
            if not chunk:
                break
            data = carry + chunk
            # what is written now must not end inside an ``old``, nor in what may become one with the next chunk
            cut = max(len(data) - keep, 0)
            straddling = data.find(old_bytes, max(0, cut - len(old_bytes) + 1))
            if straddling != -1 and straddling < cut:
                cut = straddling
            head, carry = data[:cut], data[cut:]
            replaced = replaced or old_bytes in head
            dst.write(head.replace(old_bytes, new_bytes))
        replaced = replaced or old_bytes in carry
        dst.write(carry.replace(old_bytes, new_bytes))
    shutil.copystat(source, destination)
    return replaced


def _copy_tree_rewriting(source: PATH, destination: PATH, old: str, new: str) -> None:
    for directory, _subdirectories, files in os.walk(source):
        relative = os.path.relpath(directory, source)
        target = destination if relative == "." else os.path.join(destination, relative)
        os.makedirs(target, exist_ok=True)
        for name in files:
            source_file = os.path.join(directory, name)
            destination_file = os.path.join(target, name)
            if name.endswith(_REWRITTEN_SUFFIXES):
                replace_in_file(source_file, destination_file, old, new)
            else:
                shutil.copy2(source_file, destination_file)


def activate_run(arguments: ProjectManagerArguments, run: RunRecord) -> List[str]:
    """Put the data of ``run`` into the ``.discopop`` of the project, where the pattern detection reads it.

    The data of the same kind that was there is replaced (``profiler`` for a dp run, ``hotspot_detection`` for an
    hd run), the paths of the build tree in it become paths of the project, and the results derived from the data
    that was there (explorer, patches) are left alone, which the workflow status then reports as outdated. Returns
    the replaced entries of ``.discopop``.

    Raises :class:`ActivationError` for a run that is unfinished or failed, or whose build has suggestions applied
    (its line numbers do not match the project's sources).
    """
    if run.mode not in PROFILING_MODES:
        raise ActivationError("only runs of the modes " + ", ".join(PROFILING_MODES) + " write profiling data")
    if run.return_code != 0:
        raise ActivationError("the run " + run.run_id + " did not finish successfully")
    if run.suggestions:
        raise ActivationError(
            "the build of the run "
            + run.run_id
            + " had suggestions applied: its line numbers differ from the project's"
        )
    run_dot = os.path.abspath(run.dot_discopop)
    if not os.path.isdir(run_dot):
        raise ActivationError("the data of the run " + run.run_id + " does not exist any more")

    tree = os.path.abspath(run.tree)
    root = os.path.abspath(arguments.project_root)
    dot = arguments.dot_dp
    os.makedirs(dot, exist_ok=True)
    staging = os.path.join(dot, ".activating")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    replaced: List[str] = []
    try:
        for name in _RUN_FILES[run.mode]:
            if os.path.isfile(os.path.join(run_dot, name)):
                replace_in_file(os.path.join(run_dot, name), os.path.join(staging, name), tree, root)
        for name in _RUN_DIRECTORIES[run.mode]:
            if os.path.isdir(os.path.join(run_dot, name)):
                _copy_tree_rewriting(os.path.join(run_dot, name), os.path.join(staging, name), tree, root)
        # everything is prepared: swap it in
        for name in sorted(os.listdir(staging)):
            target = os.path.join(dot, name)
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.remove(target)
            os.replace(os.path.join(staging, name), target)
            replaced.append(name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # which run the data of the project comes from
    with open(os.path.join(dot, "active_run.json"), "w") as f:
        json.dump({"run_id": run.run_id, "build_id": run.build_id, "mode": run.mode}, f, indent=4)
    return replaced
