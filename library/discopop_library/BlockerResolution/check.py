# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Checking one unsure suggestion: the agent works in a copy of the project, DiscoPoP computes the patch from its
changes, applies the gates and has an approval reviewed (design/blocker_resolution.md, §5). The agent is a
callable, so the logic is tested without a model."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from discopop_library.PatchRepair.patchset import PatchSet
from discopop_library.BlockerResolution.answers import (
    AGREE,
    APPROVED,
    ROUNDING,
    AnswerError,
    Justification,
    cited_file,
    parse_check_answer,
    parse_review_answer,
)
from discopop_library.BlockerResolution.facts import SourceFiles
from discopop_library.BlockerResolution.prompts import check_prompt, retry_prompt, review_prompt
from discopop_library.BlockerResolution.discopop_tools import SERVER_NAME as DISCOPOP_SERVER_NAME
from discopop_library.BlockerResolution.tool_calls import mcp_server_failed, opened_files, tool_calls
from discopop_library.BlockerResolution.unsure import UnsureSuggestion
from discopop_library.BlockerResolution.workspace import Changes, Workspace, patch_of

logger = logging.getLogger("BlockerResolution")

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
    # the raw event stream of the backend, for the transcript and the tool calls; empty if there is none
    events: str = ""


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
class CheckOptions:
    # what is not copied into the workspace: the project's fingerprint ignore patterns
    ignore: Sequence[str] = ()
    # the project's own versions of the prompt templates (prompt_store), None for the shipped ones
    prompt_dir: Optional[str] = None
    # whether an approval whose results may differ by rounding (floating-point operations in another order) counts
    accept_rounding: bool = True
    # whether the agents can query DiscoPoP's data (the MCP server, see discopop_tools)
    discopop_tools: bool = False


@dataclass
class Outcome:
    pattern_id: int
    state: str
    reason: str = ""
    # the verdict of the agent: approved, rejected, unsure; None without a usable answer
    verdict: Optional[str] = None
    assumption: str = ""
    justifications: List[Justification] = field(default_factory=list)
    # as declared by an approval: "none" or "rounding"
    result_differences: Optional[str] = None
    review: Optional[Dict[str, str]] = None
    verification: Optional[str] = None
    patch: Optional[PatchSet] = None
    calls: int = 0
    unanswered: int = 0
    # tool calls of all agent calls (reading, searching, editing), as far as the backend reports them
    tool_calls: int = 0
    # whether the agent opened every file holding a blocker's line in the attempt that decided; None if its backend
    # reports no tool calls, so that it cannot be told
    read_blocker_files: Optional[bool] = None
    # the backend reported that DiscoPoP's MCP server failed to start (claude's init event)
    discopop_tools_failed: bool = False
    gates: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "state": self.state,
            "reason": self.reason,
            "verdict": self.verdict,
            "assumption": self.assumption,
            "justifications": [j.to_dict() for j in self.justifications],
            "result_differences": self.result_differences,
            "review": self.review,
            "verification": self.verification,
            "changed_files": sorted(self.patch.entries) if self.patch is not None else [],
            "calls": self.calls,
            "unanswered": self.unanswered,
            "tool_calls": self.tool_calls,
            "read_blocker_files": self.read_blocker_files,
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
            logger.debug("Prompt " + name + ":\n" + prompt)
            reply = self.agent(prompt, session, workdir)
            if self.guard is not None:
                # raises ProjectChanged, which ends the whole run
                self.guard()
            answer = reply.text if reply.answered else "(no answer) " + reply.failure
            logger.debug("Response " + name + ":\n" + answer)
            self._write(name + "_answer.txt", answer)
            if reply.events:
                calls = tool_calls(reply.events)
                self.outcome.tool_calls += len(calls)
                if mcp_server_failed(reply.events, DISCOPOP_SERVER_NAME):
                    self.outcome.discopop_tools_failed = True
                self._write(name + "_events.jsonl", reply.events)
                # paths relative to the copy the agent worked in
                prefix = os.path.join(os.path.realpath(workdir), "")
                listed = "".join(str(c).replace(prefix, "").replace(workdir + os.sep, "") + "\n" for c in calls)
                self._write(name + "_tools.txt", listed or "(no tool calls)\n")
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
    patch = patch_of(changes.mapped, files, suggestion.pattern_id)
    if not patch.entries:
        return None, "Your changes do not differ from the original code. Add the directive directly before the loop."
    return patch, ""


