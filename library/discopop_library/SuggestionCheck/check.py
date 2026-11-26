# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Checking one unsure suggestion: the agent's verdict, the patch gates and the review
(design/agent_checked_suggestions.md, §5). The agent is a callable, so the logic is tested without a model."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from discopop_library.PatchRepair.patching import (
    canonicalize,
    canonicalize_delta,
    check_pragmas_preserved,
    dry_run_apply,
)
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
from discopop_library.SuggestionCheck.answers import (
    AGREE,
    APPROVED,
    AnswerError,
    CheckAnswer,
    Justification,
    parse_check_answer,
    parse_review_answer,
)
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.prompts import check_prompt, retry_prompt, review_prompt
from discopop_library.SuggestionCheck.unsure import UnsureSuggestion

# the states of a checked suggestion
STATE_APPROVED = "approved"
STATE_REJECTED = "rejected"
# no usable answer: the agent was unreachable, or its answers could not be used within the budget
STATE_FAILED = "failed"

# how far an approval was verified
VERIFICATION_STATIC = "static"


@dataclass
class AgentReply:
    text: str
    # False if the call produced nothing to judge (unreachable, timeout, error of the agent itself)
    answered: bool
    failure: str = ""
    session: Optional[str] = None


# (prompt, session to continue or None) -> reply
Agent = Callable[[str, Optional[str]], AgentReply]


@dataclass
class Budget:
    # independent attempts, each with a fresh conversation
    prompts: int = 2
    # follow-up turns inside one attempt, for answers which cannot be used
    retries: int = 2
    # calls without an answer allowed per suggestion; they do not use up the budget above
    agent_error_retries: int = 2


@dataclass
class Outcome:
    pattern_id: int
    state: str
    reason: str = ""
    # the verdict of the agent: approved, rejected, unsure; None without a usable answer
    verdict: Optional[str] = None
    assumption: str = ""
    justifications: List[Justification] = field(default_factory=list)
    review: Optional[Dict[str, str]] = None
    verification: Optional[str] = None
    patch: Optional[PatchSet] = None
    # whether the approved patch differs from the plain one
    patch_changed: bool = False
    calls: int = 0
    unanswered: int = 0
    gates: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "state": self.state,
            "reason": self.reason,
            "verdict": self.verdict,
            "assumption": self.assumption,
            "justifications": [j.to_dict() for j in self.justifications],
            "review": self.review,
            "verification": self.verification,
            "patch_changed": self.patch_changed,
            "calls": self.calls,
            "unanswered": self.unanswered,
            "gates": self.gates,
        }


class _Unreachable(Exception):
    pass


class _Conversation:
    """the calls of one suggestion, with the transcripts and the allowance for calls without an answer"""

    def __init__(self, agent: Agent, outcome: Outcome, budget: Budget, artifacts: Optional[str], role: str) -> None:
        self.agent = agent
        self.outcome = outcome
        self.budget = budget
        self.artifacts = artifacts
        self.role = role

    def ask(self, prompt: str, session: Optional[str], name: str) -> AgentReply:
        while True:
            self.outcome.calls += 1
            reply = self.agent(prompt, session)
            self._write(name + "_prompt.txt", prompt)
            self._write(name + "_answer.txt", reply.text if reply.answered else "(no answer) " + reply.failure)
            if reply.answered:
                return reply
            self.outcome.unanswered += 1
            if self.outcome.unanswered > self.budget.agent_error_retries:
                raise _Unreachable(reply.failure)

    def _write(self, name: str, text: str) -> None:
        if self.artifacts is None:
            return
        os.makedirs(self.artifacts, exist_ok=True)
        with open(os.path.join(self.artifacts, self.role + "_" + name), "w") as f:
            f.write(text)


def candidate_patch(plain: PatchSet, replacements: Dict[int, str], files: SourceFiles) -> PatchSet:
    """the plain patch with the files of the answer replaced or added. A file the answer does not mention keeps its
    plain patch, so the loop's directive cannot get lost by omission."""
    candidate = PatchSet(suggestion_id=plain.suggestion_id)
    for file_id, entry in plain.entries.items():
        candidate.entries[file_id] = PatchEntry(file_id, replacements.get(file_id, entry.text), entry.target)
    for file_id, text in replacements.items():
        if file_id not in candidate.entries:
            candidate.entries[file_id] = PatchEntry(file_id, text, files.file_mapping[file_id])
    return candidate


