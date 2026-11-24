# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Bringing a kept build tree up to date with the project, instead of copying the project again.

A build tree is a copy of the project (``configurations/copying.py``) that a compilation added its outputs to.
To compile the project again *incrementally* in it, the tree must hold the files of the project as they are now
(with the patches of the applied suggestions), while the outputs of the earlier compilation stay. :func:`sync_tree`
does that:

- it writes a file only if its content differs from the one in the tree, and gives it the current time as
  modification time. A build system decides by modification times what to compile again, so an unchanged file
  must not be touched, and a changed one must look newer than the outputs made from it (a copy that kept the
  project's older modification time would not be compiled again).
- it deletes the files it wrote before that the project does not have any more, and nothing else: the outputs of
  the compilations stay.
- it takes the patched files (``overrides``) instead of the project's, so that dropping a suggestion writes the
  original back.

What a tree was synced from is kept in a state file of its own (:class:`TreeState`, in
``.discopop/project/builds/trees/<build id>.json``), apart from the build's fingerprint (accepting a stale build
changes its fingerprint, not the tree). A sync marks the state ``syncing`` while it writes; a tree with no state
or an interrupted sync is copied anew. One whose outputs are unknown (an interrupted or failed compilation, a
validation build in it) is synced, but compiled in full.

The files of the tree are those a copy would hold (:func:`copy_set`): every file below the project root except
``.discopop`` and what the copy leaves out (``configurations/copy_exclusions.py``). ``.discopop`` is the caller's.

Toolkit-free.
"""

import filecmp
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Set

from discopop_library.ProjectManager.configurations.copy_exclusions import CopyExclusions

PATH = str

# the states of a tree (TreeState.state)
CLEAN = "clean"  # holds what ``synced`` says and the outputs of a successful compilation
SYNCING = "syncing"  # a sync was writing into it; what it holds is unknown: copied anew
BUILDING = "building"  # its files are as ``synced`` says, the outputs unknown (a compilation was running)
DIRTY = "dirty"  # its files are as ``synced`` says, the outputs unknown (failed compilation, validation build)

_TEMPORARY_SUFFIX = ".dp_sync_tmp"
_PATCHED = "patched:"


@dataclass
class TreeState:
    """What a kept build tree holds."""

    # relative path -> signature (:func:`signature_of`) of the file the tree got, and of that file in the tree
    synced: Dict[str, str] = field(default_factory=dict)
    # the suggestions applied to the files of the tree
    applied: List[str] = field(default_factory=list)
    state: str = CLEAN
    # environment_fingerprint (builds.py) of the last successful compilation in the tree: only a tree compiled in
    # the same environment can be compiled again incrementally
    environment: str = ""


def tree_states_dir_of(project_dir: PATH) -> PATH:
    return os.path.join(project_dir, "builds", "trees")


def tree_state_path_of(project_dir: PATH, build_id: str) -> PATH:
    return os.path.join(tree_states_dir_of(project_dir), build_id + ".json")


def read_tree_state(project_dir: PATH, build_id: str) -> Optional[TreeState]:
    """The state of the tree of ``build_id``; None if there is none or it cannot be read (the tree is copied anew)."""
    try:
        with open(tree_state_path_of(project_dir, build_id), "r") as file:
            data = json.load(file)
        synced = data.get("synced")
        applied = data.get("applied", [])
        state = data.get("state")
        if not isinstance(synced, dict) or not isinstance(applied, list) or not isinstance(state, str):
            return None
        environment = data.get("environment", "")
        return TreeState(
            {str(k): str(v) for k, v in synced.items()},
            [str(a) for a in applied],
            state,
            environment if isinstance(environment, str) else "",
        )
    except (OSError, ValueError, AttributeError):
        return None


def write_tree_state(project_dir: PATH, build_id: str, state: TreeState) -> None:
    path = tree_state_path_of(project_dir, build_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump(asdict(state), file, sort_keys=True)
    os.replace(temporary, path)


def set_tree_state(project_dir: PATH, build_id: str, state: str) -> None:
    """Change only the ``state`` of the tree of ``build_id`` (nothing if it has no state file)."""
    current = read_tree_state(project_dir, build_id)
    if current is not None:
        current.state = state
        write_tree_state(project_dir, build_id, current)


def remove_tree_state(project_dir: PATH, build_id: str) -> None:
    try:
        os.remove(tree_state_path_of(project_dir, build_id))
    except OSError:
        pass


def copy_set(exclusions: CopyExclusions, directories: Optional[Set[str]] = None) -> Dict[str, PATH]:
    """The files a copy of ``exclusions.root`` holds outside of ``.discopop`` (relative path -> path in the project),
    as :func:`shutil.copytree` with ``exclusions.ignore()`` copies them: links are followed, dangling links skipped.
    ``directories``, if given, receives the directories of the copy (relative paths), empty ones included.
    """
    root = os.path.abspath(exclusions.root)
    ignore = exclusions.ignore()
    files: Dict[str, PATH] = {}
    for directory, subdirectories, names in os.walk(root, followlinks=True):
        left_out = set(ignore(directory, sorted(subdirectories + names)))
        if directory == root:
            left_out.add(".discopop")
        subdirectories[:] = [name for name in subdirectories if name not in left_out]
        relative_dir = os.path.relpath(directory, root)
        prefix = "" if relative_dir == "." else relative_dir.replace(os.sep, "/") + "/"
        if directories is not None:
            directories.update(prefix + name for name in subdirectories)
        for name in names:
            path = os.path.join(directory, name)
            if name in left_out or not os.path.exists(path):  # dangling link
                continue
            files[prefix + name] = path
    return files


def signature_of(path: PATH, patched: bool = False) -> str:
    """What tells whether the file at ``path`` changed: size, modification time and permissions (of the target of a
    link), or, for a patched file (whose modification time is that of its patching), its content and permissions."""
    try:
        stat = os.stat(path)
    except OSError:
        return "missing"
    mode = oct(stat.st_mode & 0o7777)
    if patched:
        return _PATCHED + _content_hash(path) + "\0" + mode
    return str(stat.st_size) + "\0" + str(stat.st_mtime_ns) + "\0" + mode


def _content_hash(path: PATH) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return "missing"
    return digest.hexdigest()


def signatures_of(files: Mapping[str, PATH], overrides: Mapping[str, PATH]) -> Dict[str, str]:
    """The signatures of the files a tree is to hold: those of ``files``, a patched file of ``overrides`` instead
    of the project's."""
    result = {name: signature_of(path) for name, path in files.items() if name not in overrides}
    result.update({name: signature_of(path, patched=True) for name, path in overrides.items()})
    return result


