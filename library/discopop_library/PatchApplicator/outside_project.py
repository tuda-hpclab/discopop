# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which suggestions patch files outside of the project.

A suggestion is a directory ``patch_generator/<id>/`` of patches named ``<file id>.patch``; the file id is
resolved through ``FileMapping.txt`` (``<id>\\t<absolute path>``). The code the profiler instruments can include
directories outside of the project (shared sources), and their paths stay absolute when the project manager works
in a copy of the project: applying such a patch there would modify the ORIGINAL file, which other projects may
use, which nothing restores and which parallel copies (the autotuner) would patch concurrently.

"Outside" is decided relative to the project of a ``.discopop`` directory, i.e. the directory that contains it:
a target is inside if it lies below that directory, compared as given or with symbolic links resolved (the
project may be reached through a link, and the paths in the file mapping name it either way). Only an explicit,
manual application may patch outside targets (``--allow-outside-project`` of the patch applicator,
``--allow-patching-outside-project`` of the project manager); automatic tools skip such suggestions with
:func:`log_skipped_outside_suggestions`.

This module imports no GUI toolkit and runs no process.
"""

import logging
import os
from typing import Dict, Iterable, List, Optional, Tuple

PATCH_SUFFIX = ".patch"


def project_root_of(dot_discopop: str) -> str:
    """The project of a ``.discopop`` directory: the directory that contains it."""
    return os.path.dirname(os.path.abspath(dot_discopop))


def _below(path: str, root: str) -> bool:
    """True if ``path`` lies below ``root``; compares with a trailing separator, so ``/a/b2`` is not below ``/a/b``."""
    return os.path.join(path, "").startswith(os.path.join(root, ""))


def is_outside_project(target: str, project_root: str) -> bool:
    """True if ``target`` is not below ``project_root``, compared as given and with symbolic links resolved."""
    if _below(os.path.abspath(target), os.path.abspath(project_root)):
        return False
    if _below(os.path.realpath(target), os.path.realpath(project_root)):
        return False
    return True


def read_file_mapping_paths(dot_discopop: str) -> Dict[int, str]:
    """The ``FileMapping.txt`` of ``dot_discopop`` as file id -> path (empty if there is none).

    Unlike ``load_file_mapping`` it keeps files that do not exist: a missing file is no reason to
    treat its suggestion as one inside the project.
    """
    mapping: Dict[int, str] = dict()
    path = os.path.join(dot_discopop, "FileMapping.txt")
    if not os.path.exists(path):
        return mapping
    try:
        with open(path, "r") as f:
            for line in f:
                split_line = line.rstrip("\n").split("\t")
                if len(split_line) < 2 or not split_line[0].isdigit():
                    continue
                mapping[int(split_line[0])] = split_line[1]
    except (OSError, ValueError):  # an unreadable file mapping classifies nothing
        pass
    return mapping


def patch_target_paths(dot_discopop: str, suggestion_id: str, file_mapping: Dict[int, str]) -> List[str]:
    """The files the patches of suggestion ``suggestion_id`` modify (unknown file ids are left out)."""
    suggestion_dir = os.path.join(dot_discopop, "patch_generator", suggestion_id)
    if not os.path.isdir(suggestion_dir):
        return []
    targets: List[str] = []
    for patch_file_name in sorted(os.listdir(suggestion_dir)):
        file_id = patch_file_name[: -len(PATCH_SUFFIX)] if patch_file_name.endswith(PATCH_SUFFIX) else ""
        if file_id.isdigit() and int(file_id) in file_mapping:
            targets.append(file_mapping[int(file_id)])
    return targets


def find_outside_project_targets(
    dot_discopop: str, suggestion_ids: Optional[Iterable[object]] = None
) -> Dict[str, List[str]]:
    """The suggestions with patch targets outside the project of ``dot_discopop``, and those targets.

    ``suggestion_ids`` limits the check (ids as strings or numbers); ``None`` checks every generated suggestion.
    The result maps a suggestion id to its sorted outside targets and holds only suggestions that have some.
    """
    dot_discopop = os.path.abspath(dot_discopop)
    if suggestion_ids is None:
        generator_dir = os.path.join(dot_discopop, "patch_generator")
        ids: List[str] = sorted(os.listdir(generator_dir)) if os.path.isdir(generator_dir) else []
    else:
        ids = [str(suggestion_id) for suggestion_id in suggestion_ids]
    file_mapping = read_file_mapping_paths(dot_discopop)
    root = project_root_of(dot_discopop)
    outside: Dict[str, List[str]] = dict()
    for suggestion_id in ids:
        targets = sorted(set(patch_target_paths(dot_discopop, suggestion_id, file_mapping)))
        outside_targets = [t for t in targets if is_outside_project(t, root)]
        if outside_targets:
            outside[suggestion_id] = outside_targets
    return outside


def split_by_outside_project(dot_discopop: str, suggestion_ids: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """``suggestion_ids`` without the outside ones (order kept), and the outside ones with their targets."""
    outside = find_outside_project_targets(dot_discopop, suggestion_ids)
    return [s for s in suggestion_ids if str(s) not in outside], outside


def describe_outside_targets(outside: Dict[str, List[str]]) -> str:
    """One line per suggestion: ``suggestion 3: /shared/a.c, /shared/b.c``."""
    return "\n".join(
        "suggestion " + suggestion_id + ": " + ", ".join(targets)
        for suggestion_id, targets in sorted(outside.items(), key=lambda item: (len(item[0]), item[0]))
    )


def log_skipped_outside_suggestions(logger: logging.Logger, tool: str, outside: Dict[str, List[str]]) -> None:
    """Say which suggestions ``tool`` skips because they patch files outside the project, and why."""
    if not outside:
        return
    logger.warning(
        tool
        + ": skipping "
        + str(len(outside))
        + " suggestion(s) that patch files outside the project; automatic tools never modify files other projects "
        + "may use. Apply them manually (discopop_patch_applicator --allow-outside-project, or the project "
        + "manager's --allow-patching-outside-project):\n"
        + describe_outside_targets(outside)
    )
