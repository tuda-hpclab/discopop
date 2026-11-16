# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The directories of the project that are no project code, e.g. dependencies fetched into ``build/_deps``.

The profiler counts every file below the project directory (``DP_PROJECT_ROOT_DIR``) and the included directories
(``services/included_directories.py``) as project code: it instruments it, maps it in ``FileMapping.txt``, and the AST
export keeps its declarations. For a library fetched into the build directory that costs profiling time and, for
template libraries, gigabytes of AST per translation unit. The directories listed here are left out by all of them: the
project manager passes them to every build as ``DP_PROJECT_EXCLUDE_DIRS`` (``:`` separated, as absolute paths in the
copy of the project a configuration is built in).

Stored in ``.discopop/project/excluded_directories.json`` (kept by "Reset Project", like the configurations), as
paths relative to the project directory with ``/`` as separator. A directory excludes everything below it, so the list
never holds a directory below another one in it. Toolkit-free: the Qt GUI shows it as a folder tree.
"""

import json
import os
import posixpath
from typing import List, Optional, Sequence

EXCLUDED_DIRECTORIES_FILE = "excluded_directories.json"
ENVIRONMENT_VARIABLE = "DP_PROJECT_EXCLUDE_DIRS"
# never project code (and the place of the results), or not code at all
HIDDEN_DIRECTORY_NAMES = (".discopop", ".git")


def excluded_directories_path(project_dir: str) -> str:
    """The file of the list; ``project_dir`` is ``.discopop/project`` (``ProjectManagerArguments.project_dir``)."""
    return os.path.join(project_dir, EXCLUDED_DIRECTORIES_FILE)


def normalize(relative: str) -> Optional[str]:
    """``relative`` as stored: ``/`` separated, without ``.`` segments and trailing ``/``; None if it names no
    directory below the project directory (empty, the project directory itself, absolute, or leaving it)."""
    path = posixpath.normpath(relative.replace(os.sep, "/").strip())
    if path in ("", ".") or path.startswith("/") or path == ".." or path.startswith("../"):
        return None
    return path


def _is_below(path: str, directory: str) -> bool:
    """Whether ``path`` is ``directory`` or lies in it (both normalized)."""
    return path == directory or path.startswith(directory + "/")


def minimal(directories: Sequence[str]) -> List[str]:
    """``directories`` normalized and sorted, without duplicates and without those below another one of them."""
    normalized = sorted({path for path in map(normalize, directories) if path is not None})
    return [path for path in normalized if not any(_is_below(path, other) for other in normalized if other != path)]


def load_excluded_directories(project_dir: str) -> List[str]:
    """The stored list; empty if there is none or it cannot be read (an unreadable file must not stop a build)."""
    try:
        with open(excluded_directories_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return []
    entries = content.get("excluded_directories") if isinstance(content, dict) else None
    if not isinstance(entries, list):
        return []
    return minimal([entry for entry in entries if isinstance(entry, str)])


def save_excluded_directories(project_dir: str, directories: Sequence[str]) -> List[str]:
    """Store ``directories`` (made minimal) and return what was stored."""
    stored = minimal(directories)
    os.makedirs(project_dir, exist_ok=True)
    path = excluded_directories_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump({"excluded_directories": stored}, file, indent=2)
        file.write("\n")
    os.replace(temporary, path)
    return stored


def excluding_directory(directories: Sequence[str], relative: str) -> Optional[str]:
    """The directory of ``directories`` that excludes ``relative`` (itself or one above it), or None."""
    path = normalize(relative)
    if path is None:
        return None
    for directory in minimal(directories):
        if _is_below(path, directory):
            return directory
    return None


def toggle(directories: Sequence[str], relative: str) -> List[str]:
    """``directories`` with ``relative`` excluded if it was not, and included again if it was listed itself.

    A directory excluded through one above it cannot be included on its own: the list is returned unchanged (include
    the one above instead). Excluding a directory drops the ones below it from the list, as they are excluded anyway.
    """
    path = normalize(relative)
    current = minimal(directories)
    if path is None:
        return current
    if path in current:
        return [directory for directory in current if directory != path]
    if excluding_directory(current, path) is not None:
        return current
    return minimal([directory for directory in current if not _is_below(directory, path)] + [path])


def environment_value(directories: Sequence[str], existing: str = "", root: Optional[str] = None) -> str:
    """``DP_PROJECT_EXCLUDE_DIRS`` for a build: the entries already set (e.g. in a configuration's settings) and the
    stored directories, without duplicates. With ``root`` (the project directory of the run) the stored directories
    are passed as absolute paths below it."""
    stored = minimal(directories)
    if root is not None:
        stored = [os.path.join(root, *directory.split("/")) for directory in stored]
    entries: List[str] = []
    for entry in [*existing.split(":"), *stored]:
        if entry and entry not in entries:
            entries.append(entry)
    return ":".join(entries)


def relative_entry(project_root: str, text: str) -> Optional[str]:
    """The list entry for a hand-written ``text``: a path relative to the project directory (``build/_deps``) or an
    absolute path below it; None if it names no directory below the project directory. The directory need not exist
    (yet): the build may create it."""
    text = text.strip()
    if os.path.isabs(text):
        root = os.path.normpath(os.path.abspath(project_root))
        text = os.path.relpath(os.path.normpath(text), root)
    return normalize(text)


def listed_children(directories: Sequence[str], relative: str = "") -> List[str]:
    """The directories directly in ``relative`` that lie on the way to a listed directory, whether they exist or
    not (relative to the project directory, like :func:`subdirectories`): ``build/_deps`` listed gives ``build`` for
    "" and ``build/_deps`` for ``build``."""
    prefix = relative + "/" if relative else ""
    names = {
        prefix + path[len(prefix) :].split("/", 1)[0]
        for path in map(normalize, directories)
        if path is not None and path.startswith(prefix) and len(path) > len(prefix)
    }
    return sorted(names, key=lambda name: (name.lower(), name))


def subdirectories(project_root: str, relative: str = "") -> List[str]:
    """The directories directly in ``relative`` (relative to ``project_root``; "" is the project directory), as paths
    relative to ``project_root``, sorted by name (ignoring case, then upper case first). Symbolic links to directories
    are listed but not followed further by the tree (they can form cycles); ``.discopop`` and ``.git`` are left
    out."""
    base = os.path.join(project_root, relative) if relative else project_root
    names: List[str] = []
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                try:
                    is_directory = entry.is_dir()
                except OSError:
                    continue
                if is_directory and entry.name not in HIDDEN_DIRECTORY_NAMES:
                    names.append(entry.name)
    except OSError:
        return []
    return [
        posixpath.join(relative, name) if relative else name
        for name in sorted(names, key=lambda name: (name.lower(), name))
    ]


def is_symbolic_link(project_root: str, relative: str) -> bool:
    return os.path.islink(os.path.join(project_root, relative))
