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
import re
import shutil
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

from filelock import FileLock, Timeout

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

# a run without a result is taken for one that is going on this long, then for one that was aborted
_UNFINISHED_RUN_GRACE_SECONDS = 24 * 3600

# how much of a file is read at once when paths are replaced
_CHUNK_SIZE = 8 << 20

# the files below the data of a run that hold paths of the build tree, which are replaced on activation
_REWRITTEN_SUFFIXES = (".txt", ".json", ".xml", ".dot")

# what an instrumented program writes: never carried into a run. The compilation may have run instrumented programs
# (configure tests), which leave such files in the build; a run must start without them (and a link to them would let
# every run overwrite the others' results)
_RESULT_FILES = ("dynamic_dependencies.txt", "loop_counter_output.txt", "cu_taken_branch_counter_output.txt")
_RESULT_FILE_PREFIXES = ("hotspot_result_",)

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


def _taken(run_id: str, trees: PATH) -> bool:
    """Whether a run of any build has the id (ids are used on their own, e.g. by ``--delete-runs``)."""
    if not os.path.isdir(trees):
        return False
    return any(
        entry.endswith(RUNS_DIRECTORY_SUFFIX) and os.path.exists(os.path.join(trees, entry, run_id))
        for entry in os.listdir(trees)
    )


def _new_run_id(runs_directory: PATH) -> str:
    trees = os.path.dirname(runs_directory)
    base = time.strftime("%Y%m%d-%H%M%S")
    run_id = base
    counter = 1
    while _taken(run_id, trees):
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


def _is_result_file(name: str) -> bool:
    return name in _RESULT_FILES or name.startswith(_RESULT_FILE_PREFIXES)


def _clone_directory(source: PATH, destination: PATH, link_files: bool) -> None:
    for directory, subdirectories, files in os.walk(source):
        relative = os.path.relpath(directory, source)
        target = destination if relative == "." else os.path.join(destination, relative)
        os.makedirs(target, exist_ok=True)
        for name in files:
            if _is_result_file(name):
                continue
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
    candidates = [r for r in list_all_runs(arguments) if r.mode == mode and r.return_code == 0 and not r.suggestions]
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
        if record.return_code is None and time.time() - record.started_at < _UNFINISHED_RUN_GRACE_SECONDS:
            logger.warning("not deleting the run " + record.run_id + ": it may still be running")
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
    """Copy ``source`` to ``destination`` with every path ``old`` replaced by ``new``; True if there was one.

    ``old`` is a directory: it only counts where it ends (the next character is no part of a name), so that the tree
    ``/b/cfg_dp`` is not found in ``/b/cfg_dp_s1a2b`` or ``/b/cfg_dp.runs``. Streams the file, so a large file (the AST
    dump) is never held in memory. A file without ``old`` is copied as is.
    """
    pattern = re.compile(re.escape(old.encode()) + rb"(?![\w.\-])")
    new_bytes = new.encode()
    keep = len(old.encode()) + 1
    replaced = False
    with open(source, "rb") as src, open(destination, "wb") as dst:
        carry = b""
        while True:
            chunk = src.read(_CHUNK_SIZE)
            if not chunk:
                break
            data = carry + chunk
            # what is written now must not end inside an ``old`` or before the character that decides whether it counts
            cut = max(len(data) - keep, 0)
            for match in pattern.finditer(data, max(0, cut - keep)):
                if match.start() < cut < match.end() + 1:
                    cut = match.start()
                    break
            head, carry = data[:cut], data[cut:]
            head, count = pattern.subn(lambda _match: new_bytes, head)
            replaced = replaced or count > 0
            dst.write(head)
        carry, count = pattern.subn(lambda _match: new_bytes, carry)
        replaced = replaced or count > 0
        dst.write(carry)
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


def _mapping_of(path: PATH) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                file_id, separator, file_path = line.rstrip("\n").partition("\t")
                if separator:
                    mapping[file_id] = file_path
    except OSError:
        pass
    return mapping


