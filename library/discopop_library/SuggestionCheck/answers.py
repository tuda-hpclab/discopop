# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Reading the agent's answers. An answer which cannot be read is fed back for another turn; a readable rejection is
final, and an approval has to justify every blocker (design/agent_checked_suggestions.md, §5.3, §5.4)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Collection, Dict, List, Optional

from discopop_library.PatchRepair.llm_backends.base import iter_json_objects

APPROVED = "approved"
REJECTED = "rejected"
UNSURE = "unsure"
VERDICTS = (APPROVED, REJECTED, UNSURE)

AGREE = "agree"
DISAGREE = "disagree"
REVIEW_VERDICTS = (AGREE, DISAGREE)


# a cited line: path:line or path:first-last
EVIDENCE = re.compile(r"^`?(?P<file>[^\s:`]+):(?P<line>\d+)(?:-\d+)?`?$")


def _cited_lines(raw: Any, known_files: Optional[Collection[str]]) -> List[str]:
    """the entries of raw which cite a line of a known file as path:line. Anything else, e.g. a string instead of a
    list, null or "n/a", cites nothing."""
    if not isinstance(raw, list):
        return []
    cited: List[str] = []
    basenames = None if known_files is None else {os.path.basename(f) for f in known_files}
    for item in raw:
        if not isinstance(item, str):
            continue
        match = EVIDENCE.match(item.strip())
        if match is None or int(match.group("line")) < 1:
            continue
        cited_file = match.group("file")
        if known_files is not None and cited_file not in known_files and cited_file not in (basenames or set()):
            continue
        cited.append(item.strip().strip("`"))
    return cited


class AnswerError(ValueError):
    """the answer cannot be used; the message is meant for the agent"""


@dataclass
class Justification:
    index: int
    text: str
    evidence: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "justification": self.text, "evidence": list(self.evidence)}


@dataclass
class CheckAnswer:
    verdict: str
    reason: str = ""
    assumption: str = ""
    justifications: List[Justification] = field(default_factory=list)


@dataclass
class ReviewAnswer:
    verdict: str
    reason: str


def _answer_object(text: str, required_key: str) -> Dict[str, Any]:
    """the last JSON object of the answer which has required_key"""
    found: Optional[Dict[str, Any]] = None
    for obj in iter_json_objects(text or ""):
        if isinstance(obj, dict) and required_key in obj:
            found = obj
    if found is None:
        raise AnswerError(
            'The answer contains no JSON object with a "' + required_key + '" field. Answer in the format given.'
        )
    return found


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_check_answer(text: str, blocker_count: int, known_files: Optional[Collection[str]] = None) -> CheckAnswer:
    """known_files: the paths the agent was shown; evidence has to cite a line of one of them"""
    obj = _answer_object(text, "verdict")
    verdict = _text(obj.get("verdict")).lower()
    if verdict not in VERDICTS:
        raise AnswerError(
            '"verdict" must be one of ' + ", ".join('"' + v + '"' for v in VERDICTS) + ", not " + repr(verdict) + "."
        )
    reason = _text(obj.get("reason"))
    if verdict != APPROVED:
        # final either way: a rejection is never argued with
        return CheckAnswer(verdict=verdict, reason=reason or "(no reason given)")

    problems: List[str] = []
    assumption = _text(obj.get("assumption"))
    if not assumption:
        problems.append('An approval must state the assumption it rests on ("assumption").')

    justifications: Dict[int, Justification] = {}
    raw = obj.get("blockers")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        evidence = _cited_lines(item.get("evidence"), known_files)
        justifications[index] = Justification(index, _text(item.get("justification")), evidence)
    for index in range(1, blocker_count + 1):
        given = justifications.get(index)
        if given is None or not given.text:
            problems.append("Blocker " + str(index) + " has no justification.")
        elif not given.evidence:
            problems.append(
                "The justification of blocker "
                + str(index)
                + ' cites no code: "evidence" must list lines of the files shown, as path:line.'
            )
    unknown = sorted(i for i in justifications if not 1 <= i <= blocker_count)
    if unknown:
        problems.append("There is no blocker " + ", ".join(str(i) for i in unknown) + ".")

    if problems:
        raise AnswerError(
            "The approval is incomplete:\n"
            + "\n".join("- " + p for p in problems)
            + '\nAn approval must justify every blocker with code, or the answer must be "rejected" or '
            '"unsure".'
        )
    return CheckAnswer(
        verdict=APPROVED,
        reason=reason,
        assumption=assumption,
        justifications=[justifications[i] for i in range(1, blocker_count + 1)],
    )


def parse_review_answer(text: str) -> ReviewAnswer:
    obj = _answer_object(text, "verdict")
    verdict = _text(obj.get("verdict")).lower()
    if verdict not in REVIEW_VERDICTS:
        raise AnswerError(
            '"verdict" must be one of '
            + ", ".join('"' + v + '"' for v in REVIEW_VERDICTS)
            + ", not "
            + repr(verdict)
            + "."
        )
    return ReviewAnswer(verdict=verdict, reason=_text(obj.get("reason")) or "(no reason given)")
