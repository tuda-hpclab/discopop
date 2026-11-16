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
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from filelock import FileLock, Timeout

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.project_environment import project_directories_of

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

    @property
    def build_id(self) -> str:
        build_id = self.configuration + "_" + self.mode
        if self.suggestions:
            digest = hashlib.sha1(",".join(sorted(self.suggestions)).encode()).hexdigest()[:8]
            build_id += "_s" + digest
        return build_id


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


@dataclass(frozen=True)
class BuildStatus:
    state: BuildState
    reason: str
    record: Optional[BuildRecord] = None

    @property
    def usable(self) -> bool:
        return self.state == BuildState.CURRENT


def builds_dir_of(project_dir: PATH) -> PATH:
    """The directory of the build manifests (``.discopop/project/builds``)."""
    return os.path.join(project_dir, "builds")


def manifest_path_of(project_dir: PATH, key: BuildKey) -> PATH:
    return os.path.join(builds_dir_of(project_dir), key.build_id + ".json")


def build_trees_dir_of(project_root: PATH) -> PATH:
    """The directory holding the build trees: next to the project, like every project copy."""
    root = os.path.abspath(project_root)
    return os.path.join(str(Path(root).parent), os.path.basename(root) + "_discopop_builds")


def build_tree_path_of(project_root: PATH, key: BuildKey) -> PATH:
    return os.path.join(build_trees_dir_of(project_root), key.build_id)


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


def source_fingerprint(project_root: PATH) -> str:
    """A hash over the path, size and modification time of the files below ``project_root``.

    In a git work tree these are the files git knows or does not ignore, so that build outputs (which a
    ``.gitignore`` lists) do not count; otherwise every file outside ``.discopop`` and ``.git``. Every file counts,
    not only the C/C++ sources: build files, headers and data can change what a compilation produces, and a build
    that is reused although it should not be would silently misreport a run. The price is a rebuild after a change
    that did not matter. A file that disappeared is part of the hash as such. Content is not hashed, so that the
    fingerprint of a large project takes seconds, not minutes.
    """
    root = os.path.abspath(project_root)
    names = _git_files(root)
    if names is None:
        names = _walk_files(root)
    else:
        names = [name for name in names if name.split("/", 1)[0] not in _FINGERPRINT_PRUNED_DIRS]
    return _hash_entries(root, names)


def _hash_entries(root: PATH, names: Sequence[str]) -> str:
    digest = hashlib.sha256()
    entries: List[str] = []
    for name in names:
        try:
            stat = os.lstat(os.path.join(root, name))
            entries.append(name + "\0" + str(stat.st_size) + "\0" + str(stat.st_mtime_ns))
        except OSError:
            entries.append(name + "\0missing")
    for entry in sorted(entries):
        digest.update(entry.encode("utf-8", errors="surrogateescape") + b"\n")
    return digest.hexdigest()


# the files of a configuration directory that only the runs read; everything else (helper files of compile.sh, ...)
# can change the build
_RUN_ONLY_FILES = ("execute.sh", "validate.sh", "execution_time.json")


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
    arguments: ProjectManagerArguments, key: BuildKey, compile_script: PATH, settings_path: PATH
) -> Dict[str, str]:
    """The parts the fingerprint of a build is made of.

    - the files of the project (path, size, modification time)
    - the compile script and the settings file of the mode (compiler, flags)
    - what is project code (included and excluded directories), as it decides what is instrumented, and the files
      of the included directories
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
    parts = {
        "sources": source_fingerprint(arguments.project_root),
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
    if key.suggestions:
        parts["patches"] = _patch_fingerprint(arguments.dot_dp)
    return parts


def combine_fingerprint(parts: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def read_build(project_dir: PATH, key: BuildKey) -> Optional[BuildRecord]:
    """The manifest of the build ``key``, None if there is none or it cannot be read."""
    try:
        with open(manifest_path_of(project_dir, key), "r") as f:
            data: Dict[str, Any] = json.load(f)
        if data.get("version") != MANIFEST_VERSION:
            return None
        return BuildRecord(**data)
    except (OSError, ValueError, TypeError):
        return None


def write_build(project_dir: PATH, record: BuildRecord) -> None:
    key = BuildKey(record.configuration, record.mode, tuple(record.suggestions))
    os.makedirs(builds_dir_of(project_dir), exist_ok=True)
    path = manifest_path_of(project_dir, key)
    with FileLock(path + ".lock"):
        temporary = path + ".tmp"
        with open(temporary, "w") as f:
            json.dump(asdict(record), f, indent=4, sort_keys=True)
        os.replace(temporary, path)


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
            if data.get("version") == MANIFEST_VERSION:
                records.append(BuildRecord(**data))
        except (OSError, ValueError, TypeError):
            continue
    return records


def build_status(
    arguments: ProjectManagerArguments, key: BuildKey, compile_script: PATH, settings_path: PATH
) -> BuildStatus:
    """Whether the build ``key`` can serve a run, and if not, why."""
    record = read_build(arguments.project_dir, key)
    if record is None:
        return BuildStatus(BuildState.NONE, "No build yet.")
    if not os.path.isdir(record.tree):
        return BuildStatus(BuildState.NONE, "The build tree " + record.tree + " does not exist any more.", record)
    parts = compute_fingerprint_parts(arguments, key, compile_script, settings_path)
    if combine_fingerprint(parts) == record.fingerprint:
        return BuildStatus(BuildState.CURRENT, "", record)
    changed = sorted(name for name in parts if parts[name] != record.fingerprint_parts.get(name))
    return BuildStatus(BuildState.STALE, "Changed since the build: " + ", ".join(changed) + ".", record)


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
    )


def invalidate_build(project_dir: PATH, key: BuildKey) -> None:
    """Forget the manifest of the build ``key``, so that the next run compiles. For a tree that was changed after
    its compilation (e.g. by the separate build of a validation), which the fingerprint cannot see."""
    try:
        os.remove(manifest_path_of(project_dir, key))
    except OSError:
        pass


class BuildInUseError(Exception):
    """The build is used by a run (or is being compiled) and cannot be deleted."""


def delete_build(arguments: ProjectManagerArguments, key: BuildKey) -> bool:
    """Delete the manifest and the tree of the build ``key``; True if there was a build."""
    record = read_build(arguments.project_dir, key)
    manifest = manifest_path_of(arguments.project_dir, key)
    existed = record is not None or os.path.exists(manifest)
    lock = FileLock(manifest + ".build.lock")
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


def delete_builds(arguments: ProjectManagerArguments, build_ids: Optional[Sequence[str]] = None) -> List[str]:
    """Delete the builds with the given ids, all of them if ``build_ids`` is None. Returns the deleted ids."""
    deleted: List[str] = []
    for record in list_builds(arguments.project_dir):
        if build_ids is not None and record.build_id not in build_ids:
            continue
        key = BuildKey(record.configuration, record.mode, tuple(record.suggestions))
        try:
            if delete_build(arguments, key):
                deleted.append(record.build_id)
        except BuildInUseError:
            logger.warning("not deleting the build " + record.build_id + ": a run is using it")
    return deleted
