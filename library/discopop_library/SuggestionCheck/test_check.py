# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The check of one unsure suggestion, with scripted agents working in their workspaces."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import pytest

from discopop_library.SuggestionCheck.check import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_REJECTED,
    VERIFICATION_STATIC,
    Budget,
    Outcome,
    check_suggestion,
)
from discopop_library.SuggestionCheck.conftest import (
    AGREE,
    APPROVAL,
    APPROVED_SOURCE,
    LOOP_LINE,
    PARALLEL,
    SOURCE,
    Project,
    ScriptedAgent,
    edits,
    json_answer,
    with_line_before,
)
from discopop_library.SuggestionCheck.workspace import ProjectChanged, ProjectGuard


def run(project: Project, agent: ScriptedAgent, reviewer: Optional[ScriptedAgent] = None, **budget: Any) -> Outcome:
    return check_suggestion(
        project.suggestion,
        project.files,
        str(project.root),
        agent,
        reviewer,
        Budget(**budget),
        guard=ProjectGuard(str(project.root)).check,
    )


def approve(code: str = APPROVED_SOURCE) -> Any:
    return edits(code, APPROVAL)


@pytest.mark.parametrize("verdict", ["rejected", "unsure"])
def test_a_rejection_is_final(project: Project, verdict: str) -> None:
    agent = ScriptedAgent([json_answer(verdict=verdict, reason="the order matters")])
    outcome = run(project, agent)
    assert (outcome.state, outcome.verdict, outcome.reason) == (STATE_REJECTED, verdict, "the order matters")
    assert outcome.patch is None
    assert outcome.calls == 1


def test_the_agent_works_in_a_copy_of_the_project(project: Project) -> None:
    agent = ScriptedAgent([json_answer(verdict="unsure", reason="?")])
    run(project, agent)
    workdir = agent.workdirs[0]
    assert os.path.realpath(workdir) != os.path.realpath(project.root)
    assert agent.seen_code == [SOURCE]
    # removed afterwards
    assert not os.path.exists(workdir)


def test_an_approval_agreed_by_the_review_is_approved_with_the_patch_of_the_changes(project: Project) -> None:
    reviewer = ScriptedAgent([AGREE])
    outcome = run(project, ScriptedAgent([approve()]), reviewer)
    assert outcome.state == STATE_APPROVED
    assert outcome.verification == VERIFICATION_STATIC
    assert outcome.assumption == "the values only need to be random"
    assert outcome.review == {"verdict": "agree", "reason": "holds"}
    assert outcome.patch is not None and sorted(outcome.patch.entries) == [1]
    patch = outcome.patch.entries[1].text
    assert re.search(r"^\+\s*#pragma omp parallel for", patch, re.MULTILINE)
    assert "+// each thread has its own state" in patch
    # the project itself is unchanged
    assert (project.root / "code.cpp").read_text() == SOURCE
    # the reviewer sees the approval, the patch and a copy with the changes, in a directory of its own
    assert "the values only need to be random" in reviewer.prompts[0]
    assert "+++ b/code.cpp" in reviewer.prompts[0]
    assert reviewer.seen_code == [APPROVED_SOURCE]


def test_a_disagreeing_review_rejects(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approve()]), ScriptedAgent([json_answer(verdict="disagree", reason="no")]))
    assert outcome.state == STATE_REJECTED
    assert outcome.reason == "the review disagreed: no"
    assert outcome.patch is None


def test_a_review_without_a_usable_answer_rejects(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approve()]), ScriptedAgent(["looks fine", "really fine"]), retries=1)
    assert outcome.state == STATE_REJECTED
    assert outcome.patch is None


def test_without_a_review_an_approval_is_still_only_static(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approve()]))
    assert (outcome.state, outcome.verification, outcome.review) == (STATE_APPROVED, VERIFICATION_STATIC, None)


def test_an_approval_without_the_directive_is_sent_back_and_the_changes_stay(project: Project) -> None:
    only_comment = with_line_before(SOURCE, 3, "// each thread has its own state\n")
    agent = ScriptedAgent([edits(only_comment, APPROVAL), approve()])
    outcome = run(project, agent)
    assert outcome.state == STATE_APPROVED
    assert "not directly preceded by its OpenMP directive" in agent.prompts[1]
    # the follow-up turn continues the conversation in the same copy
    assert agent.sessions == [None, "s1"]
    assert agent.workdirs[0] == agent.workdirs[1]
    assert agent.seen_code[1] == only_comment