def unexplained_files(
    changed: Sequence[int], suggestion: UnsureSuggestion, files: SourceFiles, justifications: List[Justification]
) -> List[str]:
    """the changed files which hold neither the loop nor a blocker's line, and which no justification cites: a
    change there is explained by nothing. Evidence names a file by its path, or by its file name if no other known
    file has that name, as the answer parser accepts it."""
    expected = {suggestion.start.file_id}
    for blocker in suggestion.blockers:
        for location in (blocker.source, blocker.sink):
            if location is not None:
                expected.add(location.file_id)
    known = [files.display_path(i) for i in sorted(files.file_mapping)]
    cited = set()
    for justification in justifications:
        for evidence in justification.evidence:
            name = cited_file(evidence.strip("`").split(":")[0], known)
            if name is not None:
                cited.add(name)
    result = []
    for file_id in sorted(changed):
        if file_id in expected:
            continue
        path = files.display_path(file_id)
        if path not in cited:
            result.append(path)
    return result


def blocker_files(suggestion: UnsureSuggestion, files: SourceFiles) -> Tuple[List[str], List[str]]:
    """(the files holding the lines of the blockers, as the agent sees them in its copy; those it cannot open). A
    file without a file id or outside the project root is not in the copy, and a blocker without any location has no
    file to open: the second list names them, and no approval can then be checked."""
    names: Set[str] = set()
    unreadable: Set[str] = set()
    for blocker in suggestion.blockers:
        locations = [location for location in (blocker.source, blocker.sink) if location is not None]
        if not locations:
            unreadable.add("a blocker without a location")
        for location in locations:
            name = files.in_project(location.file_id)
            if name is None:
                unreadable.add(files.display_path(location.file_id))
            else:
                names.add(name)
    return sorted(names), sorted(unreadable)


class _Reading:
    """what the agent opened during one attempt"""

    def __init__(self, required: List[str]) -> None:
        self.required = required
        self.reported = False
        self.opened: Set[str] = set()

    def add(self, reply: AgentReply, workdir: str) -> None:
        if reply.events:
            self.reported = True
            self.opened |= opened_files(tool_calls(reply.events), workdir)

    def missing(self) -> List[str]:
        return [name for name in self.required if name not in self.opened] if self.reported else []

    def verdict(self) -> Optional[bool]:
        return (not self.missing()) if self.reported else None


