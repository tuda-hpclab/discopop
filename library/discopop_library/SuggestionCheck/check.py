# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Checking one unsure suggestion: the agent works in a copy of the project, DiscoPoP computes the patch from its
changes, applies the gates and has an approval reviewed (design/agent_checked_suggestions.md, §5). The agent is a
callable, so the logic is tested without a model."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from discopop_library.PatchRepair.patchset import PatchSet
from discopop_library.SuggestionCheck.answers import (
    AGREE,
    APPROVED,
    AnswerError,
    Justification,
    parse_check_answer,
    parse_review_answer,
)
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.prompts import check_prompt, retry_prompt, review_prompt
from discopop_library.SuggestionCheck.unsure import UnsureSuggestion
from discopop_library.SuggestionCheck.workspace import Changes, Workspace, patch_of

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


# (prompt, session to continue or None, the directory the agent works in) -> reply
Agent = Callable[[str, Optional[str], str], AgentReply]


@dataclass
class Budget:
    # independent attempts, each with a fresh conversation and a fresh copy of the project
    prompts: int = 2
    # follow-up turns inside one attempt, for answers or changes which cannot be used
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
            "changed_files": sorted(self.patch.entries) if self.patch is not None else [],
            "calls": self.calls,
            "unanswered": self.unanswered,
            "gates": self.gates,
        }


class _Unreachable(Exception):
    pass


class _Conversation:
    """the calls of one role, with the transcripts, the allowance for calls without an answer and the check that the
    project itself did not change"""

    def __init__(
        self,
        agent: Agent,
        outcome: Outcome,
        budget: Budget,
        artifacts: Optional[str],
        role: str,
        guard: Optional[Callable[[], None]],
    ) -> None:
        self.agent = agent
        self.outcome = outcome
        self.budget = budget
        self.artifacts = artifacts
        self.role = role
        self.guard = guard

    def ask(self, prompt: str, session: Optional[str], workdir: str, name: str) -> AgentReply:
        while True:
            self.outcome.calls += 1
            self._write(name + "_prompt.txt", prompt)
            reply = self.agent(prompt, session, workdir)
            if self.guard is not None:
                # raises ProjectChanged, which ends the whole run
                self.guard()
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


# an OpenMP directive which makes the following loop a parallel or worksharing loop
_LOOP_DIRECTIVE = re.compile(r"^#\s*pragma\s+omp\s+(?:parallel\s+)?for\b")


def directive_at_loop(code: str, header: str) -> bool:
    """whether, in code, a line equal to the loop's header line is directly preceded by a parallel for directive. A
    directive elsewhere, in a comment or on another loop does not count."""
    lines = [line.strip() for line in code.splitlines()]
    for index, line in enumerate(lines):
        if not header or line != header:
            continue
        previous = index - 1
        while previous >= 0 and not lines[previous]:
            previous -= 1
        if previous >= 0 and _LOOP_DIRECTIVE.match(lines[previous]):
            return True
    return False


def change_gates(changes: Changes, suggestion: UnsureSuggestion, files: SourceFiles) -> Tuple[Optional[PatchSet], str]:
    """(the patch, "") if the agent's changes are usable, otherwise (None, why) for the agent"""
    if changes.unmapped:
        return None, (
            "Only source files of the project may change, and no file may be added or removed. These cannot be "
            "part of the change: " + ", ".join(changes.unmapped) + ". Undo these changes."
        )
    loop_file = suggestion.start.file_id
    if loop_file in changes.mapped:
        code = changes.mapped[loop_file]
    else:
        code = "\n".join(files.lines(loop_file))
    if not directive_at_loop(code, files.line_text(suggestion.start)):
        return None, (
            "The loop at "
            + files.where(suggestion.start)
            + " (`"
            + files.line_text(suggestion.start)
            + "`) is not directly preceded by its OpenMP directive (`#pragma omp parallel for ...`), or its header "
            "line was changed. Add the directive directly before the loop and keep the header line as it is."
        )
    return patch_of(changes.mapped, files, suggestion.pattern_id), ""


