# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What a repair run reports, live and afterwards.

Two channels, modelled on the autotuner's
:mod:`discopop_library.EmpiricalAutotuning.output.progress`:

* ``@@PR_PROGRESS <json>`` lines on stdout, so a consumer that already streams the
  process' output (the Project Manager GUI) can follow a run without a second IPC
  mechanism, and
* ``patch_repair/progress.jsonl``, so a finished run can be redisplayed without
  repeating it.

``results.json`` is the run's result proper: one record per considered suggestion,
written incrementally so an interrupted run still describes what it did.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import time
from typing import Any, Dict, List, Optional

PROGRESS_PREFIX = "@@PR_PROGRESS "

# Status values of a suggestion record in results.json.
STATUS_OK = "ok"  # built as generated; nothing to repair
STATUS_REPAIRED = "repaired"  # did not build, a fix was found and written
STATUS_FAILED = "failed"  # did not build, no fix found within the budget
STATUS_NOT_APPLIED = "not_applied"  # patches did not apply, so nothing was built
STATUS_SKIPPED = "skipped"  # not considered (budget exhausted, or interrupted)
# Did not build, and the agent never delivered an answer to judge: every call it was
# allowed failed before the model produced one (unreachable provider, a server error,
# no response within the timeout). Deliberately not STATUS_FAILED: that one says a
# model was asked and could not fix the patch, which is a statement about the model.
# Reporting an unreachable endpoint as a failed repair would be a measurement of
# nothing, read as a measurement of the model.
STATUS_UNREACHABLE = "agent_unreachable"


@dataclass
class SuggestionRecord:
    suggestion_id: int
    hotspot_type: str
    status: str
    # The file ids of the suggestion's patch set, and those a repair actually changed.
    files: List[int] = field(default_factory=list)
    changed_files: List[int] = field(default_factory=list)
    # Every agent call made for this suggestion, answered or not, which is also how
    # many directories sit under attempts/<id>/.
    attempts: int = 0
    # How many of those never produced an answer from the model. They cost no tokens
    # and gave the model no chance, so they do not consume the prompt/retry budget --
    # see PatchRepairArguments.agent_error_retries.
    unanswered: int = 0
    accepted_attempt: Optional[int] = None
    backend: Optional[str] = None
    model: Optional[str] = None
    first_error: str = ""
    duration_s: float = 0.0


class ProgressReporter:
    """Emits repair events to stdout and to ``progress.jsonl``."""

    def __init__(self, jsonl_path: Optional[str] = None) -> None:
        self._fh = open(jsonl_path, "w") if jsonl_path is not None else None
        self._start = time.time()

    def _emit(self, obj: Dict[str, Any]) -> None:
        line = json.dumps(obj, sort_keys=True)
        print(PROGRESS_PREFIX + line, flush=True)
        if self._fh is not None:
            self._fh.write(line + "\n")
            self._fh.flush()

    # -- events ------------------------------------------------------------------

    def start(self, candidates: List[int], backend: Optional[str], model: Optional[str], dry_run: bool) -> None:
        self._emit(
            {
                "event": "start",
                "candidates": [int(c) for c in candidates],
                "candidate_count": len(candidates),
                "backend": backend,
                "model": model,
                "dry_run": bool(dry_run),
            }
        )

    def discovery(self, built: List[int], failing: List[int], not_applied: List[int], reference_built: bool) -> None:
        self._emit(
            {
                "event": "discovery",
                "built": [int(s) for s in built],
                "failing": [int(s) for s in failing],
                "not_applied": [int(s) for s in not_applied],
                "reference_built": bool(reference_built),
            }
        )

    def attempt(
        self,
        suggestion_id: int,
        attempt: int,
        turn: int,
        template: str,
        outcome: str,
        detail: str = "",
    ) -> None:
        """One agent call and what became of its answer.

        ``outcome`` names the gate that rejected the candidate (or ``accepted``), which
        is what makes a failing run diagnosable without reading every transcript.
        """
        self._emit(
            {
                "event": "attempt",
                "suggestion": int(suggestion_id),
                "attempt": int(attempt),
                "turn": int(turn),
                "template": template,
                "outcome": outcome,
                "detail": detail[:2000],
            }
        )

    def suggestion(self, record: SuggestionRecord) -> None:
        obj: Dict[str, Any] = {"event": "suggestion"}
        obj.update(asdict(record))
        self._emit(obj)

    def done(self, repaired: int, failed: int, considered: int, duration_s: float, unreachable: int = 0) -> None:
        self._emit(
            {
                "event": "done",
                "repaired": int(repaired),
                "failed": int(failed),
                # Suggestions the agent never answered for. Counted apart from
                # ``failed``, which says a model was asked and could not fix the patch.
                "unreachable": int(unreachable),
                "considered": int(considered),
                "duration_s": round(duration_s, 2),
            }
        )

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class ResultsWriter:
    """Maintains ``results.json`` incrementally.

    Written after every suggestion rather than once at the end: a repair run can take a
    long time and be stopped part way through, and the suggestions it already repaired
    are a real result that must not be lost with the process.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.records: Dict[int, SuggestionRecord] = {}

    def record(self, record: SuggestionRecord) -> None:
        self.records[record.suggestion_id] = record
        self.flush()

    def flush(self) -> None:
        payload = {
            "suggestions": {
                str(suggestion_id): asdict(record) for suggestion_id, record in sorted(self.records.items())
            }
        }
        with open(self.path, "w") as f:
            json.dump(payload, f, sort_keys=True, indent=4)

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for record in self.records.values():
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts
