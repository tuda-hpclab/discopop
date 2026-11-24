# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Paths of the project that copies of it leave out (build trees, candidates of the autotuner).

Configured build directories are recognized and left out anyway (``configurations/copy_exclusions.py``). This list is
for what has no marker: a build directory of another build system, large input data that ``execute.sh`` reads from
``$DP_PROJECT_ORIGINAL_DIR``, ``.git`` of a project whose build does not read it. A path left out of the copy is no
input of the build either, so the list is part of the build fingerprint (``configurations/builds.py``).

Stored in ``.discopop/project/copy_exclude.json`` as paths (files or directories) relative to the project directory
with ``/`` as separator. ``.discopop`` cannot be listed. Toolkit-free.
"""

import json
import os
from typing import List, Sequence

from discopop_library.ProjectManager.services.excluded_directories import minimal

COPY_EXCLUDE_FILE = "copy_exclude.json"
_KEY = "copy_exclude"


def copy_exclude_path(project_dir: str) -> str:
    """The file of the list; ``project_dir`` is ``.discopop/project`` (``ProjectManagerArguments.project_dir``)."""
    return os.path.join(project_dir, COPY_EXCLUDE_FILE)


def _valid(paths: Sequence[str]) -> List[str]:
    return [path for path in minimal(paths) if path.split("/", 1)[0] != ".discopop"]


def load_copy_exclude(project_dir: str) -> List[str]:
    """The stored list; empty if there is none or it cannot be read (an unreadable file must not stop a build)."""
    try:
        with open(copy_exclude_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return []
    entries = content.get(_KEY) if isinstance(content, dict) else None
    if not isinstance(entries, list):
        return []
    return _valid([entry for entry in entries if isinstance(entry, str)])


def save_copy_exclude(project_dir: str, paths: Sequence[str]) -> List[str]:
    """Store ``paths`` (normalized, without those below another one) and return what was stored."""
    stored = _valid(paths)
    os.makedirs(project_dir, exist_ok=True)
    path = copy_exclude_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump({_KEY: stored}, file, indent=2)
        file.write("\n")
    os.replace(temporary, path)
    return stored
