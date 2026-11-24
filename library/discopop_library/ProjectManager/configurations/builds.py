# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Builds of a configuration: what was compiled in which mode, and whether it can serve another run.

Compiling can take very long for large codes, whereas a run of the result (another input, another thread
count) is cheap in comparison. A *build* is therefore kept as a project copy of its own (the *build tree*)
together with a manifest in ``.discopop/project/builds/<id>.json``, so that further runs execute in the same
tree instead of building again.

A build is identified by its :class:`BuildKey`: the configuration, the mode (seq, dp, hd, par) and the
suggestions applied to its sources. Whether it is still usable is decided by its *fingerprint*, which covers
everything that decides what the compilation produces (see :func:`compute_fingerprint`). The manifests
and the build trees are never deleted automatically; see :func:`delete_build`.

This module imports no GUI toolkit.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from filelock import FileLock, Timeout

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.build_sharing import RUN_ONLY_FILES
from discopop_library.ProjectManager.configurations.project_environment import project_directories_of
from discopop_library.ProjectManager.services import callpath_pruning, openmp_handling
from discopop_library.ProjectManager.configurations.copy_exclusions import drop_below, left_out_paths
from discopop_library.ProjectManager.configurations.tree_sync import (
    CLEAN,
    DIRTY,
    read_tree_state,
    remove_tree_state,
    set_tree_state,
)
from discopop_library.ProjectManager.services.copy_exclude import load_copy_exclude
from discopop_library.ProjectManager.services.fingerprint_ignore import is_ignored, load_fingerprint_ignore

PATH = str

logger = logging.getLogger("ConfigurationManager")

MANIFEST_VERSION = 1

# directories whose content is no input of a compilation: DiscoPoP's own data and version control
_FINGERPRINT_PRUNED_DIRS = (".discopop", ".git")


class BuildPolicy(str, Enum):
    """When a run compiles."""

    # compile when there is no build or it is stale (the default)
    AUTO = "auto"
    # compile in any case
    REBUILD = "rebuild"
    # never compile; a missing or stale build is an error
    REUSE = "reuse"


class BuildState(str, Enum):
    NONE = "none"
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True)
class BuildKey:
    """What identifies a build."""

    configuration: str
    mode: str
    # the ids of the suggestions applied to the sources; only they make builds of the same mode differ
    suggestions: Tuple[str, ...] = ()
    # what the build is for: "" (the runs of the mode) or ROLE_VALIDATE (the validation build, compile_validate.sh)
    role: str = ""

    @property
    def build_id(self) -> str:
        build_id = self.configuration + "_" + self.mode
        if self.suggestions:
            digest = hashlib.sha1(",".join(sorted(self.suggestions)).encode()).hexdigest()[:8]
            build_id += "_s" + digest
        if self.role:
            build_id += "_" + self.role
        return build_id


ROLE_VALIDATE = "validate"


@dataclass
class BuildRecord:
    """The manifest of a build."""

    build_id: str
    configuration: str
    mode: str
    suggestions: List[str]
    fingerprint: str
    tree: PATH
    # time.time() when the compilation finished
    built_at: float
    compile_seconds: float
    compile_script: PATH
    version: int = MANIFEST_VERSION
    # what the fingerprint was made of, to tell what changed when a build is stale
    fingerprint_parts: Dict[str, str] = field(default_factory=dict)
    # BuildKey.role (manifests written before it have none: the runs of the mode)
    role: str = ""


def key_of(record: BuildRecord) -> BuildKey:
    """The key of the build ``record`` describes. The one place that turns a manifest back into a key, so that a
    field added to :class:`BuildKey` cannot be forgotten by its callers."""
    return BuildKey(record.configuration, record.mode, tuple(record.suggestions), record.role)


