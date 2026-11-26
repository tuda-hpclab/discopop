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
from typing import Any, List, Mapping, Optional, Sequence

import pytest

from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.check import Agent
from discopop_library.SuggestionCheck.conftest import Project, ScriptedAgent, approval, json_answer
from discopop_library.SuggestionCheck.run import run
from discopop_library.SuggestionCheck.test_check import APPROVED_SOURCE


def _dot_discopop(project: Project, tmp_path: Path, pattern_ids: List[int]) -> Path:
    dot = tmp_path / ".discopop"
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
    for i in pattern_ids:
        patch_dir = dot / "patch_generator_unsure" / str(i)
        patch_dir.mkdir(parents=True)
        (patch_dir / "1.patch").write_text(project.plain.entries[1].text)
    return dot


def _arguments(dot: Path, **kwargs: Any) -> SuggestionCheckArguments:
    return SuggestionCheckArguments(log_level="WARNING", write_log=False, dot_dp_path=str(dot), **kwargs)


def _factory(answers: Mapping[str, Sequence[Optional[str]]]) -> Any:
    """the first agent made per suggestion checks, the second reviews"""
    made: List[ScriptedAgent] = []

    def factory() -> Agent:
        role = "check" if len(made) % 2 == 0 else "review"
        agent = ScriptedAgent(list(answers[role]))
        made.append(agent)
        return agent

    return factory


def test_an_approved_and_a_rejected_suggestion(project: Project, tmp_path: Path) -> None:
    dot = _dot_discopop(project, tmp_path, [5, 6])
    approve = json_answer(**approval()) + "\n" + project.patch_block(APPROVED_SOURCE)
    answers = {"check": [approve], "review": [json_answer(verdict="agree", reason="ok")]}
    assert run(_arguments(dot, suggestions="5"), _factory(answers)) == 0
    answers = {"check": [json_answer(verdict="rejected", reason="order matters")], "review": []}
    assert run(_arguments(dot, suggestions="6"), _factory(answers)) == 0

    check = dot / "suggestion_check"
    results = json.loads((check / "results.json").read_text())
    assert [(s["pattern_id"], s["state"]) for s in results["suggestions"]] == [(5, "approved"), (6, "rejected")]
    approved = json.loads((check / "approved.json").read_text())
    assert [(s["pattern_id"], s["verification"]) for s in approved["suggestions"]] == [(5, "static")]
    assert "assumption" in approved["note"]
    assert os.listdir(check / "approved") == ["5"]
    assert (check / "transcripts" / "5" / "check_1_0_prompt.txt").exists()
    events = [json.loads(line)["event"] for line in (check / "progress.jsonl").read_text().splitlines()]
    assert events == ["start", "check", "done", "end"]


def test_results_of_an_earlier_explorer_run_are_dropped(project: Project, tmp_path: Path) -> None:
    dot = _dot_discopop(project, tmp_path, [5])
    approve = json_answer(**approval()) + "\n" + project.patch_block(APPROVED_SOURCE)
    run(_arguments(dot, review=False), _factory({"check": [approve], "review": []}))
    assert (dot / "suggestion_check" / "approved" / "5").exists()

    # the explorer ran again
    path = dot / "explorer" / "unsure_suggestions.json"
    path.write_text(path.read_text() + " ")
    run(_arguments(dot, review=False), _factory({"check": [json_answer(verdict="unsure", reason="?")], "review": []}))
    results = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert [(s["pattern_id"], s["state"]) for s in results["suggestions"]] == [(5, "rejected")]
    assert not (dot / "suggestion_check" / "approved" / "5").exists()


def test_an_unknown_suggestion_is_an_error(project: Project, tmp_path: Path) -> None:
    dot = _dot_discopop(project, tmp_path, [5])
    assert run(_arguments(dot, suggestions="9"), _factory({"check": [], "review": []})) == 1


@pytest.mark.parametrize("verify", ["build", "run"])
def test_verification_is_not_implemented_yet(tmp_path: Path, verify: str) -> None:
    with pytest.raises(ValueError, match="not implemented"):
        _arguments(tmp_path, verify=verify)