def check_suggestion(
    suggestion: UnsureSuggestion,
    files: SourceFiles,
    project_root: str,
    agent: Agent,
    reviewer: Optional[Agent],
    budget: Budget,
    artifacts: Optional[str] = None,
    guard: Optional[Callable[[], None]] = None,
) -> Outcome:
    """asks the agent, applies the gates and, for an approval, the review. Never approves without a usable,
    complete answer: anything else is a rejection or a failure."""
    outcome = Outcome(pattern_id=suggestion.pattern_id, state=STATE_FAILED)
    conversation = _Conversation(agent, outcome, budget, artifacts, "check", guard)
    known_files = [files.display_path(i) for i in sorted(files.file_mapping)]
    last_problem = ""
    try:
        for attempt in range(1, budget.prompts + 1):
            workspace = Workspace(project_root, files)
            try:
                message = check_prompt(suggestion, files)
                session: Optional[str] = None
                for turn in range(budget.retries + 1):
                    reply = conversation.ask(message, session, workspace.root, str(attempt) + "_" + str(turn))
                    session = reply.session
                    try:
                        answer = parse_check_answer(reply.text, len(suggestion.blockers), known_files)
                        failure = ""
                    except AnswerError as error:
                        failure = str(error)
                    if not failure:
                        outcome.verdict = answer.verdict
                        if answer.verdict != APPROVED:
                            outcome.state = STATE_REJECTED
                            outcome.reason = answer.reason
                            return outcome
                        changes = workspace.changes()
                        patch, failure = change_gates(changes, suggestion, files)
                    if failure:
                        outcome.gates.append({"attempt": attempt, "turn": turn, "detail": failure})
                        last_problem = failure
                        outcome.verdict = None
                        if session is None:
                            # a follow-up turn needs the conversation: on its own, it would ask about nothing
                            outcome.gates.append({"attempt": attempt, "turn": turn, "detail": "no session to continue"})
                            break
                        message = retry_prompt(failure)
                        continue
                    assert patch is not None
                    outcome.assumption = answer.assumption
                    outcome.justifications = answer.justifications
                    outcome.patch = patch
                    return _review(
                        suggestion, files, project_root, changes.mapped, reviewer, budget, artifacts, guard, outcome
                    )
            finally:
                workspace.remove()
        outcome.reason = "no usable answer within the attempt budget" + (
            "; the last problem: " + last_problem if last_problem else ""
        )
    except _Unreachable as error:
        outcome.reason = "the agent did not answer: " + str(error)
    # nothing of an approval which did not pass survives
    outcome.state = STATE_FAILED
    outcome.verdict = None
    outcome.assumption = ""
    outcome.justifications = []
    outcome.review = None
    outcome.patch = None
    return outcome


def _review(
    suggestion: UnsureSuggestion,
    files: SourceFiles,
    project_root: str,
    changed_code: Dict[int, str],
    reviewer: Optional[Agent],
    budget: Budget,
    artifacts: Optional[str],
    guard: Optional[Callable[[], None]],
    outcome: Outcome,
) -> Outcome:
    assert outcome.patch is not None
    if reviewer is None:
        outcome.state = STATE_APPROVED
        outcome.verification = VERIFICATION_STATIC
        return outcome
    conversation = _Conversation(reviewer, outcome, budget, artifacts, "review", guard)
    message = review_prompt(suggestion, outcome.patch, files, outcome.assumption, outcome.justifications)
    workspace = Workspace(project_root, files)
    try:
        workspace.write(changed_code)
        session: Optional[str] = None
        for turn in range(budget.retries + 1):
            reply = conversation.ask(message, session, workspace.root, str(turn))
            session = reply.session
            try:
                review = parse_review_answer(reply.text)
            except AnswerError as error:
                outcome.gates.append({"review_turn": turn, "detail": str(error)})
                if session is None:
                    # a follow-up turn without the conversation would review nothing
                    break
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
    finally:
        workspace.remove()
    # a review which cannot be read is not an agreement
    outcome.state = STATE_REJECTED
    outcome.reason = "the review gave no usable answer"
    outcome.patch = None
    return outcome
