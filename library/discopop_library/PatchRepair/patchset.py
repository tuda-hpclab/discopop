# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A suggestion's patches, handled as one unit.

A suggestion is *not* one patch. ``patch_generator/<id>/`` holds one
``<file_id>.patch`` per source file the suggestion touches, and the applicator already
treats them as indivisible: it walks the directory, stops at the first patch
``patch(1)`` rejects, and rolls the already-applied ones back (``PatchApplicator``).
A half-applied suggestion is never a state the rest of DiscoPoP has to reason about,
and the repair tool must not introduce one.

So the *set* is the object the repair pipeline operates on: one conversation per
suggestion, whole-set validation, all-or-nothing write-back. The agent may rewrite a
subset of it -- a patch that was already fine is never regenerated, which saves tokens
and removes the chance of corrupting a working patch while fixing an unrelated one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional

logger = logging.getLogger("PatchRepair").getChild("patchset")

PATCH_SUFFIX = ".patch"

# Lines a unified diff adds. Only these carry what a suggestion actually introduces,
# which is what the pragma guard is about.
ADDED_LINE = re.compile(r"^\+(?!\+\+)", re.MULTILINE)


@dataclass
class PatchEntry:
    """One ``<file_id>.patch`` and the source file it applies to."""

    file_id: int
    text: str
    target: Path

    def added_lines(self) -> List[str]:
        return [line[1:] for line in self.text.splitlines() if line.startswith("+") and not line.startswith("+++")]

    def is_empty(self) -> bool:
        """Whether this patch would change nothing."""
        return not self.text.strip()


@dataclass
class PatchSet:
    """Every patch of one suggestion."""

    suggestion_id: int
    entries: Dict[int, PatchEntry] = field(default_factory=dict)

    @property
    def file_ids(self) -> List[int]:
        return sorted(self.entries)

    def targets(self) -> Dict[int, Path]:
        return {file_id: entry.target for file_id, entry in self.entries.items()}

    def with_replacements(self, replacements: Dict[int, str]) -> "PatchSet":
        """A copy with the given files' patches replaced, the rest kept as they are.

        This is what makes "the agent may rewrite a subset" work: a file it did not
        answer for keeps its original patch untouched.
        """
        merged = PatchSet(suggestion_id=self.suggestion_id)
        for file_id, entry in self.entries.items():
            text = replacements.get(file_id, entry.text)
            merged.entries[file_id] = PatchEntry(file_id=file_id, text=text, target=entry.target)
        for file_id, text in replacements.items():
            if file_id not in merged.entries:
                raise KeyError(
                    "Suggestion "
                    + str(self.suggestion_id)
                    + " has no patch for file id "
                    + str(file_id)
                    + "; known file ids: "
                    + str(self.file_ids)
                )
        return merged

    def changed_against(self, other: "PatchSet") -> List[int]:
        """The file ids whose patch text differs from ``other``'s."""
        changed: List[int] = []
        for file_id, entry in sorted(self.entries.items()):
            previous = other.entries.get(file_id)
            if previous is None or previous.text != entry.text:
                changed.append(file_id)
        return changed

    def without_empty(self) -> "PatchSet":
        """A copy with the patches that change nothing dropped.

        An agent that answers with an empty diff for a file has made a no-op edit; the
        file's patch is then simply not part of the set any more.
        """
        kept = PatchSet(suggestion_id=self.suggestion_id)
        for file_id, entry in self.entries.items():
            if entry.is_empty():
                logger.debug("Dropping empty patch for file id " + str(file_id))
                continue
            kept.entries[file_id] = entry
        return kept


def patch_set_dir(patch_generator_path: str, suggestion_id: int) -> str:
    return os.path.join(patch_generator_path, str(suggestion_id))


def load_patch_set(patch_generator_path: str, suggestion_id: int, file_mapping: Dict[int, Path]) -> PatchSet:
    """Read a suggestion's patch directory.

    A patch whose file id is not in the file mapping is skipped with a warning rather
    than failing the run: it cannot be applied by the applicator either, so it is
    already broken in a way this tool cannot fix.
    """
    directory = patch_set_dir(patch_generator_path, suggestion_id)
    patch_set = PatchSet(suggestion_id=suggestion_id)
    if not os.path.isdir(directory):
        raise FileNotFoundError(directory)
    for name in sorted(os.listdir(directory)):
        if not name.endswith(PATCH_SUFFIX):
            continue
        stem = name[: -len(PATCH_SUFFIX)]
        if not stem.isdigit():
            continue
        file_id = int(stem)
        target = file_mapping.get(file_id)
        if target is None:
            logger.warning(
                "Suggestion "
                + str(suggestion_id)
                + " has a patch for file id "
                + str(file_id)
                + ", which the file mapping does not know. Skipping it."
            )
            continue
        with open(os.path.join(directory, name), "r", newline="") as f:
            text = f.read()
        patch_set.entries[file_id] = PatchEntry(file_id=file_id, text=text, target=target)
    return patch_set


def write_patch_set(patch_generator_path: str, patch_set: PatchSet) -> List[int]:
    """Write a patch set into ``patch_generator/<id>/``, all of it or none of it.

    The files are written to a staging directory first and moved into place only once
    every one of them is written, so an interruption cannot leave a set that is half
    repaired and half original. Files that were in the directory before and are not in
    the set are removed: a patch that is no longer part of the suggestion must not stay
    behind for the applicator to find.
    """
    directory = patch_set_dir(patch_generator_path, patch_set.suggestion_id)
    staging = directory + ".discopop_patch_repair.staging"
    if os.path.exists(staging):
        _remove_tree(staging)
    os.makedirs(staging)
    try:
        for file_id, entry in sorted(patch_set.entries.items()):
            # newline="" keeps the line terminators the canonicalization restored
            with open(os.path.join(staging, str(file_id) + PATCH_SUFFIX), "w", newline="") as f:
                f.write(entry.text)
        for name in os.listdir(directory):
            os.remove(os.path.join(directory, name))
        for name in os.listdir(staging):
            os.replace(os.path.join(staging, name), os.path.join(directory, name))
    finally:
        if os.path.exists(staging):
            _remove_tree(staging)
    return patch_set.file_ids


def snapshot_patch_dir(patch_generator_path: str, suggestion_id: int) -> Dict[str, bytes]:
    """The exact bytes of every file in ``patch_generator/<id>/``, for :func:`restore_patch_dir`."""
    directory = patch_set_dir(patch_generator_path, suggestion_id)
    snapshot: Dict[str, bytes] = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                snapshot[name] = f.read()
    return snapshot


def restore_patch_dir(patch_generator_path: str, suggestion_id: int, snapshot: Dict[str, bytes]) -> None:
    """Put ``patch_generator/<id>/`` back exactly as :func:`snapshot_patch_dir` found it.

    Byte for byte, including files a :class:`PatchSet` does not carry (a patch for a file
    id the mapping does not know), so undoing a rejected candidate cannot change anything
    else about the directory.
    """
    directory = patch_set_dir(patch_generator_path, suggestion_id)
    staging = directory + ".discopop_patch_repair.staging"
    if os.path.exists(staging):
        _remove_tree(staging)
    os.makedirs(staging)
    try:
        for name, content in snapshot.items():
            with open(os.path.join(staging, name), "wb") as f:
                f.write(content)
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                os.remove(path)
        for name in os.listdir(staging):
            os.replace(os.path.join(staging, name), os.path.join(directory, name))
    finally:
        if os.path.exists(staging):
            _remove_tree(staging)


def _remove_tree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
