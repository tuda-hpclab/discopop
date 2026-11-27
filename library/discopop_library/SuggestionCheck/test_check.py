# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The check of one unsure suggestion, with scripted agents working in their workspaces."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import pytest

from discopop_library.SuggestionCheck.answers import Justification, parse_check_answer
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.check import (
    STATE_APPROVED,
    STATE_FAILED,
    STATE_REJECTED,
    VERIFICATION_STATIC,
    AgentReply,
    Budget,
    CheckOptions,
    Outcome,
    unexplained_files,
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
    approval,
    ScriptedAgent,
    edits,
    json_answer,
    with_line_before,
)
from discopop_library.SuggestionCheck.unsure import Location
from discopop_library.SuggestionCheck.workspace import ProjectChanged, ProjectGuard


def run(
    project: Project,
    agent: ScriptedAgent,
    reviewer: Optional[ScriptedAgent] = None,
    options: Optional[CheckOptions] = None,
    **budget: Any,
) -> Outcome:
    return check_suggestion(
        project.suggestion,
        project.files,
        str(project.root),
        agent,
        reviewer,
        Budget(**budget),
        guard=ProjectGuard(str(project.root)).check,
        options=options,
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


def test_a_loop_which_already_has_its_directive_is_rejected_without_asking_the_agent(project: Project) -> None:
    source = project.root / "code.cpp"
    source.write_text(with_line_before(SOURCE, LOOP_LINE, PARALLEL))
    agent = ScriptedAgent([approve()])
    project.files = SourceFiles({1: source}, str(project.root))
    # the explorer's line numbers are those of this source: the directive shifted the header by one line
    project.suggestion = dataclasses.replace(project.suggestion, start=Location(1, LOOP_LINE + 1))
    outcome = run(project, agent)
    assert outcome.state == STATE_REJECTED and "already has an OpenMP parallel for directive" in outcome.reason
    assert agent.prompts == []


def test_an_array_section_clause_is_sent_back(project: Project) -> None:
    section = with_line_before(SOURCE, LOOP_LINE, "  #pragma omp parallel for reduction(-:f[k*n:n])\n")
    agent = ScriptedAgent([edits(section, APPROVAL), approve()])
    outcome = run(project, agent)
    assert outcome.state == STATE_APPROVED
    assert "array section" in agent.prompts[1]


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
    # correctness only: profitability is measured later, with production inputs
    assert "Whether\nparallelizing it pays off is not your question" in prompt


ROUNDING_APPROVAL = json_answer(**approval(result_differences="rounding"))


def test_a_rounding_approval_is_accepted_by_default_and_marked(project: Project) -> None:
    reviewer = ScriptedAgent([AGREE])
    outcome = run(project, ScriptedAgent([edits(APPROVED_SOURCE, ROUNDING_APPROVAL)]), reviewer)
    assert outcome.state == STATE_APPROVED
    assert outcome.result_differences == "rounding"
    assert outcome.to_dict()["result_differences"] == "rounding"
    # the reviewer checks the declaration
    assert "Result differences: rounding" in reviewer.prompts[0]


def test_a_rounding_approval_is_rejected_if_rounding_is_not_accepted(project: Project) -> None:
    reviewer = ScriptedAgent([AGREE])
    outcome = run(
        project,
        ScriptedAgent([edits(APPROVED_SOURCE, ROUNDING_APPROVAL)]),
        reviewer,
        CheckOptions(accept_rounding=False),
    )
    assert outcome.state == STATE_REJECTED
    assert "rounding" in outcome.reason
    assert outcome.patch is None
    # no review is spent on it
    assert reviewer.prompts == []


def test_an_approval_without_differences_passes_even_if_rounding_is_not_accepted(project: Project) -> None:
    outcome = run(project, ScriptedAgent([approve()]), ScriptedAgent([AGREE]), CheckOptions(accept_rounding=False))
    assert (outcome.state, outcome.result_differences) == (STATE_APPROVED, "none")


def test_the_projects_own_prompts_are_used(project: Project, tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "check.md").write_text("MY CHECK PROMPT\n{description}\n{blockers}\n{code}\n")
    (prompt_dir / "review.md").write_text("MY REVIEW PROMPT {result_differences}\n{patch}\n")
    agent = ScriptedAgent([approve()])
    reviewer = ScriptedAgent([AGREE])
    outcome = run(project, agent, reviewer, CheckOptions(prompt_dir=str(prompt_dir)))
    assert outcome.state == STATE_APPROVED
    assert agent.prompts[0].startswith("MY CHECK PROMPT\nSuggestion 5")
    assert reviewer.prompts[0].startswith("MY REVIEW PROMPT none")


def _with_header(project: Project) -> Project:
    header = project.root / "other.h"
    header.write_text("int unrelated = 0;\n")
    files = SourceFiles({1: project.root / "code.cpp", 2: header}, str(project.root))
    return Project(project.root, files, project.suggestion)


def _edits_both(answer: str) -> Any:
    def step(workdir: Path) -> str:
        (workdir / "code.cpp").write_text(APPROVED_SOURCE)
        (workdir / "other.h").write_text("int unrelated = 1;\n")
        return answer

    return step


def test_a_change_no_justification_explains_is_sent_back(project: Project) -> None:
    project = _with_header(project)
    cited = json_answer(**approval(evidence=["code.cpp:8", "other.h:1"]))
    agent = ScriptedAgent([_edits_both(APPROVAL), cited])
    outcome = run(project, agent, ScriptedAgent([AGREE]))
    assert "no justification cites them: other.h" in outcome.gates[0]["detail"]
    assert "other.h" in agent.prompts[1]
    # cited in the evidence: the change is part of the approval
    assert outcome.state == STATE_APPROVED
    assert outcome.patch is not None and sorted(outcome.patch.entries) == [1, 2]


def test_files_of_the_loop_and_the_blockers_need_no_citation(project: Project) -> None:
    project = _with_header(project)
    approval_ = approval(evidence=["code.cpp:8"])
    justifications = parse_check_answer(json_answer(**approval_), 1, ["code.cpp", "other.h"]).justifications
    assert unexplained_files([1], project.suggestion, project.files, justifications) == []
    assert unexplained_files([1, 2], project.suggestion, project.files, justifications) == ["other.h"]
    by_name = parse_check_answer(
        json_answer(**approval(evidence=["code.cpp:8", "`other.h:1`"])), 1, ["code.cpp", "other.h"]
    ).justifications
    assert unexplained_files([1, 2], project.suggestion, project.files, by_name) == []


def test_a_file_name_shared_by_several_changed_files_explains_neither(project: Project) -> None:
    for directory in ("a", "b"):
        (project.root / directory).mkdir()
        (project.root / directory / "util.h").write_text("int x;\n")
    files = SourceFiles(
        {1: project.root / "code.cpp", 2: project.root / "a" / "util.h", 3: project.root / "b" / "util.h"},
        str(project.root),
    )
    justification = [Justification(1, "j", ["code.cpp:8", "util.h:1"])]
    assert unexplained_files([1, 2, 3], project.suggestion, files, justification) == ["a/util.h", "b/util.h"]
    by_path = [Justification(1, "j", ["code.cpp:8", "a/util.h:1"])]
    assert unexplained_files([1, 2, 3], project.suggestion, files, by_path) == ["b/util.h"]


def _reading_agent(code: str) -> Any:
    """approves without opening a file first, then after reading code.cpp; records its prompts"""
    turns = iter([False, True])
    prompts = []

    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        prompts.append(prompt)
        read = next(turns)
        (Path(workdir) / "code.cpp").write_text(code)
        content = [{"type": "tool_use", "id": str(len(prompts)), "name": "Read", "input": {"file_path": "code.cpp"}}]
        return AgentReply(APPROVAL, True, session="s", events=json.dumps({"content": content if read else []}))

    agent.prompts = prompts  # type: ignore[attr-defined]
    return agent


@pytest.mark.parametrize("linked", ["root", "file_mapping"])
def test_a_project_reached_through_a_symbolic_link_is_checked_like_any_other(
    project: Project, tmp_path: Path, linked: str
) -> None:
    link = tmp_path / "link"
    link.symlink_to(project.root, target_is_directory=True)
    if linked == "root":
        files, root = SourceFiles({1: project.root / "code.cpp"}, str(link)), str(link)
    else:
        files, root = SourceFiles({1: link / "code.cpp"}, str(project.root)), str(project.root)
    agent = _reading_agent(APPROVED_SOURCE)
    outcome = check_suggestion(project.suggestion, files, root, agent, ScriptedAgent([AGREE]), Budget())
    # the agent is shown the paths of its copy, not absolute ones it cannot open
    assert "`code.cpp:8`" in agent.prompts[0]
    assert str(project.root) not in agent.prompts[0] and str(link) not in agent.prompts[0]
    # the reading gate requires the blocker's file: the approval without reading it is sent back
    assert "Not opened: code.cpp" in outcome.gates[0]["detail"]
    assert (outcome.state, outcome.read_blocker_files) == (STATE_APPROVED, True)


@pytest.mark.parametrize("where", ["outside", "unmapped", "nowhere"])
def test_a_blocker_in_no_file_of_the_copy_rejects_without_asking(project: Project, tmp_path: Path, where: str) -> None:
    outside = tmp_path / "outside.h"
    outside.write_text("int state;\n")
    files = SourceFiles({1: project.root / "code.cpp", 2: outside}, str(project.root))
    blocker = project.suggestion.blockers[0]
    location = {"outside": Location(2, 1), "unmapped": Location(9, 1), "nowhere": None}[where]
    blockers = [dataclasses.replace(blocker, source=location, sink=location if where == "nowhere" else blocker.sink)]
    suggestion = dataclasses.replace(project.suggestion, blockers=blockers)
    agent = ScriptedAgent([])
    outcome = check_suggestion(suggestion, files, str(project.root), agent, None, Budget())
    assert outcome.state == STATE_REJECTED and agent.prompts == []
    assert "no file the agent can open" in outcome.reason


def test_the_debug_level_shows_the_prompt_and_the_response(project: Project, caplog: pytest.LogCaptureFixture) -> None:
    agent = ScriptedAgent([json_answer(verdict="unsure", reason="cannot tell here")])
    with caplog.at_level("DEBUG", logger="SuggestionCheck"):
        run(project, agent)
    messages = [r.getMessage() for r in caplog.records if r.name == "SuggestionCheck"]
    assert any(m.startswith("Prompt ") and "checking whether a loop" in m for m in messages)
    assert any(m.startswith("Response ") and "cannot tell here" in m for m in messages)