@pytest.mark.parametrize(
    "code",
    [
        with_line_before(SOURCE, LOOP_LINE, "  // #pragma omp parallel for\n"),
        with_line_before(SOURCE, 6, PARALLEL),
        with_line_before(SOURCE, LOOP_LINE, PARALLEL).replace("i < 100; i++", "i < 100; ++i"),
        SOURCE,
    ],
    ids=["comment", "other_line", "header_changed", "unchanged"],
)
def test_the_loop_must_be_directly_preceded_by_its_directive(project: Project, code: str) -> None:
    outcome = run(project, ScriptedAgent([edits(code, APPROVAL)]), retries=0, prompts=1)
    assert outcome.state == STATE_FAILED
    assert outcome.patch is None


def test_only_source_files_may_change(project: Project) -> None:
    def also_readme(workdir: Path) -> str:
        (workdir / "code.cpp").write_text(APPROVED_SOURCE)
        (workdir / "README").write_text("changed\n")
        (workdir / "new.h").write_text("int x;\n")
        return APPROVAL

    def undoes(workdir: Path) -> str:
        (workdir / "README").write_text("not a source file\n")
        (workdir / "new.h").unlink()
        return APPROVAL

    agent = ScriptedAgent([also_readme, undoes])
    outcome = run(project, agent)
    assert "README, new.h" in agent.prompts[1]
    assert outcome.state == STATE_APPROVED
    assert outcome.patch is not None and sorted(outcome.patch.entries) == [1]


def test_a_new_attempt_starts_with_a_fresh_copy(project: Project) -> None:
    only_comment = with_line_before(SOURCE, 3, "// x\n")
    agent = ScriptedAgent([edits(only_comment, APPROVAL), json_answer(verdict="rejected", reason="no")])
    outcome = run(project, agent, prompts=2, retries=0)
    assert outcome.state == STATE_REJECTED
    assert agent.workdirs[0] != agent.workdirs[1]
    assert agent.seen_code[1] == SOURCE


def test_unusable_answers_end_in_failure_not_approval(project: Project) -> None:
    agent = ScriptedAgent(["no idea"] * 4)
    outcome = run(project, agent, prompts=2, retries=1)
    assert outcome.state == STATE_FAILED
    assert outcome.calls == 4
    assert agent.sessions == [None, "s1", None, "s3"]


def test_without_a_session_a_follow_up_turn_starts_a_new_attempt(project: Project) -> None:
    agent = ScriptedAgent(["no idea", json_answer(verdict="rejected", reason="no")], sessions=False)
    outcome = run(project, agent, prompts=2, retries=2)
    assert outcome.state == STATE_REJECTED
    assert agent.prompts[1] == agent.prompts[0]


def test_a_review_without_a_session_is_not_continued(project: Project) -> None:
    reviewer = ScriptedAgent(["fine"], sessions=False)
    outcome = run(project, ScriptedAgent([approve()]), reviewer, retries=2)
    assert outcome.state == STATE_REJECTED
    assert len(reviewer.prompts) == 1


def test_an_unreachable_agent_fails_without_using_the_budget(project: Project) -> None:
    agent = ScriptedAgent([None, None, json_answer(verdict="rejected", reason="no")])
    outcome = run(project, agent, agent_error_retries=2, prompts=1, retries=0)
    assert (outcome.state, outcome.unanswered, outcome.calls) == (STATE_REJECTED, 2, 3)

    outcome = run(project, ScriptedAgent([None, None, None]), agent_error_retries=2)
    assert outcome.state == STATE_FAILED
    assert outcome.reason.startswith("the agent did not answer")


def test_an_unreachable_reviewer_leaves_nothing_of_the_approval(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approve()]), ScriptedAgent([None] * 3), agent_error_retries=2)
    assert outcome.state == STATE_FAILED
    assert (outcome.patch, outcome.verdict, outcome.assumption, outcome.justifications) == (None, None, "", [])


def test_an_agent_which_changes_the_project_itself_ends_the_run(project: Project) -> None:
    def escapes(workdir: Path) -> str:
        (project.root / "code.cpp").write_text(APPROVED_SOURCE)
        return APPROVAL

    with pytest.raises(ProjectChanged, match="code.cpp"):
        run(project, ScriptedAgent([escapes]))


def test_the_prompt_states_facts_and_proposes_no_fix(project: Project) -> None:
    agent = ScriptedAgent([json_answer(verdict="unsure", reason="?")])
    run(project, agent)
    prompt = agent.prompts[0]
    assert "Suggestion 5: loop code.cpp:7-10: doall, 1 blocker." in prompt
    assert "#pragma omp parallel for firstprivate(drawn)" in prompt
    assert "### Blocker 1" in prompt
    assert "`code.cpp:8`: `state = state * 3u + 1u;`" in prompt
    assert "_ZL5state" in prompt
    assert " 8 |     state = state * 3u + 1u;" in prompt
    for remedy in ("thread_local", "critical", "atomic", "threadprivate", "private(state"):
        assert remedy not in prompt
