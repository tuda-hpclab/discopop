# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""What a check writes to .discopop/suggestion_check/ (design/agent_checked_suggestions.md, §5.6)."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional

from discopop_library.SuggestionCheck.check import STATE_APPROVED, Outcome
from discopop_library.SuggestionCheck.unsure import Fingerprint, UnsureSuggestion

FORMAT_VERSION = 1
RESULTS_FILE = "results.json"
APPROVED_FILE = "approved.json"
APPROVED_DIR = "approved"
TRANSCRIPTS_DIR = "transcripts"
PROGRESS_FILE = "progress.jsonl"
PROGRESS_PREFIX = "@@SC_PROGRESS "


class Results:
    """results.json, approved.json and the approved patches. Results of earlier runs are kept for the suggestions
    this run does not check, unless they belong to another explorer run."""

    def __init__(self, path: str, fingerprint: Fingerprint, run_info: Dict[str, Any]) -> None:
        self.path = path
        self.fingerprint = fingerprint
        self.run_info = run_info
        self.entries: Dict[int, Dict[str, Any]] = dict()
        os.makedirs(path, exist_ok=True)
        previous = self._load(os.path.join(path, RESULTS_FILE))
        if previous is not None and previous.get("explorer_output") == fingerprint.to_dict():
            for entry in previous.get("suggestions", []):
                self.entries[int(entry["pattern_id"])] = entry
        else:
            # results of another explorer run: their ids may now name other loops
            for stale in (APPROVED_DIR, TRANSCRIPTS_DIR):
                shutil.rmtree(os.path.join(path, stale), ignore_errors=True)
        self._progress = open(os.path.join(path, PROGRESS_FILE), "w")

    @staticmethod
    def _load(path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def transcripts_dir(self, pattern_id: int) -> str:
        return os.path.join(self.path, TRANSCRIPTS_DIR, str(pattern_id))

    def progress(self, event: str, **fields: Any) -> None:
        line = json.dumps({"event": event, **fields}, sort_keys=True)
        print(PROGRESS_PREFIX + line, flush=True)
        self._progress.write(line + "\n")
        self._progress.flush()

    def record(self, suggestion: UnsureSuggestion, outcome: Outcome) -> None:
        entry = outcome.to_dict()
        entry["start_line"] = str(suggestion.start)
        entry["end_line"] = str(suggestion.end)
        entry["blockers"] = len(suggestion.blockers)
        # which agent and settings judged it: results of several runs are kept side by side
        entry.update(self.run_info)
        self.entries[suggestion.pattern_id] = entry
        approved_dir = os.path.join(self.path, APPROVED_DIR, str(suggestion.pattern_id))
        shutil.rmtree(approved_dir, ignore_errors=True)
        if outcome.state == STATE_APPROVED and outcome.patch is not None:
            os.makedirs(approved_dir)
            for file_id, patch in sorted(outcome.patch.entries.items()):
                with open(os.path.join(approved_dir, str(file_id) + ".patch"), "w", newline="") as f:
                    f.write(patch.text)
        self.save()

    def save(self) -> None:
        suggestions = [self.entries[i] for i in sorted(self.entries)]
        self._write(
            RESULTS_FILE,
            {
                "format_version": FORMAT_VERSION,
                "explorer_output": self.fingerprint.to_dict(),
                **self.run_info,
                "suggestions": suggestions,
            },
        )
        approved: List[Dict[str, Any]] = [
            {
                "pattern_id": e["pattern_id"],
                "assumption": e.get("assumption"),
                "result_differences": e.get("result_differences"),
                "verification": e.get("verification"),
                "review": e.get("review"),
                "backend": e.get("backend"),
                "model": e.get("model"),
                "patch_dir": os.path.join(APPROVED_DIR, str(e["pattern_id"])),
            }
            for e in suggestions
            if e.get("state") == STATE_APPROVED
        ]
        self._write(
            APPROVED_FILE,
            {
                "format_version": FORMAT_VERSION,
                "note": "Approved by an LLM agent, not by DiscoPoP's analysis: each rests on the assumption stated.",
                "explorer_output": self.fingerprint.to_dict(),
                "suggestions": approved,
            },
        )

    def _write(self, name: str, data: Dict[str, Any]) -> None:
        target = os.path.join(self.path, name)
        with open(target + ".tmp", "w") as f:
            json.dump(data, f, indent=1)
            f.write("\n")
        os.replace(target + ".tmp", target)

    def close(self) -> None:
        self._progress.close()