@dataclass
class SyncResult:
    # files whose content changed and that were written (relative paths, sorted)
    written: List[str] = field(default_factory=list)
    # files that were deleted, as the project does not have them any more
    deleted: List[str] = field(default_factory=list)
    # files of the project that a compilation changed in the tree and that were left as they are (keep_outputs)
    kept_outputs: List[str] = field(default_factory=list)
    # what the tree holds now (TreeState.synced)
    synced: Dict[str, str] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.written or self.deleted)


def sync_tree(
    tree: PATH,
    files: Mapping[str, PATH],
    previous: Mapping[str, str],
    overrides: Optional[Mapping[str, PATH]] = None,
    directories: Iterable[str] = (),
    preserve_times: bool = False,
    keep_outputs: bool = False,
) -> SyncResult:
    """Make the files of ``tree`` those of ``files`` (relative path -> source; a patched file of ``overrides``
    instead), knowing that it was synced to the signatures ``previous`` before. See the module docstring.

    A file whose signature is unchanged, in the project and in the tree, is not read. One whose signature changed is
    compared by content with the file in the tree and written only if it differs (a ``touch`` or a checkout of the
    same content does not cause a compilation). Raises :class:`OSError` if a file cannot be written; the caller
    marks the tree to be copied anew.
    """
    overrides = dict(overrides or {})
    sources = dict(files)
    sources.update(overrides)
    wanted = signatures_of(files, overrides)
    result = SyncResult()
    for name in sorted(sources):
        destination = os.path.join(tree, name)
        # unchanged in the project, and in the tree as the sync left it (a compilation may change a file of the
        # project in the tree, e.g. a configure step writing into the sources)
        if previous.get(name) == _entry(wanted[name], destination):
            result.synced[name] = previous[name]
            continue
        if keep_outputs and name not in overrides and _changed_in_tree(previous.get(name), destination):
            # the build changed this file of the project in the tree: an output (e.g. an object file of a build in
            # the project directory). Restoring the project's version would give it a new modification time and
            # make the build system take it for current. Recorded as before, so a full build restores it.
            result.synced[name] = previous[name]  # type: ignore[assignment]
            result.kept_outputs.append(name)
            continue
        if not _same_content(sources[name], destination):
            _write(sources[name], destination, preserve_times)
            result.written.append(name)
        elif _mode_of(sources[name]) != _mode_of(destination):
            shutil.copymode(sources[name], destination)
        result.synced[name] = _entry(wanted[name], destination)
    for name in sorted(set(previous) - set(sources)):
        destination = os.path.join(tree, name)
        if os.path.lexists(destination) and not os.path.isdir(destination):
            os.remove(destination)
            result.deleted.append(name)
    for name in sorted(directories):
        destination = os.path.join(tree, name)
        if not os.path.isdir(destination):
            _make_parent(os.path.join(destination, "x"))
    return result


