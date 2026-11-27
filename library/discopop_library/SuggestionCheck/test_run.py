# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""A whole run of discopop_suggestion_check on a .discopop directory, with scripted agents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.llm_backends.base import Invocation
from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.check import Agent
from discopop_library.SuggestionCheck.conftest import (
    AGREE,
    APPROVAL,
    APPROVED_SOURCE,
    Project,
    ScriptedAgent,
    Step,
    edits,
    json_answer,
)
from discopop_library.SuggestionCheck.prompt_store import custom_prompt_dir, default_template, save_template
from discopop_library.SuggestionCheck.run import EDIT, READ, BackendAgent, restricted, run


def _dot_discopop(project: Project, pattern_ids: List[int]) -> Path:
    dot = project.root / ".discopop"
    (dot / "explorer").mkdir(parents=True)
    (dot / "FileMapping.txt").write_text("1\t" + str(project.files.file_mapping[1]) + "\n")
    blocker = {
        "type": "RAW",
        "source_line": "1:8",
        "sink_line": "1:8",
        "origin": "dynamic",
        "accesses": [{"variable": "_ZL5state", "memory_region": "42"}],
    }
    entries = [
        {
            "pattern_id": i,
            "type": "do_all",
            "start_line": "1:7",
            "end_line": "1:10",
            "pragma": "#pragma omp parallel for",
            "blockers": [blocker],
        }
        for i in pattern_ids
    ]
    (dot / "explorer" / "unsure_suggestions.json").write_text(json.dumps({"format_version": 1, "suggestions": entries}))
    return dot


def _arguments(dot: Path, **kwargs: Any) -> SuggestionCheckArguments:
    return SuggestionCheckArguments(log_level="WARNING", write_log=False, dot_dp_path=str(dot), **kwargs)


def _factory(steps: Dict[str, List[Step]]) -> Any:
    """the agents by mode: EDIT checks, READ reviews"""

    def factory(mode: str) -> Agent:
        return ScriptedAgent(list(steps[mode]))

    return factory


def test_an_approved_and_a_rejected_suggestion(project: Project) -> None:
    dot = _dot_discopop(project, [5, 6])
    assert (
        run(_arguments(dot, suggestions="5"), _factory({EDIT: [edits(APPROVED_SOURCE, APPROVAL)], READ: [AGREE]})) == 0
    )
    assert (
        run(_arguments(dot, suggestions="6"), _factory({EDIT: [json_answer(verdict="rejected", reason="x")], READ: []}))
        == 0
    )

    check = dot / "suggestion_check"
    results = json.loads((check / "results.json").read_text())
    assert [(s["pattern_id"], s["state"]) for s in results["suggestions"]] == [(5, "approved"), (6, "rejected")]
    approved = json.loads((check / "approved.json").read_text())
    assert [(s["pattern_id"], s["verification"]) for s in approved["suggestions"]] == [(5, "static")]
    assert os.listdir(check / "approved") == ["5"]
    assert "#pragma omp parallel for" in (check / "approved" / "5" / "1.patch").read_text()
    assert (check / "transcripts" / "5" / "check_1_0_prompt.txt").exists()
    events = [json.loads(line)["event"] for line in (check / "progress.jsonl").read_text().splitlines()]
    assert events == ["start", "check", "done", "end"]
    # the agent's copy did not contain .discopop
    assert "suggestion_check" not in (check / "transcripts" / "5" / "check_1_0_prompt.txt").read_text()


