# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the Suggestion Check tab shows, as data: the unsure suggestions, table rows, details, transcripts, summaries.

Toolkit independent; the colors are named by a tone (``TONE_*``) that each toolkit maps to its status colors. The
files are those of ``discopop_suggestion_check`` (``SuggestionCheck/results.py``): ``suggestion_check/results.json``
(a list of entries with an integer ``pattern_id``), ``approved/<id>/<file id>.patch`` and ``transcripts/<id>/``.
Publishing (``SuggestionCheck/publish.py``) is imported where it is used: it pulls in the check itself.
"""

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.services.selections import parse_id_ranges

# the connection selector and the backend line are shared with the Patch Repair tab (llm_connection_view); the names
# stay importable from here
from discopop_library.ProjectManager.services.llm_connection_view import (  # noqa: F401
    NO_CONNECTION as NO_CONNECTION,
    ConnectionInfo as ConnectionInfo,
    backend_description as backend_description,
    connection_choices as connection_choices,
    llm_config_path as llm_config_path,
    load_connections as load_connections,
    manual_choice_note as manual_choice_note,
    resolve_connection as resolve_connection,
)
from discopop_library.SuggestionCheck.unsure import UNSURE_SUGGESTIONS_FILE, Fingerprint

if TYPE_CHECKING:
    from discopop_library.SuggestionCheck.publish import PublishResult

TONE_IDLE = "idle"
TONE_BUSY = "busy"
TONE_OK = "ok"
TONE_FAIL = "fail"
TONE_STOP = "stop"

# the states of check.py (STATE_*), repeated here so that reading the results does not import the check
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"
STATE_FAILED = "failed"
# the verdict of an agent that could not decide (answers.UNSURE); recorded as a rejection
VERDICT_UNSURE = "unsure"

STATE_LABEL_APPROVED = "Approved"
STATE_LABEL_REJECTED = "Rejected"
STATE_LABEL_UNSURE = "Unsure"
STATE_LABEL_ERROR = "Error"
# candidates without a result: a suggestion the check has not looked at, or the hotspot filter skipped
STATE_PENDING = "pending"
STATE_SKIPPED = "skipped"
STATE_LABEL_PENDING = "Not checked"
STATE_LABEL_SKIPPED = "Skipped (cold)"

DIRECTORY = "suggestion_check"
RESULTS_FILE = "results.json"
TRANSCRIPTS_DIR = "transcripts"
APPROVED_DIR = "approved"

# what every approval is, said wherever one can be used
AGENT_NOTE = (
    "An approval is an LLM agent's judgement, not DiscoPoP's analysis: it holds only if the agent's assumption "
    "holds for your program."
)


# ── files ────────────────────────────────────────────────────────────────────


def check_dir(dot_dp: str) -> str:
    return os.path.join(dot_dp, DIRECTORY)


def results_path(dot_dp: str) -> str:
    return os.path.join(check_dir(dot_dp), RESULTS_FILE)


def unsure_path(dot_dp: str) -> str:
    return os.path.join(dot_dp, UNSURE_SUGGESTIONS_FILE)


def has_unsure_suggestions(dot_dp: str) -> bool:
    return os.path.isfile(unsure_path(dot_dp))


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sort_key(suggestion_id: str) -> Tuple[int, str]:
    """Numeric order where possible, so 10 does not sort before 2."""
    try:
        return (int(suggestion_id), "")
    except ValueError:
        return (1 << 30, suggestion_id)


def load_document(dot_dp: str) -> Optional[Dict[str, Any]]:
    """``results.json`` as a whole; None without a readable file."""
    return _read_json(results_path(dot_dp))


def records_of(document: Optional[Dict[str, Any]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """The entries of a ``results.json`` by suggestion id (as a string)."""
    if document is None or not isinstance(document.get("suggestions"), list):
        return None
    records: Dict[str, Dict[str, Any]] = {}
    for entry in document["suggestions"]:
        if isinstance(entry, dict) and "pattern_id" in entry:
            records[str(entry["pattern_id"])] = dict(entry)
    return records


def load_results(dot_dp: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """The checked suggestions by id (as a string); None without a readable ``results.json``."""
    return records_of(load_document(dot_dp))


def skipped_by_hotspot(document: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(suggestion id, hotspot type) of the suggestions the last run skipped by its hotspot filter."""
    if document is None or not isinstance(document.get("skipped_by_hotspot"), list):
        return []
    return [
        (str(entry["pattern_id"]), str(entry.get("hotspot_type") or ""))
        for entry in document["skipped_by_hotspot"]
        if isinstance(entry, dict) and "pattern_id" in entry
    ]