def check_suggestion(
    suggestion: UnsureSuggestion,
    files: SourceFiles,
    project_root: str,
    agent: Agent,
    reviewer: Optional[Agent],
    budget: Budget,
    artifacts: Optional[str] = None,
    guard: Optional[Callable[[], None]] = None,
    options: Optional[CheckOptions] = None,
) -> Outcome:
    """asks the agent, applies the gates and, for an approval, the review. Never approves without a usable,
    complete answer: anything else is a rejection or a failure."""
    options = options or CheckOptions()
    outcome = Outcome(pattern_id=suggestion.pattern_id, state=STATE_FAILED)
    conversation = _Conversation(agent, outcome, budget, artifacts, "check", guard)
    known_files = [files.display_path(i) for i in sorted(files.file_mapping)]
    required_files, unreadable_files = blocker_files(suggestion, files)
    if unreadable_files:
        # fail closed: the reading gate could require nothing for these blockers, so an approval could not be
        # checked; asking the agent would only cost calls
        outcome.state = STATE_REJECTED
        outcome.reason = (
            "a blocker's line is in no file the agent can open in its copy of the project (outside the project root "
            "or without a file id): " + ", ".join(unreadable_files)
        )
        return outcome
    if directive_at_loop("\n".join(files.lines(suggestion.start.file_id)), files.line_text(suggestion.start)):
        # nothing to add: asking the agent would end in an approval without a change
        outcome.state = STATE_REJECTED
        outcome.reason = (
            "the loop at " + files.where(suggestion.start) + " already has an OpenMP parallel for directive in the "
            "source; there is nothing to add"
        )
        return outcome
    last_problem = ""
    try:
        for attempt in range(1, budget.prompts + 1):
            workspace = Workspace(project_root, files, ignore=options.ignore)
            try:
                message = check_prompt(suggestion, files, options.prompt_dir, options.discopop_tools)
                reading = _Reading(required_files)
                session: Optional[str] = None
                for turn in range(budget.retries + 1):
                    reply = conversation.ask(message, session, workspace.root, str(attempt) + "_" + str(turn))
                    session = reply.session
                    reading.add(reply, workspace.root)
                    outcome.read_blocker_files = reading.verdict()
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
                        if reading.missing():
                            # only what can be checked: the files were opened, not that the declarations were read
                            failure = (
                                "Before approving, open the files of the blockers and read the declarations of the "
                                "data involved. Not opened: " + ", ".join(reading.missing()) + "."
                            )
                        else:
                            changes = workspace.changes()
                            patch, failure = change_gates(changes, suggestion, files)
                            unexplained = unexplained_files(
                                list(changes.mapped), suggestion, files, answer.justifications
                            )
                            if not failure and unexplained:
                                patch = None
                                failure = (
                                    "These files changed although they hold neither the loop nor a blocker's line, "
                                    "and no justification cites them: "
                                    + ", ".join(unexplained)
                                    + ". Undo changes the parallel loop does not need; cite the lines of a needed "
                                    "change in the evidence of the blocker it resolves."
                                )
                    if failure:
                        outcome.gates.append({"attempt": attempt, "turn": turn, "detail": failure})
                        last_problem = failure
                        outcome.verdict = None
                        if session is None:
                            # a follow-up turn needs the conversation: on its own, it would ask about nothing
                            outcome.gates.append({"attempt": attempt, "turn": turn, "detail": "no session to continue"})
                            break
                        message = retry_prompt(failure, options.prompt_dir)
                        continue
                    assert patch is not None
                    outcome.assumption = answer.assumption
                    outcome.justifications = answer.justifications
                    outcome.result_differences = answer.result_differences
                    if answer.result_differences == ROUNDING and not options.accept_rounding:
                        # final: the approval is complete, only its kind is not accepted
                        outcome.state = STATE_REJECTED
                        outcome.reason = (
                            "the results may differ from the sequential program by rounding, which is not accepted "
                            "(--reject-rounding)"
                        )
                        return outcome
                    outcome.patch = patch
                    return _review(
                        suggestion,
                        files,
                        project_root,
                        changes.mapped,
                        reviewer,
                        budget,
                        artifacts,
                        guard,
                        outcome,
                        options,
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
    outcome.result_differences = None
    outcome.read_blocker_files = None
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
    options: CheckOptions,
) -> Outcome:
    assert outcome.patch is not None
    if reviewer is None:
        outcome.state = STATE_APPROVED
        outcome.verification = VERIFICATION_STATIC
        return outcome
    conversation = _Conversation(reviewer, outcome, budget, artifacts, "review", guard)
    message = review_prompt(
        suggestion,
        outcome.patch,
        files,
        outcome.assumption,
        outcome.justifications,
        outcome.result_differences or "",
        options.prompt_dir,
        options.discopop_tools,
    )
    workspace = Workspace(project_root, files, ignore=options.ignore)
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
                message = retry_prompt(str(error), options.prompt_dir)
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