def test_results_of_an_earlier_explorer_run_are_dropped(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    run(_arguments(dot, review=False), _factory({EDIT: [edits(APPROVED_SOURCE, APPROVAL)], READ: []}))
    assert (dot / "suggestion_check" / "approved" / "5").exists()
    path = dot / "explorer" / "unsure_suggestions.json"
    path.write_text(path.read_text() + " ")
    run(_arguments(dot, review=False), _factory({EDIT: [json_answer(verdict="unsure", reason="?")], READ: []}))
    results = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert [(s["pattern_id"], s["state"]) for s in results["suggestions"]] == [(5, "rejected")]
    assert not (dot / "suggestion_check" / "approved" / "5").exists()


def test_a_run_which_judged_nothing_fails(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    assert run(_arguments(dot, review=False), _factory({EDIT: [None, None, None], READ: []})) == 1


def test_an_agent_which_changes_the_project_aborts_the_run(project: Project) -> None:
    dot = _dot_discopop(project, [5, 6])

    def escapes(workdir: Path) -> str:
        (project.root / "code.cpp").write_text(APPROVED_SOURCE)
        return APPROVAL

    assert run(_arguments(dot, review=False), _factory({EDIT: [escapes], READ: []})) == 2
    events = [
        json.loads(line)["event"] for line in (dot / "suggestion_check" / "progress.jsonl").read_text().splitlines()
    ]
    assert events[-1] == "aborted"


def test_an_unknown_suggestion_is_an_error(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    assert run(_arguments(dot, suggestions="9"), _factory({EDIT: [], READ: []})) == 1


@pytest.mark.parametrize("verify", ["build", "run"])
def test_verification_is_not_implemented_yet(tmp_path: Path, verify: str) -> None:
    with pytest.raises(ValueError, match="not implemented"):
        _arguments(tmp_path, verify=verify)


def test_the_agents_tools_are_restricted_on_the_command_line() -> None:
    check = restricted({"backend": "claude", "extra_args": ["--x"]}, EDIT)
    assert check["extra_args"] == [
        "--x",
        "--tools",
        "Read,Edit,Write,Grep,Glob",
        "--strict-mcp-config",
        "--restricted",
        "--permission-mode",
        "acceptEdits",
    ]
    review = restricted({"backend": "claude"}, READ)
    assert review["extra_args"] == ["--tools", "Read,Grep,Glob", "--strict-mcp-config", "--restricted"]
    opencode = restricted({"backend": "opencode", "auto": True, "backend_options": {"auto": True}}, EDIT)
    assert opencode["auto"] is False and opencode["backend_options"]["auto"] is False
    assert json.loads(opencode["env"]["OPENCODE_CONFIG_CONTENT"])["permission"] == {
        "edit": "allow",
        "bash": "deny",
        "webfetch": "deny",
    }
    read_only = restricted({"backend": "opencode"}, READ)
    assert json.loads(read_only["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]["edit"] == "deny"
    with pytest.raises(ValueError):
        restricted({"backend": "something"}, EDIT)


def test_the_backend_agent_runs_in_the_directory_it_is_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: List[Any] = []

    class Module:
        @staticmethod
        def new_session_id() -> str:
            return "new"

    def fake_run_agent(module: Any, profile: Any, prompt: str, cwd: str, **kwargs: Any) -> Any:
        calls.append((cwd, kwargs["session"], kwargs["new_session"]))
        return Invocation(text="answer", session_id="sid" if kwargs["session"] is None else None)

    monkeypatch.setattr(llm_backends, "for_profile", lambda profile: Module)
    monkeypatch.setattr(llm_backends, "run_agent", fake_run_agent)
    agent = BackendAgent({"backend": "claude"}, 10, EDIT)
    first = agent("prompt", None, str(tmp_path))
    second = agent("follow-up", first.session, str(tmp_path))
    assert (first.session, second.session) == ("sid", "sid")
    assert calls == [(str(tmp_path), None, "new"), (str(tmp_path), "sid", None)]


def test_the_fingerprint_ignore_patterns_are_not_copied(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    (dot / "project").mkdir()
    (dot / "project" / "fingerprint_ignore.json").write_text(json.dumps({"patterns": ["dp_build/"]}))
    (project.root / "dp_build").mkdir()
    (project.root / "dp_build" / "huge.o").write_text("object code")
    seen: List[bool] = []

    def look(workdir: Path) -> str:
        seen.append((workdir / "dp_build").exists())
        return json_answer(verdict="rejected", reason="no")

    assert run(_arguments(dot), _factory({EDIT: [look], READ: []})) == 0
    assert seen == [False]


def test_the_results_record_the_prompts_and_whether_rounding_is_accepted(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    prompt_dir = custom_prompt_dir(str(dot))
    save_template(prompt_dir, "check", default_template("check") + "\nBe brief.\n")
    factory = _factory({EDIT: [json_answer(verdict="rejected", reason="no")], READ: []})
    assert run(_arguments(dot, accept_rounding=False), factory) == 0
    results = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert results["accept_rounding"] is False
    assert results["prompts"]["check"]["custom"] is True
    assert results["prompts"]["review"]["custom"] is False


def test_the_reviews_verdict_is_not_overwritten_by_the_run_settings(project: Project) -> None:
    dot = _dot_discopop(project, [5])
    run(_arguments(dot, suggestions="5"), _factory({EDIT: [edits(APPROVED_SOURCE, APPROVAL)], READ: [AGREE]}))
    results = json.loads((dot / "suggestion_check" / "results.json").read_text())
    entry = results["suggestions"][0]
    assert isinstance(entry["review"], dict) and entry["review"]["verdict"] == "agree"
    assert entry["review_enabled"] is True