def _mapping_conflict(project_mapping: PATH, run_mapping: PATH, tree: PATH, root: PATH) -> Optional[str]:
    """Why the file ids of the run (paths of the tree turned into those of the project) differ from those of the
    project, None if they agree where both know a file."""
    mine = _mapping_of(project_mapping)
    theirs = {
        file_id: (root + path[len(tree) :] if path == tree or path.startswith(tree + os.sep) else path)
        for file_id, path in _mapping_of(run_mapping).items()
    }
    by_path = {path: file_id for file_id, path in mine.items()}
    for file_id, path in theirs.items():
        if file_id in mine and mine[file_id] != path:
            return "the file id " + file_id + " is " + mine[file_id] + " in the project and " + path + " in the run"
        if path in by_path and by_path[path] != file_id:
            return path + " has the file id " + by_path[path] + " in the project and " + file_id + " in the run"
    return None


def _write_json_atomically(path: PATH, data: Dict[str, Any]) -> None:
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(temporary, path)


def activate_run(arguments: ProjectManagerArguments, run: RunRecord) -> List[str]:
    """Put the data of ``run`` into the ``.discopop`` of the project, where the pattern detection reads it.

    The data of the same kind that was there is replaced (``profiler`` for a dp run, ``hotspot_detection`` for an
    hd run), the paths of the build tree in it become paths of the project, and the results derived from the data
    that was there (explorer, patches) are left alone, which the workflow status then reports as outdated. Returns
    the replaced entries of ``.discopop``. Either everything is replaced or, if that fails, nothing.

    Raises :class:`ActivationError` for a run that is unfinished or failed, whose build has suggestions applied (its
    line numbers do not match the project's sources), or whose file ids contradict those of the data of the other
    kind that stays in the project (the file ids belong to the build; dp and hd builds assign them independently).
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
    # the data that stays: whatever the run does not replace, but depends on the file ids
    other = {"dp": "hotspot_detection", "hd": "profiler"}[run.mode]
    if os.path.isdir(os.path.join(dot, other)):
        conflict = _mapping_conflict(
            os.path.join(dot, "FileMapping.txt"), os.path.join(run_dot, "FileMapping.txt"), tree, root
        )
        if conflict is not None:
            raise ActivationError(
                "the file ids of the run do not fit the " + other + " data in the project (" + conflict + "); "
                "profile that mode again or delete its data first"
            )
    try:
        with FileLock(os.path.join(dot, ".activate.lock"), timeout=0):
            return _activate_locked(arguments, run, run_dot, tree, root, dot)
    except Timeout:
        raise ActivationError("another run is being put into the project right now")
    except OSError as error:
        raise ActivationError("the run could not be put into the project: " + str(error))


def _activate_locked(
    arguments: ProjectManagerArguments, run: RunRecord, run_dot: PATH, tree: PATH, root: PATH, dot: PATH
) -> List[str]:
    staging = os.path.join(dot, ".activating")
    backup = os.path.join(dot, ".replaced")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    os.makedirs(staging)
    os.makedirs(backup)
    replaced: List[str] = []
    swapped: List[str] = []
    try:
        for name in _RUN_FILES[run.mode]:
            if os.path.isfile(os.path.join(run_dot, name)):
                replace_in_file(os.path.join(run_dot, name), os.path.join(staging, name), tree, root)
        for name in _RUN_DIRECTORIES[run.mode]:
            if os.path.isdir(os.path.join(run_dot, name)):
                _copy_tree_rewriting(os.path.join(run_dot, name), os.path.join(staging, name), tree, root)
        # everything is prepared: swap it in, keeping what it replaces until all is in place
        for name in sorted(os.listdir(staging)):
            target = os.path.join(dot, name)
            if os.path.lexists(target):
                os.replace(target, os.path.join(backup, name))
            swapped.append(name)
            os.replace(os.path.join(staging, name), target)
            replaced.append(name)
        _write_json_atomically(
            os.path.join(dot, "active_run.json"), {"run_id": run.run_id, "build_id": run.build_id, "mode": run.mode}
        )
    except BaseException:
        # put back what was there
        for name in swapped:
            target = os.path.join(dot, name)
            saved = os.path.join(backup, name)
            if os.path.lexists(saved):
                if os.path.isdir(target) and not os.path.islink(target):
                    shutil.rmtree(target, ignore_errors=True)
                os.replace(saved, target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
    return replaced
