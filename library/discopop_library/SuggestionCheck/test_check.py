# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The check of one unsure suggestion, with a scripted agent."""

from __future__ import annotations

import re

import pytest

from discopop_library.SuggestionCheck.check import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_REJECTED,
    VERIFICATION_STATIC,
    Budget,
    check_suggestion,
)
from discopop_library.SuggestionCheck.conftest import (
    LOOP_LINE,
    PARALLEL,
    SOURCE,
    Project,
    ScriptedAgent,
    approval,
    json_answer,
    with_line_before,
)

# the approved change: the loop's directive and a change elsewhere
APPROVED_SOURCE = with_line_before(
    with_line_before(SOURCE, LOOP_LINE, PARALLEL), 3, "// each thread has its own state\n"
)
AGREE = json_answer(verdict="agree", reason="holds")


def approved_answer(project: Project, modified: str = APPROVED_SOURCE) -> str:
    return json_answer(**approval()) + "\n\n" + project.patch_block(modified)


def run(project: Project, agent: ScriptedAgent, reviewer: ScriptedAgent | None = None, **budget: int):  # type: ignore
    return check_suggestion(project.suggestion, project.plain, project.files, agent, reviewer, Budget(**budget))


@pytest.mark.parametrize("verdict", ["rejected", "unsure"])
def test_a_rejection_is_final(project: Project, verdict: str) -> None:
    agent = ScriptedAgent([json_answer(verdict=verdict, reason="the order matters")])
    outcome = run(project, agent)
    assert (outcome.state, outcome.verdict, outcome.reason) == (STATE_REJECTED, verdict, "the order matters")
    assert outcome.patch is None
    assert outcome.calls == 1


def test_an_approval_agreed_by_the_review_is_approved_statically(project: Project) -> None:
    agent = ScriptedAgent([approved_answer(project)])
    reviewer = ScriptedAgent([AGREE])
    outcome = run(project, agent, reviewer)
    assert outcome.state == STATE_APPROVED
    assert outcome.verification == VERIFICATION_STATIC
    assert outcome.assumption == "the values only need to be random"
    assert outcome.review == {"verdict": "agree", "reason": "holds"}
    assert outcome.patch is not None and outcome.patch_changed
    patch = outcome.patch.entries[1].text
    assert re.search(r"^\+\s*#pragma omp parallel for", patch, re.MULTILINE)
    assert "+// each thread has its own state" in patch
    # the reviewer sees the approval
    assert "the values only need to be random" in reviewer.prompts[0]


def test_a_disagreeing_review_rejects(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approved_answer(project)]), ScriptedAgent([json_answer(verdict="disagree")]))
    assert outcome.state == STATE_REJECTED
    assert outcome.reason.startswith("the review disagreed")
    assert outcome.patch is None


def test_a_review_without_a_usable_answer_rejects(project: Project) -> None:
    reviewer = ScriptedAgent(["looks fine", "really fine"])
    outcome = run(project, ScriptedAgent([approved_answer(project)]), reviewer, retries=1)
    assert outcome.state == STATE_REJECTED
    assert outcome.patch is None


def test_without_a_review_an_approval_is_still_only_static(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approved_answer(project)]))
    assert (outcome.state, outcome.verification, outcome.review) == (STATE_APPROVED, VERIFICATION_STATIC, None)


def test_an_incomplete_approval_is_asked_again_in_the_same_conversation(project: Project) -> None:
    incomplete = json_answer(verdict="approved", assumption="x", blockers=[]) + "\n" + project.patch_block(SOURCE)
    agent = ScriptedAgent([incomplete, approved_answer(project)])
    outcome = run(project, agent)
    assert outcome.state == STATE_APPROVED
    assert "Blocker 1 has no justification" in agent.prompts[1]
    assert agent.sessions == [None, "s1"]


def test_a_patch_which_drops_the_directive_is_not_accepted(project: Project) -> None:
    without_directive = with_line_before(SOURCE, 3, "// a comment\n")
    agent = ScriptedAgent(
        [approved_answer(project, without_directive)],
    )
    outcome = run(project, agent, retries=0, prompts=1)
    assert outcome.state == STATE_FAILED
    assert outcome.patch is None
    assert [g["gate"] for g in outcome.gates] == ["patch"]


def test_a_patch_which_does_not_apply_is_fed_back(project: Project) -> None:
    broken = (
        json_answer(**approval())
        + "\n===BEGIN PATCH 1===\n--- a\n+++ b\n@@ -1,1 +1,1 @@\n-nothing\n+x\n===END PATCH 1==="
    )
    agent = ScriptedAgent([broken, approved_answer(project)])
    outcome = run(project, agent)
    assert outcome.state == STATE_APPROVED
    assert "diff against the original source" in agent.prompts[1]


def test_unusable_answers_end_in_failure_not_approval(project: Project) -> None:
    agent = ScriptedAgent(["no idea"] * 4)
    outcome = run(project, agent, prompts=2, retries=1)
    assert outcome.state == STATE_FAILED
    assert outcome.calls == 4
    # each attempt starts a new conversation
    assert agent.sessions == [None, "s1", None, "s3"]


def test_an_unreachable_agent_fails_without_using_the_budget(project: Project) -> None:
    agent = ScriptedAgent([None, None, json_answer(verdict="rejected", reason="no")])
    outcome = run(project, agent, agent_error_retries=2, prompts=1, retries=0)
    assert (outcome.state, outcome.unanswered, outcome.calls) == (STATE_REJECTED, 2, 3)

    agent = ScriptedAgent([None, None, None])
    outcome = run(project, agent, agent_error_retries=2)
    assert outcome.state == STATE_FAILED
    assert outcome.reason.startswith("the agent did not answer")


def test_the_prompt_states_facts_and_proposes_no_fix(project: Project) -> None:
    agent = ScriptedAgent([json_answer(verdict="unsure", reason="?")])
    run(project, agent)
    prompt = agent.prompts[0]
    assert "### Blocker 1" in prompt
    assert "`code.cpp:8`: `state = state * 3u + 1u;`" in prompt
    assert "_ZL5state" in prompt
    assert " 8 |     state = state * 3u + 1u;" in prompt
    for remedy in ("thread_local", "critical", "atomic", "threadprivate", "private("):
        assert remedy not in prompt