def patch_gates(plain: PatchSet, answer: CheckAnswer, files: SourceFiles) -> Tuple[Optional[PatchSet], str]:
    """(the canonical patch, "") if the approved patch applies to the original code and keeps the loop's directive,
    otherwise (None, why) for the agent"""
    candidate = candidate_patch(plain, answer.patches, files)
    applied = dry_run_apply(candidate)
    if applied.ok:
        try:
            canonical = canonicalize(candidate)
        except ValueError as error:
            return None, str(error)
    else:
        # an answer written against the patched code instead of the original, as in patch repair
        delta = canonicalize_delta(plain, answer.patches) if set(answer.patches) <= set(plain.entries) else None
        if delta is None:
            return None, applied.message + "\nThe patch must be a unified diff against the original source."
        canonical = delta
    missing = check_pragmas_preserved(plain, canonical)
    if missing is not None:
        return None, missing + ". The patch must keep the loop's OpenMP directive."
    return canonical, ""


def check_suggestion(
    suggestion: UnsureSuggestion,
    plain: PatchSet,
    files: SourceFiles,
    agent: Agent,
    reviewer: Optional[Agent],
    budget: Budget,
    artifacts: Optional[str] = None,
) -> Outcome:
    """asks the agent, applies the gates and, for an approval, the review. Never approves without a usable,
    complete answer: anything else is a rejection or a failure."""
    outcome = Outcome(pattern_id=suggestion.pattern_id, state=STATE_FAILED)
    conversation = _Conversation(agent, outcome, budget, artifacts, "check")
    known_file_ids = sorted(files.file_mapping)
    try:
        for attempt in range(1, budget.prompts + 1):
            message = check_prompt(suggestion, plain, files)
            session: Optional[str] = None
            for turn in range(budget.retries + 1):
                name = str(attempt) + "_" + str(turn)
                reply = conversation.ask(message, session, name)
                session = reply.session
                try:
                    answer = parse_check_answer(reply.text, len(suggestion.blockers), known_file_ids)
                except AnswerError as error:
                    outcome.gates.append({"attempt": attempt, "turn": turn, "gate": "answer", "detail": str(error)})
                    message = retry_prompt(str(error))
                    continue
                outcome.verdict = answer.verdict
                if answer.verdict != APPROVED:
                    outcome.state = STATE_REJECTED
                    outcome.reason = answer.reason
                    return outcome
                canonical, failure = patch_gates(plain, answer, files)
                if canonical is None:
                    outcome.gates.append({"attempt": attempt, "turn": turn, "gate": "patch", "detail": failure})
                    message = retry_prompt(failure)
                    continue
                outcome.assumption = answer.assumption
                outcome.justifications = answer.justifications
                outcome.patch = canonical
                outcome.patch_changed = canonical.changed_against(plain) != []
                return _review(suggestion, canonical, files, reviewer, budget, artifacts, outcome)
        outcome.reason = "no usable answer within the attempt budget"
    except _Unreachable as error:
        outcome.reason = "the agent did not answer: " + str(error)
    outcome.patch = None
    return outcome


def _review(
    suggestion: UnsureSuggestion,
    approved: PatchSet,
    files: SourceFiles,
    reviewer: Optional[Agent],
    budget: Budget,
    artifacts: Optional[str],
    outcome: Outcome,
) -> Outcome:
    if reviewer is None:
        outcome.state = STATE_APPROVED
        outcome.verification = VERIFICATION_STATIC
        outcome.review = None
        return outcome
    conversation = _Conversation(reviewer, outcome, budget, artifacts, "review")
    message = review_prompt(suggestion, approved, files, outcome.assumption, outcome.justifications)
    session: Optional[str] = None
    for turn in range(budget.retries + 1):
        reply = conversation.ask(message, session, str(turn))
        session = reply.session
        try:
            review = parse_review_answer(reply.text)
        except AnswerError as error:
            outcome.gates.append({"review_turn": turn, "gate": "review answer", "detail": str(error)})
            message = retry_prompt(str(error))
            continue
        outcome.review = {"verdict": review.verdict, "reason": review.reason}
        if review.verdict == AGREE:
            outcome.state = STATE_APPROVED
            outcome.verification = VERIFICATION_STATIC
        else:
            outcome.state = STATE_REJECTED
            outcome.reason = "the review disagreed: " + review.reason
            outcome.patch = None
        return outcome
    # a review which cannot be read is not an agreement
    outcome.state = STATE_REJECTED
    outcome.reason = "the review gave no usable answer"
    outcome.patch = None
    return outcome
