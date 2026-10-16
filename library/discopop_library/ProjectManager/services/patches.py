# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Discovery of the patches the patch generator wrote below ``<dot_dp>/patch_generator``."""

import os
from typing import Dict, List, Tuple

PATCH_GENERATOR_DIRECTORY = "patch_generator"
PATCH_SUFFIX = ".patch"


def _suggestion_order(name: str) -> Tuple[int, int, str]:
    """Numeric ids first in numeric order, then other names alphabetically (never compares int with str)."""
    return (0, int(name), "") if name.isdigit() else (1, 0, name)


def discover_patches(dot_dp_path: str) -> Dict[str, List[str]]:
    """Map every suggestion id to the sorted names of its ``.patch`` files.

    An id is a subdirectory of ``<dot_dp>/patch_generator`` containing at least one ``.patch`` file;
    ids are ordered numerically.
    """
    patch_generator_dir = os.path.join(dot_dp_path, PATCH_GENERATOR_DIRECTORY)
    patches: Dict[str, List[str]] = {}
    if not os.path.isdir(patch_generator_dir):
        return patches
    for suggestion_id in sorted(os.listdir(patch_generator_dir), key=_suggestion_order):
        suggestion_dir = os.path.join(patch_generator_dir, suggestion_id)
        if not os.path.isdir(suggestion_dir):
            continue
        patch_files = sorted(f for f in os.listdir(suggestion_dir) if f.endswith(PATCH_SUFFIX))
        if patch_files:
            patches[suggestion_id] = patch_files
    return patches


def discover_suggestion_ids(dot_dp_path: str) -> List[str]:
    """The ids of all suggestions that have at least one patch, in numeric order."""
    return list(discover_patches(dot_dp_path))


def count_patches(dot_dp_path: str) -> int:
    """The number of ``.patch`` files over all suggestions."""
    return sum(len(files) for files in discover_patches(dot_dp_path).values())


def has_patches(dot_dp_path: str) -> bool:
    return bool(discover_patches(dot_dp_path))