@dataclass
class BuildFiles:
    """What a build keeps besides its manifest, in ``builds/fingerprints/<id>.json``: the files of the project the
    fingerprint was computed from (:func:`source_entries`, to tell which files changed) and the changes the user
    accepted (:func:`accept_build`). Kept apart from the manifest, so that its format stays the same."""

    sources: Dict[str, str] = field(default_factory=dict)
    accepted: List[Dict[str, Any]] = field(default_factory=list)
    # the fingerprint of the manifest these files belong to: a manifest written without them (by an older version
    # of DiscoPoP, which keeps no file list) must not be compared with the files of the build before
    fingerprint: str = ""
    # the paths the copy left out and the fingerprint did not count (configured build directories, copy_exclude),
    # so that such a directory deleted later does not count as removed files
    left_out: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileChanges:
    """The files of the project that changed since a build (relative paths, sorted)."""

    added: Tuple[str, ...] = ()
    removed: Tuple[str, ...] = ()
    modified: Tuple[str, ...] = ()
    # the build recorded no file list (built before it was kept): ``modified`` are the files newer than the build,
    # additions and removals are unknown
    approximate: bool = False

    @property
    def paths(self) -> Tuple[str, ...]:
        return tuple(sorted(self.added + self.removed + self.modified))

    def __len__(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


@dataclass(frozen=True)
class BuildChanges:
    """What differs between a stale build and the project."""

    # the names of the fingerprint parts that differ
    parts: Tuple[str, ...]
    # the changed files if ``sources`` differs and they are known
    files: Optional[FileChanges] = None
    # (part, why) for parts whose change has a cause elsewhere (callpath_pruning: outdated hotspot results)
    causes: Tuple[Tuple[str, str], ...] = ()

    @property
    def content_only(self) -> bool:
        """Whether only what the tree holds changed (:data:`CONTENT_PARTS`): the tree can be brought up to date
        by writing the changed files into it. Any other part changes how the code is compiled."""
        return all(part in CONTENT_PARTS for part in self.parts)


# The parts of the fingerprint (compute_fingerprint), split by what a change of them means for a kept build tree:
# - content: the files the tree holds (the sources of the project and of the included directories, the patches
#   of the applied suggestions, what the copy leaves out); writing the changed files into the tree suffices
# - environment: how the tree is compiled (scripts, settings, compilers, profiler, what is instrumented and how);
#   the tree has to be built from scratch
# Every part belongs to exactly one of them (checked by test_builds.py).
# not computed but found: the kept tree holds the code of another build (BuildStatus of build_status)
TREE_PART = "tree"
CONTENT_PARTS = frozenset({"sources", "included_sources", "patches", "copy_exclude", TREE_PART})
ENVIRONMENT_PARTS = frozenset(
    {
        "compile_script",
        "settings",
        "project_directories",
        "configuration",
        "toolchain",
        "callpath_pruning",
        "openmp",
    }
)


@dataclass(frozen=True)
class BuildStatus:
    state: BuildState
    reason: str
    record: Optional[BuildRecord] = None
    # for a stale build: what changed
    changes: Optional[BuildChanges] = None

    @property
    def usable(self) -> bool:
        return self.state == BuildState.CURRENT


def builds_dir_of(project_dir: PATH) -> PATH:
    """The directory of the build manifests (``.discopop/project/builds``)."""
    return os.path.join(project_dir, "builds")


def build_files_path_of(project_dir: PATH, key: BuildKey) -> PATH:
    """The :class:`BuildFiles` of the build ``key``; in a subdirectory, which :func:`list_builds` does not read."""
    return os.path.join(builds_dir_of(project_dir), "fingerprints", key.build_id + ".json")


def manifest_path_of(project_dir: PATH, key: BuildKey) -> PATH:
    return os.path.join(builds_dir_of(project_dir), key.build_id + ".json")


def build_trees_dir_of(project_root: PATH) -> PATH:
    """The directory holding the build trees: next to the project, like every project copy."""
    root = os.path.abspath(project_root)
    return os.path.join(str(Path(root).parent), os.path.basename(root) + "_discopop_builds")


def build_tree_path_of(project_root: PATH, key: BuildKey) -> PATH:
    return os.path.join(build_trees_dir_of(project_root), key.build_id)


def tree_key(key: BuildKey) -> BuildKey:
    """The key whose kept tree the build ``key`` is compiled in: one tree per configuration, mode and role holds the
    builds of every set of suggestions, one at a time (``configurations/tree_sync.py``)."""
    return BuildKey(key.configuration, key.mode, (), key.role)


def kept_tree_path_of(project_root: PATH, key: BuildKey) -> PATH:
    return build_tree_path_of(project_root, tree_key(key))


def build_lock_path_of(project_dir: PATH, key: BuildKey) -> PATH:
    """The lock that serializes everything using or changing the tree of ``key``; the builds of all sets of
    suggestions share it, as they share the tree."""
    return manifest_path_of(project_dir, tree_key(key)) + ".build.lock"


def _same_path(first: PATH, second: PATH) -> bool:
    return os.path.abspath(first) == os.path.abspath(second)


def _hash_file(path: PATH) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return "missing"
    return digest.hexdigest()


def _git_files(root: PATH) -> Optional[List[str]]:
    """The files of the project that git knows or does not ignore (relative to ``root``), None if ``root`` is no
    git work tree or git fails. Build outputs, which a ``.gitignore`` normally lists, thereby do not count."""
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return [name for name in completed.stdout.decode("utf-8", errors="surrogateescape").split("\0") if name]


def _walk_files(root: PATH) -> List[str]:
    files: List[str] = []
    for directory, subdirectories, names in os.walk(root):
        if directory == root:
            subdirectories[:] = [d for d in subdirectories if d not in _FINGERPRINT_PRUNED_DIRS]
        files.extend(os.path.relpath(os.path.join(directory, name), root) for name in names)
    return files


def source_entries(project_root: PATH) -> Dict[str, str]:
    """The files below ``project_root`` that the fingerprint looks at (see :func:`source_fingerprint`), each with its
    size and modification time (or ``missing``), before the ignore patterns of the project are applied."""
    root = os.path.abspath(project_root)
    names = _git_files(root)
    if names is None:
        names = _walk_files(root)
    else:
        names = [name for name in names if name.split("/", 1)[0] not in _FINGERPRINT_PRUNED_DIRS]
    return _entries(root, names)


def without_ignored(entries: Dict[str, str], patterns: Sequence[str]) -> Dict[str, str]:
    """``entries`` without the files the ignore patterns (``services/fingerprint_ignore.py``) leave out."""
    if not patterns:
        return entries
    return {name: value for name, value in entries.items() if not is_ignored(name, patterns)}


def left_out_of(
    arguments: ProjectManagerArguments, entries: Dict[str, str], patterns: Optional[Sequence[str]] = None
) -> List[str]:
    """The paths a copy of the project leaves out (configured build directories and the paths of
    ``copy_exclude.json``, ``configurations/copy_exclusions.py``), as far as they concern ``entries`` (those of
    :func:`source_entries` that the ignore patterns ``patterns``, by default the project's, keep)."""
    if patterns is None:
        patterns = load_fingerprint_ignore(arguments.project_dir)
    return left_out_paths(
        arguments.project_root, without_ignored(entries, patterns), load_copy_exclude(arguments.project_dir)
    )


def counted_entries(
    arguments: ProjectManagerArguments,
    entries: Dict[str, str],
    patterns: Optional[Sequence[str]] = None,
    left_out: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    """The ``entries`` of the project (:func:`source_entries`) that its builds depend on: without those the ignore
    patterns (``patterns``, by default the project's) leave out, and without those a copy of the project leaves out
    (``left_out``, by default :func:`left_out_of`): they are no input of a build."""
    if patterns is None:
        patterns = load_fingerprint_ignore(arguments.project_dir)
    if left_out is None:
        left_out = left_out_of(arguments, entries, patterns)
    return drop_below(without_ignored(entries, patterns), left_out)


def source_fingerprint(project_root: PATH, ignore: Sequence[str] = ()) -> str:
    """A hash over the path, size and modification time of the files below ``project_root``.

    In a git work tree these are the files git knows or does not ignore, so that build outputs (which a
    ``.gitignore`` lists) do not count; otherwise every file outside ``.discopop`` and ``.git``. Every file counts,
    not only the C/C++ sources: build files, headers and data can change what a compilation produces, and a build
    that is reused although it should not be would silently misreport a run. The price is a rebuild after a change
    that did not matter. A file that disappeared is part of the hash as such. Content is not hashed, so that the
    fingerprint of a large project takes seconds, not minutes.

    Files matching one of the ``ignore`` patterns (the project's ``fingerprint_ignore.json``) do not count.
    """
    return hash_of_entries(without_ignored(source_entries(project_root), ignore))


def _entries(root: PATH, names: Sequence[str]) -> Dict[str, str]:
    """``name -> "<size>\\0<mtime_ns>"`` (``missing`` for a file that disappeared) of the files ``names`` below
    ``root``."""
    entries: Dict[str, str] = {}
    for name in names:
        try:
            stat = os.lstat(os.path.join(root, name))
            entries[name] = str(stat.st_size) + "\0" + str(stat.st_mtime_ns)
        except OSError:
            entries[name] = "missing"
    return entries


def hash_of_entries(entries: Dict[str, str]) -> str:
    """The hash of :func:`_entries` (unchanged since the builds recorded only the hash, so their fingerprints stay
    valid)."""
    digest = hashlib.sha256()
    for entry in sorted(name + "\0" + value for name, value in entries.items()):
        digest.update(entry.encode("utf-8", errors="surrogateescape") + b"\n")
    return digest.hexdigest()


def _hash_entries(root: PATH, names: Sequence[str]) -> str:
    return hash_of_entries(_entries(root, names))


_RUN_ONLY_FILES = RUN_ONLY_FILES


def configuration_fingerprint(arguments: ProjectManagerArguments, key: BuildKey) -> str:
    """A hash over the files of the configuration directory that can change the build."""
    directory = os.path.join(arguments.project_config_dir, key.configuration)
    names = [name for name in _walk_files(directory) if os.path.basename(name) not in _RUN_ONLY_FILES]
    return _hash_entries(directory, names)


def _toolchain_fingerprint(settings_path: PATH) -> str:
    """A hash over what compiles the code: the installed profiler (its libraries and scripts) and the compilers.

    The version of the profiler package does not change when its pass or runtime is rebuilt locally, hence the
    files themselves count (path, size, modification time), and so do the compilers the settings and the
    environment name, which may be a different binary tomorrow.
    """
    digest = hashlib.sha256()
    try:
        from importlib.metadata import distribution

        files = distribution("discopop-profiler").files or []
        for entry in sorted(str(f) for f in files if str(f).endswith((".so", ".a", ".sh"))):
            path = str(distribution("discopop-profiler").locate_file(entry))
            digest.update(
                entry.encode() + b"\0" + _hash_entries(os.path.dirname(path), [os.path.basename(path)]).encode()
            )
    except Exception:
        digest.update(b"profiler unknown")
    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}
    for variable in ("CC", "CXX"):
        compiler = settings.get(variable) or os.environ.get(variable) or ""
        resolved = shutil.which(compiler) if compiler else None
        digest.update(variable.encode() + b"=" + compiler.encode())
        if resolved:
            digest.update(_hash_entries(os.path.dirname(resolved), [os.path.basename(resolved)]).encode())
    for variable in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS"):
        digest.update(variable.encode() + b"=" + os.environ.get(variable, "").encode() + b"\n")
    return digest.hexdigest()


def _patch_fingerprint(dot_dp: PATH) -> str:
    """A hash over the generated patches, which the suggestions of a build are applied from."""
    digest = hashlib.sha256()
    patch_dir = os.path.join(dot_dp, "patch_generator")
    for directory, subdirectories, files in os.walk(patch_dir):
        subdirectories.sort()
        for name in sorted(files):
            path = os.path.join(directory, name)
            digest.update(os.path.relpath(path, patch_dir).encode() + b"\0" + _hash_file(path).encode() + b"\n")
    return digest.hexdigest()


def compute_fingerprint_parts(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    compile_script: PATH,
    settings_path: PATH,
    pruning_environment: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """The parts the fingerprint of a build is made of; see :func:`compute_fingerprint`."""
    return compute_fingerprint(arguments, key, compile_script, settings_path, pruning_environment)[0]


def compute_fingerprint(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    compile_script: PATH,
    settings_path: PATH,
    pruning_environment: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """The parts the fingerprint of a build is made of, and the files of the project they were computed from
    (:func:`source_entries`, before the ignore patterns are applied, so that a pattern added later applies to
    the build as well).

    - the files of the project (path, size, modification time) without those the project's ignore patterns
      (``services/fingerprint_ignore.py``) or the copy (configured build directories, ``copy_exclude.json``) leave
      out (:func:`counted_entries`)
    - the paths of ``copy_exclude.json``, if it lists any
    - the compile script and the settings file of the mode (compiler, flags)
    - what is project code (included and excluded directories), as it decides what is instrumented, and the files
      of the included directories
    - for a ``dp`` build: whether and how it prunes its call path states, and the hotspot results it prunes with
      (``pruning_environment``, see :func:`callpath_pruning.environment`; computed if not given)
    - for a build with suggestions: the generated patches
    - the files of the configuration directory that can change the build (not execute.sh and validate.sh, which
      the runs take from the project)
    - the installed profiler and the compilers

    The thread count is no part of it: it only reaches the compilation as ``OMP_NUM_THREADS``, which a
    build script has no business to depend on.
    """
    directories = project_directories_of(
        arguments.project_dir, arguments.project_root, arguments.project_include_dirs, arguments.project_exclude_dirs
    )
    entries = source_entries(arguments.project_root)
    parts = {
        "sources": hash_of_entries(counted_entries(arguments, entries)),
        "compile_script": _hash_file(compile_script),
        "settings": _hash_file(settings_path),
        "project_directories": json.dumps(
            {"included": list(directories.included), "excluded": list(directories.excluded)}, sort_keys=True
        ),
        "configuration": configuration_fingerprint(arguments, key),
        "toolchain": _toolchain_fingerprint(settings_path),
    }
    if directories.included:
        # project code outside of the root is compiled as well
        parts["included_sources"] = "\n".join(source_fingerprint(d) for d in directories.included)
    if key.mode == "dp":
        if pruning_environment is None:
            pruning_environment = callpath_pruning.environment(arguments, key.configuration)
        parts["callpath_pruning"] = callpath_pruning.state_of(pruning_environment, arguments.dot_dp)
    if key.mode in ("dp", "hd"):
        # removed OpenMP flags change what the instrumented compilation produces (no part while they are kept)
        openmp_part = openmp_handling.fingerprint_part(arguments)
        if openmp_part is not None:
            parts["openmp"] = openmp_part
    if key.suggestions:
        parts["patches"] = _patch_fingerprint(arguments.dot_dp)
    copy_exclude = load_copy_exclude(arguments.project_dir)
    if copy_exclude:
        # what the copy leaves out (no part without a list, so that the builds before it stay current)
        parts["copy_exclude"] = json.dumps(copy_exclude)
    return parts, entries


def combine_fingerprint(parts: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _record_of(data: Dict[str, Any]) -> Optional[BuildRecord]:
    """The record of the manifest content ``data``; fields a later version may add are ignored."""
    if data.get("version") != MANIFEST_VERSION:
        return None
    known = {f.name for f in fields(BuildRecord)}
    return BuildRecord(**{name: value for name, value in data.items() if name in known})


def read_build(project_dir: PATH, key: BuildKey) -> Optional[BuildRecord]:
    """The manifest of the build ``key``, None if there is none or it cannot be read."""
    try:
        with open(manifest_path_of(project_dir, key), "r") as f:
            data: Dict[str, Any] = json.load(f)
        return _record_of(data)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def write_build(project_dir: PATH, record: BuildRecord, files: Optional[BuildFiles] = None) -> None:
    """Write the manifest of ``record`` and, if given, its :class:`BuildFiles` (before the manifest, so that a
    manifest never goes with the files of an older build)."""
    key = key_of(record)
    os.makedirs(builds_dir_of(project_dir), exist_ok=True)
    path = manifest_path_of(project_dir, key)
    with FileLock(path + ".lock"):
        if files is not None:
            files.fingerprint = record.fingerprint
            _write_build_files(project_dir, key, files)
        temporary = path + ".tmp"
        with open(temporary, "w") as f:
            json.dump(asdict(record), f, indent=4, sort_keys=True)
        os.replace(temporary, path)


def read_build_files(project_dir: PATH, key: BuildKey) -> Optional[BuildFiles]:
    """The :class:`BuildFiles` of the build ``key``; None for a build compiled before they were kept."""
    try:
        with open(build_files_path_of(project_dir, key), "r") as f:
            data = json.load(f)
        sources = data.get("sources")
        accepted = data.get("accepted", [])
        if not isinstance(sources, dict) or not isinstance(accepted, list):
            return None
        left_out = data.get("left_out", [])
        return BuildFiles(
            {str(k): str(v) for k, v in sources.items()},
            [a for a in accepted if isinstance(a, dict)],
            str(data.get("fingerprint", "")),
            [str(path) for path in left_out] if isinstance(left_out, list) else [],
        )
    except (OSError, ValueError, AttributeError):
        return None


def _write_build_files(project_dir: PATH, key: BuildKey, files: BuildFiles) -> None:
    path = build_files_path_of(project_dir, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as f:
        json.dump(asdict(files), f, sort_keys=True)
    os.replace(temporary, path)


def remove_build_files(project_dir: PATH, key: BuildKey) -> None:
    try:
        os.remove(build_files_path_of(project_dir, key))
    except OSError:
        pass


def list_builds(project_dir: PATH) -> List[BuildRecord]:
    """All builds with a readable manifest, sorted by their id."""
    records: List[BuildRecord] = []
    directory = builds_dir_of(project_dir)
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), "r") as f:
                data = json.load(f)
            record = _record_of(data)
            if record is not None:
                records.append(record)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return records


def _file_changes(record: BuildRecord, recorded: Optional[Dict[str, str]], current: Dict[str, str]) -> FileChanges:
    """The files that differ between the recorded and the current entries (both without the ignored files). Without
    recorded entries (an older build), the files modified after the build are the best guess."""
    if recorded is None:
        built_ns = int(record.built_at * 1e9)
        newer = []
        for name, value in current.items():
            size_and_time = value.split("\0")
            if len(size_and_time) == 2 and size_and_time[1].isdigit() and int(size_and_time[1]) > built_ns:
                newer.append(name)
        # not filtered by the ignore patterns: the recorded hash covers these files whatever the patterns say
        return FileChanges(modified=tuple(sorted(newer)), approximate=True)
    return FileChanges(
        added=tuple(sorted(name for name in current if name not in recorded)),
        removed=tuple(sorted(name for name in recorded if name not in current)),
        modified=tuple(sorted(name for name in current if name in recorded and current[name] != recorded[name])),
    )


def _top_level_counts(paths: Sequence[str]) -> List[Tuple[str, int]]:
    """How many of ``paths`` lie below each top-level directory (``dir/``) or are top-level files, most first."""
    counts: Dict[str, int] = {}
    for path in paths:
        head, separator, _rest = path.partition("/")
        group = head + "/" if separator else head
        counts[group] = counts.get(group, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


NO_FILE_LIST_NOTE = (
    "The build keeps no list of its files (compiled by an older version): ignore patterns cannot leave out files "
    "it was compiled with until it was accepted or compiled again."
)


def describe_file_changes(files: FileChanges, limit: int = 4) -> str:
    """One sentence about the changed files, e.g. ``742 files changed (700 modified, 42 added): dp_build/ (742).``"""
    if not files:
        if files.approximate:
            return "No file is newer than the build (files may have been added or removed). " + NO_FILE_LIST_NOTE
        return "No file changed (the ignore patterns may have changed)."
    kinds = [
        str(len(group)) + " " + name
        for group, name in ((files.modified, "modified"), (files.added, "added"), (files.removed, "removed"))
        if group
    ]
    groups = _top_level_counts(files.paths)
    where = ", ".join(group + " (" + str(count) + ")" for group, count in groups[:limit])
    if len(groups) > limit:
        where += ", ..."
    text = str(len(files)) + (" file changed" if len(files) == 1 else " files changed")
    if files.approximate:
        text = str(len(files)) + (" file is" if len(files) == 1 else " files are") + " newer than the build"
    else:
        text += " (" + ", ".join(kinds) + ")"
    text += ": " + where + "."
    if files.approximate:
        text += " " + NO_FILE_LIST_NOTE
    return text


def describe_changes(changes: BuildChanges) -> str:
    """The reason of a stale build: "Changed since the build: <parts>." and what is known about why."""
    text = "Changed since the build: " + ", ".join(changes.parts) + "."
    if changes.files is not None:
        text += " " + describe_file_changes(changes.files)
    for part, cause in changes.causes:
        text += " " + part + ": " + cause + "."
    return text


def _tree_holds_other_code(arguments: ProjectManagerArguments, key: BuildKey, record: BuildRecord) -> Optional[str]:
    """Why the kept tree of ``record`` does not hold the build ``key`` any more (None if it does, or if the build has
    a tree of its own)."""
    if not _same_path(record.tree, kept_tree_path_of(arguments.project_root, key)):
        return None
    state = read_tree_state(arguments.project_dir, tree_key(key).build_id)
    if state is None:
        return None  # compiled before trees were kept
    if state.state != CLEAN:
        return "its tree was changed after the compilation (" + state.state + ")"
    if sorted(state.applied) != sorted(key.suggestions):
        if state.applied:
            return "its tree holds the build with the suggestions " + ", ".join(state.applied) + " now"
        return "its tree holds the build without suggestions now"
    return None


def build_status(
    arguments: ProjectManagerArguments, key: BuildKey, compile_script: PATH, settings_path: PATH
) -> BuildStatus:
    """Whether the build ``key`` can serve a run, and if not, why (:attr:`BuildStatus.changes`).

    The parts of the fingerprint are compared one by one. The files of the project are compared with the ignore
    patterns of now applied to both sides, so that a pattern added after the build (``services/fingerprint_ignore``)
    applies to it as well.
    """
    record = read_build(arguments.project_dir, key)
    if record is None:
        return BuildStatus(BuildState.NONE, "No build yet.")
    if not os.path.isdir(record.tree):
        return BuildStatus(BuildState.NONE, "The build tree " + record.tree + " does not exist any more.", record)
    tree_cause = _tree_holds_other_code(arguments, key, record)
    if tree_cause is not None:
        changes = BuildChanges((TREE_PART,), causes=((TREE_PART, tree_cause),))
        return BuildStatus(BuildState.STALE, describe_changes(changes), record, changes)
    parts, entries = compute_fingerprint(arguments, key, compile_script, settings_path)
    patterns = load_fingerprint_ignore(arguments.project_dir)
    recorded_parts = dict(record.fingerprint_parts)
    stored = read_build_files(arguments.project_dir, key)
    recorded_sources: Optional[Dict[str, str]] = None
    current_left_out = left_out_of(arguments, entries, patterns)
    if stored is not None and stored.fingerprint == record.fingerprint and "sources" in recorded_parts:
        # what the copy leaves out now, and what it left out then (a build directory deleted since the build does
        # not count as removed files; one that turned into sources counts as added)
        recorded_left_out = set(current_left_out) | set(stored.left_out)
        if not stored.left_out:
            # a file list written before the paths were kept: classify its names by the project of now
            recorded_left_out |= set(left_out_of(arguments, stored.sources, patterns))
        recorded_sources = counted_entries(arguments, stored.sources, patterns, sorted(recorded_left_out))
        recorded_parts["sources"] = hash_of_entries(recorded_sources)
    changed = tuple(
        sorted(name for name in set(parts) | set(recorded_parts) if parts.get(name) != recorded_parts.get(name))
    )
    if not changed:
        return BuildStatus(BuildState.CURRENT, "", record)
    files = (
        _file_changes(
            record,
            recorded_sources,
            # without a recorded file list, the recorded hash covered every file: name them all
            (
                counted_entries(arguments, entries, patterns, current_left_out)
                if recorded_sources is not None
                else entries
            ),
        )
        if "sources" in changed
        else None
    )
    causes: List[Tuple[str, str]] = []
    if "callpath_pruning" in changed and "callpath_pruning" in recorded_parts and "callpath_pruning" in parts:
        cause = callpath_pruning.change_cause(
            arguments, key.configuration, recorded_parts["callpath_pruning"], parts["callpath_pruning"]
        )
        if cause:
            causes.append(("callpath_pruning", cause))
    if "openmp" in changed:
        causes.append(
            (
                "openmp",
                "the OpenMP flags are now "
                + ("removed" if "openmp" in parts else "kept")
                + " by the instrumented compilation",
            )
        )
    changes = BuildChanges(changed, files, tuple(causes))
    return BuildStatus(BuildState.STALE, describe_changes(changes), record, changes)


def make_record(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    compile_script: PATH,
    settings_path: PATH,
    tree: PATH,
    compile_seconds: float,
    parts: Optional[Dict[str, str]] = None,
) -> BuildRecord:
    if parts is None:
        parts = compute_fingerprint_parts(arguments, key, compile_script, settings_path)
    return BuildRecord(
        build_id=key.build_id,
        configuration=key.configuration,
        mode=key.mode,
        suggestions=list(key.suggestions),
        fingerprint=combine_fingerprint(parts),
        tree=tree,
        built_at=time.time(),
        compile_seconds=compile_seconds,
        compile_script=os.path.abspath(compile_script),
        fingerprint_parts=parts,
        role=key.role,
    )


# the changed files an accepted change keeps in its note, by name (the counts are always kept)
_ACCEPTED_FILES_KEPT = 200


def accept_build(
    arguments: ProjectManagerArguments, key: BuildKey, compile_script: PATH, settings_path: PATH
) -> BuildStatus:
    """Declare the stale build ``key`` current: the user saw what changed (:attr:`BuildStatus.changes`) and decided
    that it does not matter for the build. Its fingerprint becomes that of the project now; the accepted change is
    noted in its :class:`BuildFiles` (when, which parts, which files) and named whenever the build is reused.

    Nothing is compiled: runs of the build use the code it was compiled from. For a ``dp`` build this includes the
    call path pruning it was compiled with, even if the current setting would prune differently.

    A change of the call path pruning cannot be accepted (:class:`BuildAcceptError`): the tree stays pruned as it
    was compiled, and its profiling data would claim the pruning of now. If it follows from outdated hotspot results
    (their ``hd`` build is stale), accepting or rebuilding that build first resolves it.

    Returns the status before the acceptance (CURRENT: nothing to accept, NONE: no build). Raises
    :class:`BuildInUseError` while a run or a compilation holds the build.
    """
    lock = FileLock(build_lock_path_of(arguments.project_dir, key))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise BuildInUseError(key.build_id)
    try:
        status = build_status(arguments, key, compile_script, settings_path)
        if status.state != BuildState.STALE or status.record is None or status.changes is None:
            return status
        if "callpath_pruning" in status.changes.parts:
            # the tree was pruned as recorded; accepting would make its data claim another pruning
            cause = dict(status.changes.causes).get("callpath_pruning", "")
            raise BuildAcceptError(
                "The call path pruning a compilation would use now differs from the one the build was compiled with"
                + (" (" + cause + ")" if cause else "")
                + ". Accepting cannot change how its code is pruned: compile it again"
                + (", or first accept or rebuild the hd build named above" if "_hd is stale" in cause else "")
                + "."
            )
        if TREE_PART in status.changes.parts:
            raise BuildAcceptError(
                "The build tree holds the code of another build now (other suggestions, or an interrupted "
                "compilation). Accepting cannot change that: compile it again."
            )
        if "openmp" in status.changes.parts:
            # the tree was compiled with or without the OpenMP flags; accepting would make its data claim the other
            raise BuildAcceptError(
                "The OpenMP flags would be handled differently by a compilation now (see Project Setup). Accepting "
                "cannot change how the tree was compiled: compile it again."
            )
        parts, entries = compute_fingerprint(arguments, key, compile_script, settings_path)
        files = read_build_files(arguments.project_dir, key) or BuildFiles()
        changed_files = status.changes.files
        note: Dict[str, Any] = {
            "at": time.time(),
            "parts": list(status.changes.parts),
            "reason": status.reason,
        }
        if changed_files is not None:
            note["file_count"] = len(changed_files)
            note["files"] = list(changed_files.paths[:_ACCEPTED_FILES_KEPT])
        files.sources = entries
        files.left_out = left_out_of(arguments, entries)
        files.accepted.append(note)
        record = status.record
        record.fingerprint_parts = parts
        record.fingerprint = combine_fingerprint(parts)
        write_build(arguments.project_dir, record, files)
        logger.info("accepted the changes of the build " + key.build_id + ": " + status.reason)
        return status
    finally:
        lock.release()


def accepted_changes_text(project_dir: PATH, key: BuildKey) -> str:
    """Empty, or a note that changes of the project were accepted for the build ``key`` (shown when it is reused)."""
    files = read_build_files(project_dir, key)
    if files is None or not files.accepted:
        return ""
    last = files.accepted[-1]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(last.get("at", 0))))
    count = len(files.accepted)
    return (
        "Changes of the project since its compilation were accepted for this build by the user"
        + (" (" + str(count) + " times, last " if count > 1 else " (")
        + when
        + "): "
        + ", ".join(str(part) for part in last.get("parts", []))
        + "."
    )


def invalidate_build(project_dir: PATH, key: BuildKey) -> None:
    """Forget the manifest of the build ``key``, so that the next run compiles. For a tree that was changed after
    its compilation (e.g. by the separate build of a validation), which the fingerprint cannot see. Its tree is
    copied anew by the next build (``configurations/tree_sync.py``)."""
    try:
        os.remove(manifest_path_of(project_dir, key))
    except OSError:
        pass
    remove_build_files(project_dir, key)
    set_tree_state(project_dir, tree_key(key).build_id, DIRTY)


def forget_build(project_dir: PATH, key: BuildKey) -> None:
    """Remove the manifest of the build ``key`` but not its tree: another build was compiled into it."""
    try:
        os.remove(manifest_path_of(project_dir, key))
    except OSError:
        pass
    remove_build_files(project_dir, key)


class BuildAcceptError(Exception):
    """The changes since a build cannot be accepted (the message says why)."""


class BuildInUseError(Exception):
    """The build is used by a run (or is being compiled) and cannot be deleted."""


def delete_build(arguments: ProjectManagerArguments, key: BuildKey) -> bool:
    """Delete the manifest and the tree of the build ``key``; True if there was a build."""
    record = read_build(arguments.project_dir, key)
    manifest = manifest_path_of(arguments.project_dir, key)
    existed = record is not None or os.path.exists(manifest)
    lock = FileLock(build_lock_path_of(arguments.project_dir, key))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise BuildInUseError(key.build_id)
    try:
        _delete_build_locked(arguments, key, record, manifest)
    finally:
        lock.release()
    return existed


def _delete_build_locked(
    arguments: ProjectManagerArguments, key: BuildKey, record: Optional[BuildRecord], manifest: PATH
) -> None:
    if record is not None:
        tree = os.path.abspath(record.tree)
        # only what lives in the directory of the build trees is ever removed
        trees_dir = os.path.abspath(build_trees_dir_of(arguments.project_root))
        if os.path.commonpath([tree, trees_dir]) == trees_dir and tree != trees_dir and os.path.isdir(tree):
            shutil.rmtree(tree)
            logger.info("removed build tree: " + tree)
        else:
            logger.warning("not removing " + tree + ": it is no build tree of this project")
    for path in (manifest, manifest + ".lock", manifest + ".build.lock"):
        try:
            os.remove(path)
        except OSError:
            pass
    remove_build_files(arguments.project_dir, key)
    if record is not None and _same_path(record.tree, kept_tree_path_of(arguments.project_root, key)):
        remove_tree_state(arguments.project_dir, tree_key(key).build_id)


def delete_builds(arguments: ProjectManagerArguments, build_ids: Optional[Sequence[str]] = None) -> List[str]:
    """Delete the builds with the given ids, all of them if ``build_ids`` is None. Returns the deleted ids."""
    deleted: List[str] = []
    for record in list_builds(arguments.project_dir):
        if build_ids is not None and record.build_id not in build_ids:
            continue
        key = key_of(record)
        try:
            if delete_build(arguments, key):
                deleted.append(record.build_id)
        except BuildInUseError:
            logger.warning("not deleting the build " + record.build_id + ": a run is using it")
    return deleted
