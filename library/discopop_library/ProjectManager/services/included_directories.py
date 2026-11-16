# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Directories outside the project whose code is project code as well, e.g. sources shared between projects.

The profiler counts every file below the project directory (``DP_PROJECT_ROOT_DIR``) as project code. The directories
listed here are added to it: the project manager passes them to every build as ``DP_PROJECT_INCLUDE_DIRS`` (``:``
separated, absolute). Unlike the project directory they are not copied for the runs of a configuration: every copy
compiles the same files. Parallelization suggestions for them are therefore only applied on explicit request.

Stored in ``.discopop/project/included_directories.json`` (kept by "Reset Project", like the configurations), as
absolute, normalized paths. A directory includes everything below it, so the list never holds a directory below another
one in it, nor one inside the project directory (it is project code anyway). Toolkit-free: the Qt GUI shows it as a
list in the Project Setup stage.
"""

import json
import os
from typing import List, Optional, Sequence

INCLUDED_DIRECTORIES_FILE = "included_directories.json"
ENVIRONMENT_VARIABLE = "DP_PROJECT_INCLUDE_DIRS"


def included_directories_path(project_dir: str) -> str:
    """The file of the list; ``project_dir`` is ``.discopop/project`` (``ProjectManagerArguments.project_dir``)."""
    return os.path.join(project_dir, INCLUDED_DIRECTORIES_FILE)


def _is_below(path: str, directory: str) -> bool:
    """Whether ``path`` is ``directory`` or lies in it (both absolute and normalized)."""
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


def normalize(path: str) -> Optional[str]:
    """``path`` as stored: absolute (``~`` expanded), without ``.``/``..`` segments and trailing separator; None if it
    is empty or relative (a relative entry would depend on the directory the list is read from)."""
    expanded = os.path.expanduser(path.strip())
    if not expanded or not os.path.isabs(expanded):
        return None
    return os.path.normpath(expanded)


def inside_project(project_root: str, path: str) -> bool:
    """Whether the normalized ``path`` lies in the project directory, as given or with symbolic links resolved."""
    roots = {os.path.normpath(os.path.abspath(project_root)), os.path.realpath(project_root)}
    spellings = {path, os.path.realpath(path)}
    return any(_is_below(spelling, root) for spelling in spellings for root in roots)


def minimal(directories: Sequence[str], project_root: Optional[str] = None) -> List[str]:
    """``directories`` normalized and sorted, without duplicates, without those below another one of them and (with
    ``project_root``) without those inside the project directory."""
    normalized = sorted({path for path in map(normalize, directories) if path is not None})
    if project_root is not None:
        normalized = [path for path in normalized if not inside_project(project_root, path)]
    return [path for path in normalized if not any(_is_below(path, other) for other in normalized if other != path)]


def load_included_directories(project_dir: str) -> List[str]:
    """The stored list; empty if there is none or it cannot be read (an unreadable file must not stop a build)."""
    try:
        with open(included_directories_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return []
    entries = content.get("included_directories") if isinstance(content, dict) else None
    if not isinstance(entries, list):
        return []
    return minimal([entry for entry in entries if isinstance(entry, str)])


def save_included_directories(project_dir: str, project_root: str, directories: Sequence[str]) -> List[str]:
    """Store ``directories`` (made minimal, those inside the project dropped) and return what was stored."""
    stored = minimal(directories, project_root)
    os.makedirs(project_dir, exist_ok=True)
    path = included_directories_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump({"included_directories": stored}, file, indent=2)
        file.write("\n")
    os.replace(temporary, path)
    return stored


def environment_value(directories: Sequence[str], existing: str = "") -> str:
    """``DP_PROJECT_INCLUDE_DIRS`` for a build: the entries already set (e.g. in a configuration's settings) and the
    stored directories, without duplicates."""
    entries: List[str] = []
    for entry in [*existing.split(":"), *minimal(directories)]:
        if entry and entry not in entries:
            entries.append(entry)
    return ":".join(entries)


def problems(project_root: str, path: str, must_exist: bool = True) -> List[str]:
    """Why ``path`` cannot be added (empty list: it can). ``must_exist=False`` accepts a hand-written path of a
    directory that does not exist (yet)."""
    normalized = normalize(path)
    if normalized is None:
        return ["Give an absolute path."]
    if inside_project(project_root, normalized):
        return [normalized + " lies inside the project directory, its code is project code anyway."]
    if must_exist and not os.path.isdir(normalized):
        return [normalized + " is not an existing directory."]
    return []
