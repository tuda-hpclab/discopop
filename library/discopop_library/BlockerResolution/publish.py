# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Making approved suggestions usable by the other tools, and withdrawing them again.

An approval rests on an LLM agent's judgement, not on DiscoPoP's analysis, so only a published one is used: a reviewed
run publishes its approvals when it ends (unless --no-use-approved), and the user withdraws what they do not accept.
Publishing copies the patches of the approved suggestions into ``patch_generator/<id>/``, where the patch applicator,
the autotuner, patch repair and the GUI look for patches. Each published directory holds a marker file with the
assumption the approval rests on and the declared result differences, so that it can be told from a generated patch,
shown with its assumption and withdrawn again. Publishing never overwrites a generated patch.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from discopop_library.BlockerResolution.results import APPROVED_DIR, APPROVED_FILE
from discopop_library.BlockerResolution.unsure import UNSURE_SUGGESTIONS_FILE, Fingerprint

if TYPE_CHECKING:
    from discopop_library.BlockerResolution.BlockerResolutionArguments import BlockerResolutionArguments

PATCH_GENERATOR_DIR = "patch_generator"
MARKER_FILE = "agent_approved.json"


@dataclass
class PublishResult:
    published: List[int] = field(default_factory=list)
    # id -> why it was not published
    skipped: Dict[int, str] = field(default_factory=dict)


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_approved(dot_dp_path: str) -> Dict[int, Dict[str, Any]]:
    """the approvals of the last check by pattern id, empty if there is none"""
    data = _read(os.path.join(dot_dp_path, "blocker_resolution", APPROVED_FILE))
    if data is None:
        return {}
    return {int(e["pattern_id"]): e for e in data.get("suggestions", []) if isinstance(e, dict) and "pattern_id" in e}


def _is_current(dot_dp_path: str) -> bool:
    """whether the approvals belong to the explorer output there is now (a later explorer run may number loops
    differently)"""
    data = _read(os.path.join(dot_dp_path, "blocker_resolution", APPROVED_FILE))
    unsure = os.path.join(dot_dp_path, UNSURE_SUGGESTIONS_FILE)
    if data is None or not os.path.exists(unsure):
        return False
    return bool(data.get("explorer_output") == Fingerprint.of(unsure).to_dict())


def published_ids(dot_dp_path: str) -> List[int]:
    """the suggestions currently published, in numeric order"""
    root = os.path.join(dot_dp_path, PATCH_GENERATOR_DIR)
    if not os.path.isdir(root):
        return []
    return sorted(
        int(name)
        for name in os.listdir(root)
        if name.isdigit() and os.path.isfile(os.path.join(root, name, MARKER_FILE))
    )


def publish_approved(dot_dp_path: str, ids: Optional[Sequence[int]] = None) -> PublishResult:
    """Publish the approved suggestions (all, or those in ``ids``)."""
    result = PublishResult()
    approved = load_approved(dot_dp_path)
    wanted = sorted(approved) if ids is None else list(ids)
    if wanted and not _is_current(dot_dp_path):
        for pattern_id in wanted:
            result.skipped[pattern_id] = "the explorer ran again since the blocker resolution; run it again"
        return result
    for pattern_id in wanted:
        entry = approved.get(pattern_id)
        if entry is None:
            result.skipped[pattern_id] = "not approved"
            continue
        source = os.path.join(dot_dp_path, "blocker_resolution", APPROVED_DIR, str(pattern_id))
        patches = sorted(f for f in os.listdir(source) if f.endswith(".patch")) if os.path.isdir(source) else []
        if not patches:
            result.skipped[pattern_id] = "the approval has no patch files"
            continue
        target = os.path.join(dot_dp_path, PATCH_GENERATOR_DIR, str(pattern_id))
        if os.path.exists(target) and not os.path.isfile(os.path.join(target, MARKER_FILE)):
            result.skipped[pattern_id] = "the patch generator wrote a patch for this id; it is not replaced"
            continue
        shutil.rmtree(target, ignore_errors=True)
        os.makedirs(target)
        for name in patches:
            shutil.copyfile(os.path.join(source, name), os.path.join(target, name))
        marker = {
            "note": "Approved by an LLM agent, not by DiscoPoP's analysis; it rests on the assumption stated.",
            **{k: entry.get(k) for k in ("assumption", "result_differences", "review", "backend", "model")},
        }
        with open(os.path.join(target, MARKER_FILE), "w") as f:
            json.dump(marker, f, indent=1)
            f.write("\n")
        result.published.append(pattern_id)
    return result


def withdraw_published(dot_dp_path: str, ids: Optional[Sequence[int]] = None) -> List[int]:
    """Remove published suggestions (all, or those in ``ids``); generated patches are never touched."""
    withdrawn: List[int] = []
    for pattern_id in published_ids(dot_dp_path):
        if ids is not None and pattern_id not in ids:
            continue
        shutil.rmtree(os.path.join(dot_dp_path, PATCH_GENERATOR_DIR, str(pattern_id)))
        withdrawn.append(pattern_id)
    return withdrawn


def marker_of(dot_dp_path: str, pattern_id: int) -> Optional[Dict[str, Any]]:
    """assumption and result differences of a published suggestion, None for one that is not published"""
    return _read(os.path.join(dot_dp_path, PATCH_GENERATOR_DIR, str(pattern_id), MARKER_FILE))


def manage_published(arguments: "BlockerResolutionArguments") -> int:
    """the command line side: --publish-approved and --withdraw-published"""
    dot = os.path.abspath(arguments.dot_dp_path)
    ids = arguments.suggestion_ids()
    if arguments.withdraw_published:
        withdrawn = withdraw_published(dot, ids)
        print("Withdrawn: " + (", ".join(map(str, withdrawn)) or "nothing"))
        return 0
    result = publish_approved(dot, ids)
    print("Published: " + (", ".join(map(str, result.published)) or "nothing"))
    for pattern_id, reason in sorted(result.skipped.items()):
        print("Not published " + str(pattern_id) + ": " + reason)
    if result.published:
        print("They carry an agent's assumption (see " + MARKER_FILE + "), not DiscoPoP's analysis.")
    return 1 if result.skipped and not result.published else 0