def _mode_of(path: PATH) -> int:
    try:
        return os.stat(path).st_mode & 0o7777
    except OSError:
        return -1


def _changed_in_tree(previous: Optional[str], destination: PATH) -> bool:
    """Whether the file at ``destination`` differs from what the sync recorded for it (``previous``)."""
    if previous is None or "|" not in previous:
        return False
    recorded = previous.rsplit("|", 1)[1]
    return recorded != "missing" and (signature_of(destination) if _is_file(destination) else "missing") != recorded


def _entry(wanted: str, destination: PATH) -> str:
    """The entry of :attr:`TreeState.synced`: the signature of the source and that of the file in the tree."""
    return wanted + "|" + (signature_of(destination) if _is_file(destination) else "missing")


def clean_outputs(
    tree: PATH, synced: Mapping[str, str], project_root: PATH, directories: Optional[Set[str]] = None
) -> List[str]:
    """Delete everything in ``tree`` outside of ``.discopop`` that is no file of the project (``synced``): the
    outputs of earlier compilations, so that a compile script runs as in a fresh copy. An empty directory is kept
    only if it is one of the ``directories`` of the copy (by default: if the project has it empty as well).
    Returns the deleted files (relative paths)."""
    tree = os.path.abspath(tree)
    deleted: List[str] = []
    for directory, subdirectories, names in os.walk(tree, topdown=True):
        relative_dir = os.path.relpath(directory, tree)
        prefix = "" if relative_dir == "." else relative_dir.replace(os.sep, "/") + "/"
        if not prefix:
            subdirectories[:] = [name for name in subdirectories if name != ".discopop"]
        for name in names + [d for d in subdirectories if os.path.islink(os.path.join(directory, d))]:
            if prefix + name not in synced:
                os.remove(os.path.join(directory, name))
                deleted.append(prefix + name)
    # empty directories, deepest first
    for directory, subdirectories, names in os.walk(tree, topdown=False):
        relative = os.path.relpath(directory, tree)
        if relative == "." or relative.split(os.sep, 1)[0] == ".discopop":
            continue
        keep = (
            relative.replace(os.sep, "/") in directories
            if directories is not None
            else _empty_directory(os.path.join(project_root, relative))
        )
        if not os.listdir(directory) and not keep:
            os.rmdir(directory)
    return deleted


def _empty_directory(path: PATH) -> bool:
    try:
        return os.path.isdir(path) and not os.listdir(path)
    except OSError:
        return False


def _is_file(path: PATH) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def _same_content(source: PATH, destination: PATH) -> bool:
    if not _is_file(destination):
        return False
    try:
        return os.path.getsize(source) == os.path.getsize(destination) and filecmp.cmp(
            source, destination, shallow=False
        )
    except OSError:
        return False


def _make_parent(destination: PATH) -> None:
    """Create the directory of ``destination``; a file in the way (a directory of the project that was a file
    when the tree was synced) is removed."""
    parent = os.path.dirname(destination)
    if os.path.isdir(parent):
        return
    if os.path.lexists(parent):
        os.remove(parent)
    _make_parent(parent)
    os.mkdir(parent)


def _write(source: PATH, destination: PATH, preserve_times: bool = False) -> None:
    """Copy ``source`` to ``destination`` with the current time as modification time (``preserve_times``: that of
    ``source``), replacing the file at once (a compilation never reads half of it)."""
    _make_parent(destination)
    if os.path.isdir(destination) and not os.path.islink(destination):
        # a file of the project that was a directory when the tree was synced
        shutil.rmtree(destination)
    temporary = destination + _TEMPORARY_SUFFIX
    shutil.copyfile(source, temporary)
    if preserve_times:
        shutil.copystat(source, temporary)
    else:
        shutil.copymode(source, temporary)
    os.replace(temporary, destination)
