# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the Patch Repair tab shows, as data: table rows, summaries, file labels, the stored results.

Toolkit independent; the colors are named by a tone (``TONE_*``) that each toolkit maps to its status colors.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

TONE_IDLE = "idle"
TONE_BUSY = "busy"
TONE_OK = "ok"
TONE_FAIL = "fail"
TONE_STOP = "stop"

# Status values as results.json records them, with the text and tone the table shows.
STATUS_DISPLAY: Dict[str, Tuple[str, str]] = {
    "repaired": ("Repaired", TONE_OK),
    "ok": ("Compiles", TONE_IDLE),
    "failed": ("Not repaired", TONE_FAIL),
    "not_applied": ("Patch not applicable", TONE_FAIL),
    # Its own row rather than a failure: no model ever judged this suggestion, so the
    # run says nothing about whether it could have been repaired.
    "agent_unreachable": ("Agent unreachable", TONE_STOP),
    "skipped": ("Skipped", TONE_IDLE),
}


def sort_key(suggestion_id: str) -> Tuple[int, str]:
    """Numeric order where possible, so 10 does not sort before 2."""
    try:
        return (int(suggestion_id), "")
    except ValueError:
        return (1 << 30, suggestion_id)


def results_path(dot_dp: str) -> str:
    return os.path.join(dot_dp, "patch_repair", "results.json")


def load_results(dot_dp: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """The records of ``results.json`` by suggestion id (as a string); None without a readable file."""
    path = results_path(dot_dp)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    suggestions = document.get("suggestions")
    if not isinstance(suggestions, dict):
        return None
    return {str(k): dict(v) for k, v in suggestions.items()}


@dataclass(frozen=True)
class ResultRow:
    suggestion_id: str
    hotspot: str
    status: str
    status_label: str
    tone: str
    files: str
    attempts: str
    first_error: str

    def cells(self) -> Tuple[str, str, str, str, str, str]:
        return (self.suggestion_id, self.hotspot, self.status_label, self.files, self.attempts, self.first_error)


def result_rows(records: Dict[str, Dict[str, Any]]) -> List[ResultRow]:
    rows = []
    for suggestion_id in sorted(records, key=sort_key):
        record = records[suggestion_id]
        status = str(record.get("status") or "")
        label, tone = STATUS_DISPLAY.get(status, (status or "unknown", TONE_IDLE))
        changed = record.get("changed_files") or []
        files = record.get("files") or []
        rows.append(
            ResultRow(
                suggestion_id,
                str(record.get("hotspot_type") or ""),
                status,
                label,
                tone,
                (str(len(changed)) + " / " + str(len(files))) if files else "-",
                str(record.get("attempts") or 0),
                str(record.get("first_error") or ""),
            )
        )
    return rows


def preferred_row(rows: List[ResultRow], previous: Optional[str]) -> Optional[str]:
    """The suggestion to select after a refresh: the previous one, else a repaired one, else the first."""
    ids = [row.suggestion_id for row in rows]
    if not ids:
        return None
    if previous in ids:
        return previous
    return next((row.suggestion_id for row in rows if row.status == "repaired"), ids[0])


def patch_files_on_disk(dot_dp: str, suggestion_id: str) -> List[str]:
    """File ids of the patches stored for a suggestion.

    A suggestion that already compiled, or whose patches never applied, is recorded
    without a file list, because no repair ever loaded its patch set. Its patches are
    on disk nonetheless, and are still the thing worth reading.
    """
    directory = os.path.join(dot_dp, "patch_generator", suggestion_id)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return sorted((e[: -len(".patch")] for e in entries if e.endswith(".patch")), key=sort_key)


def file_labels(record: Dict[str, Any], dot_dp: str, suggestion_id: str) -> Tuple[List[str], str]:
    """The labels of the files of a suggestion's patch set and the one to show first (``""`` if none).

    The files a repair actually rewrote are marked, so a multi-file set does not have to be inspected file by file.
    """
    files = [str(f) for f in (record.get("files") or [])]
    if not files:
        files = patch_files_on_disk(dot_dp, suggestion_id)
    changed = {str(f) for f in (record.get("changed_files") or [])}
    labels = [("file " + f + (" (changed)" if f in changed else "")) for f in files]
    if not labels:
        return [], ""
    return labels, next((label for label in labels if "(changed)" in label), labels[0])


def file_id_of_label(label: str) -> str:
    return label.replace("file ", "").replace(" (changed)", "").strip()


def read_or(path: str, fallback: str) -> str:
    try:
        with open(path, "r", newline="") as f:
            return f.read()
    except OSError:
        return fallback


def diff_texts(dot_dp: str, suggestion_id: Optional[str], file_id: str, have_records: bool) -> Tuple[str, str, str]:
    """The source caption and the texts of the "before" and "after" panes for the selected suggestion and file."""
    if not suggestion_id:
        message = "(select a suggestion in the Results tab)" if have_records else "(no results yet: run patch repair)"
        return "", message, message
    source = "Suggestion " + suggestion_id
    if not file_id:
        message = "(no patch files found for suggestion " + suggestion_id + ")"
        return source, message, message
    # The backup holds the patch as the generator produced it; it exists only for a
    # suggestion a repair actually touched.
    backup = os.path.join(dot_dp, "patch_repair", "backups", suggestion_id, file_id + ".patch")
    current = os.path.join(dot_dp, "patch_generator", suggestion_id, file_id + ".patch")
    return (
        source,
        read_or(backup, "(no backup: this patch was never modified)"),
        read_or(current, "(no patch found)"),
    )


def budget_text(prompts: int, retries: int) -> str:
    """What the current dials cost, since that is what they are for."""
    return (
        "At most "
        + str(prompts)
        + " x (1 + "
        + str(retries)
        + ") = "
        + str(prompts * (1 + retries))
        + " agent calls per suggestion."
    )


def progress_summary(event: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The outcome texts (text, tone) one progress event sets, in order; the last one wins."""
    kind = str(event.get("event") or "")
    if kind == "discovery":
        failing = event.get("failing") or []
        built = event.get("built") or []
        summaries = [
            (
                str(len(built)) + " compile, " + str(len(failing)) + " do not — repairing " + str(len(failing)) + "...",
                TONE_BUSY,
            )
        ]
        if not event.get("reference_built", True):
            summaries.append(
                ("The project does not build without any suggestion applied. Fix the build first.", TONE_FAIL)
            )
        return summaries
    if kind == "done":
        repaired = int(event.get("repaired") or 0)
        failed = int(event.get("failed") or 0)
        tone = TONE_OK if repaired and not failed else TONE_IDLE
        if failed and not repaired:
            tone = TONE_FAIL
        return [
            (
                str(repaired)
                + " repaired, "
                + str(failed)
                + " not repaired, "
                + str(event.get("considered") or 0)
                + " considered.",
                tone,
            )
        ]
    return []


def backend_description(version: str, description: str) -> str:
    return (version + " -- " if version else "") + description.split("\n")[0]