def skipped_text(skipped: Sequence[Tuple[str, str]]) -> str:
    """The line under the results naming the suggestions the hotspot filter skipped; "" if none."""
    if not skipped:
        return ""
    return (
        "Skipped (cold): "
        + ", ".join(i + " (" + t.upper() + ")" for i, t in skipped)
        + ". Their hotspot type was not selected; name them in the scope to check them anyway."
    )


def results_are_stale(dot_dp: str, document: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the results belong to another explorer run than the unsure suggestions there are now: the explorer
    numbers the loops anew, so an id may name another loop."""
    if document is None:
        document = load_document(dot_dp)
    if document is None:
        return False
    path = unsure_path(dot_dp)
    if not os.path.isfile(path):
        return True
    return bool(document.get("explorer_output") != Fingerprint.of(path).to_dict())


@dataclass(frozen=True)
class UnsureEntry:
    """One unsure suggestion of ``explorer/unsure_suggestions.json``, as far as the tab shows it."""

    suggestion_id: str
    pattern_type: str = ""
    start_line: str = ""  # "file_id:line"
    pragma: str = ""
    blockers: Tuple[Dict[str, Any], ...] = ()
    end_line: str = ""  # "file_id:line"


def load_unsure(dot_dp: str) -> Dict[str, UnsureEntry]:
    """The unsure suggestions by id (as a string); empty without a readable file."""
    data = _read_json(unsure_path(dot_dp))
    result: Dict[str, UnsureEntry] = {}
    if data is None or not isinstance(data.get("suggestions"), list):
        return result
    for entry in data["suggestions"]:
        if not isinstance(entry, dict) or "pattern_id" not in entry:
            continue
        suggestion_id = str(entry["pattern_id"])
        blockers = tuple(b for b in (entry.get("blockers") or []) if isinstance(b, dict))
        result[suggestion_id] = UnsureEntry(
            suggestion_id,
            str(entry.get("type") or ""),
            str(entry.get("start_line") or ""),
            str(entry.get("pragma") or ""),
            blockers,
            str(entry.get("end_line") or ""),
        )
    return result


def hotspot_classes(dot_dp: str, unsure: Dict[str, UnsureEntry]) -> Dict[str, str]:
    """The hotspot class (YES, MAYBE, NO) of each unsure suggestion that one hotspot loop of the results starts in,
    by the rule the check's hotspot filter applies (SuggestionCheck/hotspots.py). Empty without hotspot results;
    a suggestion no hotspot loop starts in is left out."""
    # imported here: the hotspot loader reads the project's files
    from discopop_library.HostpotLoader.utilities import classify_by_loops, hotspot_loops
    from discopop_library.SuggestionCheck.hotspots import load

    try:
        information = load(dot_dp)
    except Exception:  # the results of the hotspot detection are optional here
        return {}
    if not information:
        return {}
    loops = hotspot_loops(information)
    classes: Dict[str, str] = {}
    for suggestion_id, entry in unsure.items():
        try:
            file_text, _, line_text = entry.start_line.partition(":")
            end_text = entry.end_line.partition(":")[2] or line_text
            found = classify_by_loops(int(file_text), int(line_text), int(end_text), loops)
        except ValueError:
            continue
        if found is not None:
            classes[suggestion_id] = found.name
    return classes


def unsure_ids(dot_dp: str) -> List[str]:
    return sorted(load_unsure(dot_dp), key=sort_key)


def read_file_mapping(dot_dp: str) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    try:
        with open(os.path.join(dot_dp, "FileMapping.txt"), "r") as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
        return mapping
    for line in lines:
        file_id, _, path = line.partition("\t")
        if file_id.strip().isdigit() and path.strip():
            mapping[int(file_id)] = path.strip()
    return mapping


def location_text(value: Any, file_mapping: Dict[int, str]) -> str:
    """``"<file id>:<line>"`` as ``file.cpp:12``; the raw value if the file id is unknown, "" if there is none."""
    text = str(value or "")
    file_id, separator, line = text.partition(":")
    if not separator:
        return text
    try:
        path = file_mapping.get(int(file_id))
    except ValueError:
        return text
    return (os.path.basename(path) + ":" + line) if path else text


# ── the scope ────────────────────────────────────────────────────────────────


def parse_scope(text: str, available: Sequence[str]) -> Optional[Tuple[str, ...]]:
    """The ids of a ``1,3,5-8`` spec that are unsure suggestions, in numeric order; None for an empty spec (all).

    The check takes explicit integers and refuses an id that is not an unsure suggestion, so ranges are expanded and
    unknown ids are left out here.
    """
    if not text.strip():
        return None
    return tuple(sorted(parse_id_ranges(text, list(available)), key=sort_key))


def scope_text(scope: Optional[Tuple[str, ...]], available: Sequence[str]) -> str:
    """What the scope field currently selects, for the caption below it."""
    if not available:
        return "No unsure suggestions: run the pattern detection with unsure suggestions enabled."
    if scope is None:
        return "All " + str(len(available)) + " unsure suggestion(s): " + ", ".join(available)
    if not scope:
        return "None of the available unsure suggestions matches (" + ", ".join(available) + ")."
    return str(len(scope)) + " of " + str(len(available)) + " selected: " + ", ".join(scope)


# ── the table ────────────────────────────────────────────────────────────────


def state_display(record: Dict[str, Any]) -> Tuple[str, str]:
    """(label, tone) of a checked suggestion: Approved, Rejected, Unsure (an agent that could not decide is recorded
    as a rejection) or Error (no usable answer)."""
    state = str(record.get("state") or "")
    if state == STATE_APPROVED:
        return STATE_LABEL_APPROVED, TONE_OK
    if state == STATE_REJECTED:
        if record.get("verdict") == VERDICT_UNSURE:
            return STATE_LABEL_UNSURE, TONE_STOP
        return STATE_LABEL_REJECTED, TONE_IDLE
    if state == STATE_FAILED:
        return STATE_LABEL_ERROR, TONE_FAIL
    return (state or "unknown"), TONE_IDLE


def review_verdict(record: Dict[str, Any]) -> str:
    """The reviewer's verdict: from the recorded review, else told by the state and the reason.

    Results written before the setting was called ``review_enabled`` stored it under ``review``, replacing the
    review itself; then the verdict is derived as the check does it.
    """
    review = record.get("review")
    if isinstance(review, dict):
        return str(review.get("verdict") or "")
    if review is False or record.get("review_enabled") is False:
        return "off"
    state = str(record.get("state") or "")
    reason = str(record.get("reason") or "")
    if state == STATE_APPROVED:
        return "agree"
    if reason.startswith("the review disagreed"):
        return "disagree"
    if reason.startswith("the review gave no usable answer"):
        return "no answer"
    return ""


def cost_text(record: Dict[str, Any]) -> str:
    """The cost of the agent calls, if the check recorded one (it does not so far)."""
    for key in ("cost", "cost_usd", "total_cost_usd"):
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "$" + format(float(value), ".4f")
    return ""


@dataclass(frozen=True)
class ResultRow:
    suggestion_id: str
    location: str
    state: str
    state_label: str
    tone: str
    result_differences: str
    tool_calls: str
    review: str
    model: str
    cost: str
    published: bool = False
    blockers: str = ""
    hotspot: str = ""

    def cells(self) -> Tuple[str, ...]:
        state = self.state_label + (" (in use)" if self.published else "")
        return (
            self.suggestion_id,
            self.location,
            self.blockers,
            self.hotspot,
            state,
            self.result_differences,
            self.tool_calls,
            self.review,
            self.model,
            self.cost,
        )


COLUMNS = (
    "Suggestion",
    "Location",
    "Blockers",
    "Hotspot",
    "State",
    "Result differences",
    "Tool calls",
    "Review",
    "Model",
    "Cost",
)


def result_rows(
    records: Dict[str, Dict[str, Any]],
    file_mapping: Dict[int, str],
    published: Sequence[str] = (),
    candidates: Optional[Dict[str, UnsureEntry]] = None,
    skipped: Sequence[Tuple[str, str]] = (),
    hotspots: Optional[Dict[str, str]] = None,
) -> List[ResultRow]:
    """One row per checked suggestion and, given the ``candidates`` (the unsure suggestions), one per candidate
    without a result: "Not checked", or "Skipped (cold)" if the hotspot filter skipped it. Without candidates only
    the results are listed."""
    candidates = candidates or {}
    hotspots = hotspots or {}
    cold = dict(skipped)
    rows = []
    for suggestion_id in sorted(set(records) | set(candidates), key=sort_key):
        entry = candidates.get(suggestion_id)
        blockers = str(len(entry.blockers)) if entry is not None else ""
        hotspot = hotspots.get(suggestion_id, "")
        record = records.get(suggestion_id)
        if record is None:
            skipped_type = cold.get(suggestion_id)
            label = STATE_LABEL_SKIPPED if skipped_type is not None else STATE_LABEL_PENDING
            state = STATE_SKIPPED if skipped_type is not None else STATE_PENDING
            location = location_text(entry.start_line, file_mapping) if entry is not None else ""
            rows.append(
                ResultRow(
                    suggestion_id, location, state, label, TONE_IDLE, "", "", "", "", "", False, blockers, hotspot
                )
            )
            continue
        label, tone = state_display(record)
        differences = record.get("result_differences")
        model = str(record.get("model") or "")
        backend = str(record.get("backend") or "")
        location = location_text(record.get("start_line"), file_mapping)
        if not location and entry is not None:
            location = location_text(entry.start_line, file_mapping)
        rows.append(
            ResultRow(
                suggestion_id,
                location,
                str(record.get("state") or ""),
                label,
                tone,
                str(differences) if differences else "",
                str(record.get("tool_calls") or 0),
                review_verdict(record),
                model or (backend + " (default)" if backend else ""),
                cost_text(record),
                suggestion_id in published,
                blockers,
                hotspot,
            )
        )
    return rows


def has_cost(rows: Sequence[ResultRow]) -> bool:
    return any(row.cost for row in rows)


def preferred_row(rows: Sequence[ResultRow], previous: Optional[str]) -> Optional[str]:
    """The suggestion to select after a refresh: the previous one, else an approved one, else the first."""
    ids = [row.suggestion_id for row in rows]
    if not ids:
        return None
    if previous in ids:
        return previous
    return next((row.suggestion_id for row in rows if row.state == STATE_APPROVED), ids[0])


# ── the details ──────────────────────────────────────────────────────────────


def blocker_text(blocker: Dict[str, Any], file_mapping: Dict[int, str]) -> str:
    """One blocker of the explorer in a line: its type, source and sink, the data involved and its origin."""
    variables = sorted(
        {str(a.get("variable")) for a in (blocker.get("accesses") or []) if isinstance(a, dict) and a.get("variable")}
    )
    text = (
        str(blocker.get("type") or "data")
        + " dependency "
        + location_text(blocker.get("source_line"), file_mapping)
        + " -> "
        + location_text(blocker.get("sink_line"), file_mapping)
    )
    if variables:
        text += " on " + ", ".join(variables)
    if blocker.get("origin"):
        text += " (" + str(blocker.get("origin")) + ")"
    return text


def candidate_text(
    suggestion_id: str,
    unsure: Optional[UnsureEntry],
    file_mapping: Dict[int, str],
    skipped_type: Optional[str] = None,
    hotspot: str = "",
) -> str:
    """What the Details tab shows of an unsure suggestion that has no result: what the check would look at."""
    if skipped_type is not None:
        status = "skipped by the hotspot filter (hotspot type " + skipped_type.upper() + ")"
    else:
        status = "not checked yet"
    lines = ["Suggestion " + suggestion_id + ": " + status]
    if unsure is None:
        return "\n".join(lines)
    location = location_text(unsure.start_line, file_mapping)
    if location:
        lines.append("Loop: " + location)
    if unsure.pattern_type:
        lines.append("Pattern type: " + unsure.pattern_type)
    if hotspot:
        lines.append("Hotspot: " + hotspot)
    if unsure.pragma:
        lines.append("Directive without the blockers: " + unsure.pragma)
    lines.append("")
    if unsure.blockers:
        lines.append("Blockers (dependencies between iterations that keep DiscoPoP from suggesting it):")
        for index, blocker in enumerate(unsure.blockers, start=1):
            lines.append("  " + str(index) + ". " + blocker_text(blocker, file_mapping))
    else:
        lines.append("No blockers recorded.")
    return "\n".join(lines)


def detail_text(
    suggestion_id: Optional[str],
    record: Optional[Dict[str, Any]],
    unsure: Optional[UnsureEntry],
    file_mapping: Dict[int, str],
    marker: Optional[Dict[str, Any]] = None,
    skipped_type: Optional[str] = None,
    hotspot: str = "",
) -> str:
    """What the Details tab shows of a checked suggestion: the outcome with its reason, or for an approval the
    assumption and the justification of every blocker, then how the check went."""
    if suggestion_id is None:
        return "(select a suggestion in the Results tab)"
    if record is None:
        return candidate_text(suggestion_id, unsure, file_mapping, skipped_type, hotspot)
    label, _tone = state_display(record)
    lines = ["Suggestion " + suggestion_id + ": " + label]
    if hotspot:
        lines.append("Hotspot: " + hotspot)
    location = location_text(record.get("start_line"), file_mapping)
    if location:
        end_line = str(record.get("end_line") or "").partition(":")[2]
        lines.append("Loop: " + location + (" to line " + end_line if end_line else ""))
    if unsure is not None and unsure.pragma:
        lines.append("Directive without the blockers: " + unsure.pragma)
    if marker is not None:
        lines.append("In use: published to patch_generator/" + suggestion_id + " (Withdraw takes it back).")
    lines.append("")
    if record.get("state") == STATE_APPROVED:
        lines.append(AGENT_NOTE)
        lines.append("")
        lines.append("Assumption: " + (str(record.get("assumption") or "") or "(none stated)"))
        lines.append("Result differences: " + str(record.get("result_differences") or "none"))
        lines.append("")
        blockers = list(unsure.blockers) if unsure is not None else []
        justifications = [j for j in (record.get("justifications") or []) if isinstance(j, dict)]
        if justifications:
            lines.append("Justifications of the blockers:")
        for justification in sorted(justifications, key=lambda j: int(j.get("index") or 0)):
            index = int(justification.get("index") or 0)
            heading = "  Blocker " + str(index)
            # the agent numbers the blockers from 1, in the order of the explorer
            if 1 <= index <= len(blockers):
                heading += ": " + blocker_text(blockers[index - 1], file_mapping)
            lines.append(heading)
            lines.append("    " + str(justification.get("justification") or ""))
            evidence = [str(e) for e in (justification.get("evidence") or [])]
            if evidence:
                lines.append("    Evidence: " + ", ".join(evidence))
    else:
        lines.append("Reason: " + (str(record.get("reason") or "") or "(none given)"))
        if unsure is not None and unsure.blockers:
            lines.append("")
            lines.append("Blockers:")
            for index, blocker in enumerate(unsure.blockers, start=1):
                lines.append("  " + str(index) + ". " + blocker_text(blocker, file_mapping))
    lines.append("")
    review = record.get("review")
    if isinstance(review, dict):
        lines.append("Review: " + str(review.get("verdict") or "") + " - " + str(review.get("reason") or ""))
    else:
        verdict = review_verdict(record)
        if verdict:
            lines.append("Review: " + verdict)
    lines.append(
        "Agent calls: "
        + str(record.get("calls") or 0)
        + " (unanswered: "
        + str(record.get("unanswered") or 0)
        + "), tool calls: "
        + str(record.get("tool_calls") or 0)
    )
    read = record.get("read_blocker_files")
    if read is not None:
        lines.append("Opened the files of the blockers: " + ("yes" if read else "no"))
    agent = " / ".join(str(record.get(k)) for k in ("backend", "model") if record.get(k))
    if agent:
        lines.append("Agent: " + agent)
    gates = [g for g in (record.get("gates") or []) if isinstance(g, dict)]
    if gates:
        lines.append("")
        lines.append("Answers sent back:")
        for gate in gates:
            where = ", ".join(k + " " + str(gate[k]) for k in ("attempt", "turn", "review_turn") if k in gate)
            lines.append("  [" + where + "] " + str(gate.get("detail") or ""))
    return "\n".join(lines)


def assumption_text(records: Dict[str, Dict[str, Any]], ids: Sequence[str]) -> str:
    """The assumptions the approvals ``ids`` rest on, for the line next to the publish button."""
    parts = []
    for suggestion_id in ids:
        record = records.get(suggestion_id) or {}
        if record.get("state") != STATE_APPROVED:
            continue
        assumption = str(record.get("assumption") or "") or "(none stated)"
        differences = str(record.get("result_differences") or "")
        part = suggestion_id + ": " + assumption
        if differences and differences != "none":
            part += " [results may differ by " + differences + "]"
        parts.append(part)
    if not parts:
        return "Select an approved suggestion to read the assumption it rests on."
    return "Rests on the agent's assumption - " + "; ".join(parts)


# ── the patch and the transcripts ────────────────────────────────────────────


def approved_patch_files(dot_dp: str, suggestion_id: str) -> List[str]:
    """File ids of the patches of an approval (``approved/<id>/<file id>.patch``)."""
    directory = os.path.join(check_dir(dot_dp), APPROVED_DIR, suggestion_id)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return sorted((e[: -len(".patch")] for e in entries if e.endswith(".patch")), key=sort_key)


def read_or(path: str, fallback: str) -> str:
    try:
        with open(path, "r", newline="") as f:
            return f.read()
    except OSError:
        return fallback


def patch_text(dot_dp: str, suggestion_id: Optional[str], file_id: str, record: Optional[Dict[str, Any]]) -> str:
    """The text of the Patch tab: the approved patch of a file, or why there is none."""
    if suggestion_id is None:
        return "(select a suggestion in the Results tab)"
    if not file_id:
        if record is not None and record.get("state") != STATE_APPROVED:
            return "(suggestion " + suggestion_id + " was not approved, so it has no patch)"
        return "(no patch files found for suggestion " + suggestion_id + ")"
    path = os.path.join(check_dir(dot_dp), APPROVED_DIR, suggestion_id, file_id + ".patch")
    return read_or(path, "(no patch found)")


def transcript_files(dot_dp: str, suggestion_id: str) -> List[str]:
    """The text files of a suggestion's transcript in the order of the calls: the check's attempts and turns, then
    the review; per call the prompt, the answer and the tool calls."""
    directory = os.path.join(check_dir(dot_dp), TRANSCRIPTS_DIR, suggestion_id)
    try:
        entries = [e for e in os.listdir(directory) if e.endswith(".txt")]
    except OSError:
        return []
    kinds = {"prompt": 0, "answer": 1, "tools": 2}

    def key(name: str) -> Tuple[Any, ...]:
        stem = name[: -len(".txt")]
        parts = stem.split("_")
        role = 0 if parts[0] == "check" else 1
        numbers = tuple(int(p) for p in parts[1:-1] if p.isdigit())
        return (role, numbers, kinds.get(parts[-1], 3), stem)

    return sorted(entries, key=key)


def transcript_text(dot_dp: str, suggestion_id: Optional[str], name: str) -> str:
    if suggestion_id is None:
        return "(select a suggestion in the Results tab)"
    if not name:
        return "(no transcript recorded for suggestion " + suggestion_id + ")"
    return read_or(os.path.join(check_dir(dot_dp), TRANSCRIPTS_DIR, suggestion_id, name), "(cannot be read)")


# ── publishing ───────────────────────────────────────────────────────────────


@dataclass
class PublishPlan:
    """What a click on "Use approved suggestions" resp. "Withdraw" acts on."""

    ids: List[str] = field(default_factory=list)
    label: str = ""


def approved_ids(records: Dict[str, Dict[str, Any]]) -> List[str]:
    return sorted((i for i, r in records.items() if r.get("state") == STATE_APPROVED), key=sort_key)


def publish_plan(records: Dict[str, Dict[str, Any]], selected: Sequence[str]) -> PublishPlan:
    """The approved rows among the selected ones, or all approved ones if no approved row is selected."""
    approved = approved_ids(records)
    chosen = [i for i in approved if i in selected]
    if chosen:
        return PublishPlan(chosen, "Use approved suggestion" + ("s " if len(chosen) > 1 else " ") + ", ".join(chosen))
    if approved:
        return PublishPlan(approved, "Use all approved suggestions (" + str(len(approved)) + ")")
    return PublishPlan([], "Use approved suggestions")


def withdraw_plan(published: Sequence[str], selected: Sequence[str]) -> PublishPlan:
    """The published rows among the selected ones, or all published ones if none of them is selected."""
    chosen = [i for i in published if i in selected]
    if chosen:
        return PublishPlan(chosen, "Withdraw " + ", ".join(chosen))
    if published:
        return PublishPlan(list(published), "Withdraw all (" + str(len(published)) + ")")
    return PublishPlan([], "Withdraw")


def published_suggestions(dot_dp: str) -> List[str]:
    from discopop_library.SuggestionCheck.publish import published_ids

    return [str(i) for i in published_ids(dot_dp)]


def marker(dot_dp: str, suggestion_id: str) -> Optional[Dict[str, Any]]:
    from discopop_library.SuggestionCheck.publish import marker_of

    if not suggestion_id.isdigit():
        return None
    return marker_of(dot_dp, int(suggestion_id))


def publish(dot_dp: str, ids: Sequence[str]) -> "PublishResult":
    from discopop_library.SuggestionCheck.publish import publish_approved

    return publish_approved(dot_dp, [int(i) for i in ids])


def withdraw(dot_dp: str, ids: Sequence[str]) -> List[str]:
    from discopop_library.SuggestionCheck.publish import withdraw_published

    return [str(i) for i in withdraw_published(dot_dp, [int(i) for i in ids])]


def publish_message(result: "PublishResult") -> str:
    """The outcome of publishing, with the reason of every suggestion that was not published."""
    lines = []
    if result.published:
        lines.append(
            "Now in use: "
            + ", ".join(map(str, result.published))
            + ". They are in patch_generator/ and appear among the suggestions, marked as agent-approved."
        )
    for pattern_id, reason in sorted(result.skipped.items()):
        lines.append("Not used " + str(pattern_id) + ": " + reason)
    return "\n".join(lines) or "Nothing to publish."


def confirm_publish_text(records: Dict[str, Dict[str, Any]], ids: Sequence[str]) -> str:
    """The question before publishing: what using an approval means."""
    lines = [
        "Make suggestion(s) " + ", ".join(ids) + " usable by the patch applicator, the autotuner and the other stages?",
        "",
        AGENT_NOTE,
        "",
    ]
    for suggestion_id in ids:
        record = records.get(suggestion_id) or {}
        lines.append(suggestion_id + ": " + (str(record.get("assumption") or "") or "(no assumption stated)"))
        if record.get("result_differences") == "rounding":
            lines.append("   The results may differ from the sequential program by rounding.")
    return "\n".join(lines)


# ── the backend, the budget and the progress ─────────────────────────────────


def budget_text(prompts: int, retries: int, review: bool) -> str:
    calls = prompts * (1 + retries)
    text = "At most " + str(prompts) + " x (1 + " + str(retries) + ") = " + str(calls) + " agent calls per suggestion"
    if review:
        text += ", plus up to " + str(1 + retries) + " for the review"
    return text + "."


def progress_summary(event: Dict[str, Any], total: int) -> List[Tuple[str, str]]:
    """The outcome texts (text, tone) one progress event sets, in order; the last one wins. ``total`` is the number
    of suggestions the run announced."""
    kind = str(event.get("event") or "")
    if kind == "start":
        count = len(event.get("suggestions") or [])
        return [("Checking " + str(count) + " unsure suggestion(s)...", TONE_BUSY)]
    if kind == "check":
        return [("Checking suggestion " + str(event.get("pattern_id")) + " (of " + str(total) + ")...", TONE_BUSY)]
    if kind == "end":
        counts = event.get("counts") or {}
        approved = int(counts.get(STATE_APPROVED) or 0)
        rejected = int(counts.get(STATE_REJECTED) or 0)
        failed = int(counts.get(STATE_FAILED) or 0)
        tone = TONE_OK if approved else TONE_IDLE
        if failed and not approved and not rejected:
            tone = TONE_FAIL
        return [
            (
                str(approved)
                + " approved, "
                + str(rejected)
                + " rejected, "
                + str(failed)
                + " without an answer. Approvals rest on the agent's assumptions; they are put into use when "
                'the run ends unless "Use approvals right away" is off; Withdraw takes them back.',
                tone,
            )
        ]
    if kind == "aborted":
        return [
            (
                "Aborted: the project changed during the check. " + str(event.get("reason") or ""),
                TONE_FAIL,
            )
        ]
    return []
