# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Keeping the generated patches recoverable.

A repair overwrites files that ``discopop_patch_generator`` produced, so the pristine
version has to survive somewhere. The whole ``patch_generator/<id>/`` directory is
backed up, not just the files that happen to change: the applicator treats a
suggestion's patches as one indivisible unit, so a restore has to reproduce a coherent
set rather than a mixture of repaired and original files.
"""

import hashlib
import logging
import os
import shutil
from typing import List, Optional

logger = logging.getLogger("PatchRepair").getChild("backups")

BACKUPS_DIR_NAME = "backups"

# Next to backups/<id>/: the digest of the patch set a repair left in patch_generator/<id>/.
# It is what tells "this is our own repaired set" apart from "the patch generator has
# written a new one since", which a backup alone cannot.
WRITTEN_DIGEST_SUFFIX = ".written"


def backups_dir(patch_repair_path: str) -> str:
    return os.path.join(patch_repair_path, BACKUPS_DIR_NAME)


def patch_set_digest(directory: str) -> Optional[str]:
    """A digest over the file names and contents of a patch directory, or None if absent."""
    if not os.path.isdir(directory):
        return None
    digest = hashlib.sha256()
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        digest.update(name.encode() + b"\0")
        with open(path, "rb") as f:
            digest.update(f.read())
        digest.update(b"\0")
    return digest.hexdigest()


def _written_digest_path(patch_repair_path: str, suggestion_id: int) -> str:
    return os.path.join(backups_dir(patch_repair_path), str(suggestion_id) + WRITTEN_DIGEST_SUFFIX)


def _read_written_digest(patch_repair_path: str, suggestion_id: int) -> Optional[str]:
    path = _written_digest_path(patch_repair_path, suggestion_id)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read().strip() or None


def record_written_patch_set(patch_repair_path: str, patch_generator_path: str, suggestion_id: int) -> None:
    """Remember which patch set a repair left in place for ``suggestion_id``."""
    digest = patch_set_digest(os.path.join(patch_generator_path, str(suggestion_id)))
    if digest is None:
        return
    os.makedirs(backups_dir(patch_repair_path), exist_ok=True)
    with open(_written_digest_path(patch_repair_path, suggestion_id), "w") as f:
        f.write(digest)


def _is_current(patch_repair_path: str, patch_generator_path: str, suggestion_id: int) -> bool:
    """Whether the backup of ``suggestion_id`` belongs to the patches now on disk.

    It does when patch_generator/<id>/ still holds either the backed up set itself or
    the set a repair wrote on top of it. Anything else was written by the patch
    generator after the backup was made, so the backup is from an older generation.
    """
    current = patch_set_digest(os.path.join(patch_generator_path, str(suggestion_id)))
    if current is None:
        return False
    backup = patch_set_digest(os.path.join(backups_dir(patch_repair_path), str(suggestion_id)))
    return current in (backup, _read_written_digest(patch_repair_path, suggestion_id))


def _discard_backup(patch_repair_path: str, suggestion_id: int) -> None:
    destination = os.path.join(backups_dir(patch_repair_path), str(suggestion_id))
    if os.path.exists(destination):
        shutil.rmtree(destination)
    written = _written_digest_path(patch_repair_path, suggestion_id)
    if os.path.exists(written):
        os.remove(written)


def backup_patch_set(patch_repair_path: str, patch_generator_path: str, suggestion_id: int) -> str:
    """Copy a suggestion's pristine patch directory aside.

    An existing backup is kept as long as it belongs to the patches on disk: the first
    backup is the pristine state, and overwriting it with an already-repaired set would
    destroy exactly what it exists to protect. A backup the patch generator has since
    superseded is replaced, because restoring it would bring back patches from an older
    generation.
    """
    destination = os.path.join(backups_dir(patch_repair_path), str(suggestion_id))
    if os.path.exists(destination):
        if _is_current(patch_repair_path, patch_generator_path, suggestion_id):
            logger.debug("Backup of suggestion " + str(suggestion_id) + " already exists; keeping it.")
            return destination
        logger.info("Patches of suggestion " + str(suggestion_id) + " were regenerated; replacing the old backup.")
        _discard_backup(patch_repair_path, suggestion_id)
    source = os.path.join(patch_generator_path, str(suggestion_id))
    os.makedirs(backups_dir(patch_repair_path), exist_ok=True)
    shutil.copytree(source, destination)
    logger.debug("Backed up suggestion " + str(suggestion_id) + " to " + destination)
    return destination


def backed_up_suggestion_ids(patch_repair_path: str) -> List[int]:
    root = backups_dir(patch_repair_path)
    if not os.path.exists(root):
        return []
    return sorted(
        int(entry) for entry in os.listdir(root) if entry.isdigit() and os.path.isdir(os.path.join(root, entry))
    )


def restore_patch_sets(patch_repair_path: str, patch_generator_path: str) -> List[int]:
    """Put every backed up patch set back and report which ones were restored.

    A backup the patch generator has superseded is not restored but dropped: the
    patches on disk are then newer than anything the repair touched.
    """
    restored: List[int] = []
    for suggestion_id in backed_up_suggestion_ids(patch_repair_path):
        source = os.path.join(backups_dir(patch_repair_path), str(suggestion_id))
        destination = os.path.join(patch_generator_path, str(suggestion_id))
        # A missing directory counts as superseded too: a repair never removes one, so
        # the patch generator did, and restoring it would resurrect a stale suggestion.
        if not _is_current(patch_repair_path, patch_generator_path, suggestion_id):
            logger.warning(
                "Not restoring suggestion "
                + str(suggestion_id)
                + ": its patches were regenerated after the backup was made. Dropping the stale backup."
            )
            _discard_backup(patch_repair_path, suggestion_id)
            continue
        if os.path.exists(destination):
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        written = _written_digest_path(patch_repair_path, suggestion_id)
        if os.path.exists(written):
            os.remove(written)
        restored.append(suggestion_id)
        logger.info("Restored suggestion " + str(suggestion_id))
    return restored
