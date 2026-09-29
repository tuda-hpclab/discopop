# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Structured outcome of one ``discopop_patch_applicator --apply`` invocation.

The plain integer return code cannot express *which* suggestions were requested and
which of them actually made it into the code. Without that distinction a failed
application is indistinguishable from a run that legitimately had no suggestions to
apply, and the unmodified sequential code gets measured and reported as if it were a
parallel configuration. Every consumer (Project Manager GUI, autotuner, sanity
checker, MCP server) therefore works with this result instead of the bare code.

The result is additionally persisted next to ``applied_suggestions.json`` as
``application_result.json`` so it reaches consumers that only see the project copy
(e.g. ``execute_configuration``) without threading return values through every
intermediate call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

APPLICATION_RESULT_FILE_NAME = "application_result.json"

# Return codes of the patch applicator's apply action.
RETVAL_APPLIED = 0  # everything requested is in place
RETVAL_NOTHING_APPLIED = 1  # nothing requested could be applied
RETVAL_PARTIALLY_APPLIED = 2  # some requested suggestions applied, others failed


@dataclass
class PatchApplicationResult:
    """Which of the requested suggestions ended up in the code, and which did not."""

    requested: List[str] = field(default_factory=list)
    # newly applied during this invocation
    applied: List[str] = field(default_factory=list)
    # requested, a patch exists, but ``patch`` refused it (rolled back again)
    failed: List[str] = field(default_factory=list)
    # requested, but no patch has been generated for the id
    unknown: List[str] = field(default_factory=list)
    # requested and already present in applied_suggestions.json
    already_applied: List[str] = field(default_factory=list)

    @property
    def unapplied(self) -> List[str]:
        """Requested suggestions that are *not* in the code: failed plus unknown."""
        return self.failed + self.unknown

    @property
    def unapplied_ids(self) -> List[int]:
        """``unapplied`` as suggestion ids, for the callers that key on the numeric id.

        Non-numeric entries are dropped: the applicator also accepts symbolic
        selectors, which no suggestion id can be compared against.
        """
        return [int(s) for s in self.unapplied if s.lstrip("-").isdigit()]

    @property
    def in_code(self) -> List[str]:
        """Requested suggestions that are in the code after this invocation."""
        return self.applied + self.already_applied

    @property
    def failure(self) -> bool:
        """True if at least one requested suggestion did not make it into the code.

        This is the condition that must never be silently ignored: the code that is
        about to be compiled and measured does not contain the parallelization that
        the measurement will be attributed to.
        """
        return bool(self.unapplied)

    @property
    def complete(self) -> bool:
        return not self.failure

    @property
    def nothing_in_code(self) -> bool:
        """True if the code is unmodified although suggestions were requested."""
        return bool(self.requested) and not self.in_code

    @property
    def retval(self) -> int:
        """The patch applicator return code corresponding to this result."""
        if not self.failure:
            return RETVAL_APPLIED
        if self.in_code:
            return RETVAL_PARTIALLY_APPLIED
        return RETVAL_NOTHING_APPLIED

    def summary(self) -> str:
        """One-line human-readable summary, used for log lines and GUI messages."""
        if not self.requested:
            return "No suggestions requested."
        if self.complete:
            return "All requested suggestions applied: " + ", ".join(self.requested) + "."
        parts = ["Suggestion application incomplete."]
        if self.in_code:
            parts.append("Applied: " + ", ".join(self.in_code) + ".")
        if self.failed:
            parts.append("Patch rejected for: " + ", ".join(self.failed) + ".")
        if self.unknown:
            parts.append("No patch generated for: " + ", ".join(self.unknown) + ".")
        if self.nothing_in_code:
            parts.append("The code is UNMODIFIED.")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested": list(self.requested),
            "applied": list(self.applied),
            "failed": list(self.failed),
            "unknown": list(self.unknown),
            "already_applied": list(self.already_applied),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatchApplicationResult":
        return cls(
            requested=[str(s) for s in data.get("requested", [])],
            applied=[str(s) for s in data.get("applied", [])],
            failed=[str(s) for s in data.get("failed", [])],
            unknown=[str(s) for s in data.get("unknown", [])],
            already_applied=[str(s) for s in data.get("already_applied", [])],
        )


def result_file_path(patch_applicator_dir: str) -> str:
    return os.path.join(patch_applicator_dir, APPLICATION_RESULT_FILE_NAME)


def write_application_result(patch_applicator_dir: str, result: PatchApplicationResult) -> None:
    """Persist ``result`` so consumers seeing only the project copy can read it."""
    try:
        with open(result_file_path(patch_applicator_dir), "w") as f:
            json.dump(result.to_dict(), f, sort_keys=True, indent=4)
    except OSError:
        # a missing result file degrades to "no information", never to a crash
        pass


def read_application_result(patch_applicator_dir: str) -> Optional[PatchApplicationResult]:
    """Load the persisted result, or None when none was written."""
    path = result_file_path(patch_applicator_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return PatchApplicationResult.from_dict(json.load(f))
    except (OSError, json.JSONDecodeError):
        return None


def clear_application_result(patch_applicator_dir: str) -> None:
    """Remove a stale result file so it can never be mistaken for a fresh one."""
    path = result_file_path(patch_applicator_dir)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
