# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Any, Dict

import pytest

from discopop_library.SuggestionCheck.answers import (
    APPROVED,
    NO_DIFFERENCES,
    REJECTED,
    ROUNDING,
    AnswerError,
    parse_check_answer,
    parse_review_answer,
)
from discopop_library.SuggestionCheck.conftest import approval, json_answer

FILES = ["src/code.cpp"]


def test_a_rejection() -> None:
    answer = parse_check_answer(json_answer(verdict="Rejected", reason="order matters"), 2, FILES)
    assert (answer.verdict, answer.reason) == (REJECTED, "order matters")


def test_a_complete_approval() -> None:
    answer = parse_check_answer(json_answer(**approval()), 1, FILES)
    assert answer.verdict == APPROVED
    assert [(j.index, j.evidence) for j in answer.justifications] == [(1, ["code.cpp:8"])]


@pytest.mark.parametrize("declared, parsed", [("none", NO_DIFFERENCES), ("Rounding", ROUNDING)])
def test_an_approval_declares_how_the_results_may_differ(declared: str, parsed: str) -> None:
    answer = parse_check_answer(json_answer(**approval(result_differences=declared)), 1, FILES)
    assert answer.result_differences == parsed


def test_the_json_object_with_the_verdict_counts_among_other_braces() -> None:
    prose = 'The loop {"note": 1} has a blocker, see { x = 0; }. ' + json_answer(**approval()) + " and {} more."
    assert parse_check_answer(prose, 1, FILES).verdict == APPROVED


def _with(**changes: Any) -> Dict[str, Any]:
    fields: Dict[str, Any] = dict(approval())
    fields.update(changes)
    return fields


@pytest.mark.parametrize(
    "fields, problem",
    [
        (_with(assumption=""), "assumption"),
        (_with(blockers=[]), "Blocker 1 has no justification"),
        (approval(evidence=[" "]), "cites no code"),
        (_with(result_differences=None), "result_differences"),
        (_with(result_differences="small"), "result_differences"),
    ],
)
def test_an_incomplete_approval_is_an_error(fields: Dict[str, Any], problem: str) -> None:
    with pytest.raises(AnswerError, match=problem):
        parse_check_answer(json_answer(**fields), 1, FILES)


def test_every_blocker_needs_a_justification() -> None:
    with pytest.raises(AnswerError, match="Blocker 2 has no justification"):
        parse_check_answer(json_answer(**approval()), 2, FILES)


@pytest.mark.parametrize("evidence", ["code.cpp:8", [None], ["n/a"], ["code.cpp"], ["other.cpp:8"], ["code.cpp:0"]])
def test_evidence_must_cite_lines_of_project_files(evidence: object) -> None:
    fields: Dict[str, Any] = dict(approval())
    fields["blockers"] = [{"index": 1, "justification": "j", "evidence": evidence}]
    with pytest.raises(AnswerError, match="cites no code"):
        parse_check_answer(json_answer(**fields), 1, FILES)


@pytest.mark.parametrize("evidence", ["src/code.cpp:8", "code.cpp:8-9", "`code.cpp:8`"])
def test_evidence_by_path_or_file_name(evidence: str) -> None:
    fields: Dict[str, Any] = dict(approval())
    fields["blockers"] = [{"index": 1, "justification": "j", "evidence": [evidence]}]
    answer = parse_check_answer(json_answer(**fields), 1, FILES)
    assert answer.justifications[0].evidence == [evidence.strip("`")]


def test_a_file_name_shared_by_several_files_must_be_cited_by_its_path() -> None:
    files = ["a/util.h", "b/util.h"]
    for evidence, accepted in (("util.h:3", False), ("a/util.h:3", True), ("c/util.h:3", False)):
        fields: Dict[str, Any] = dict(approval())
        fields["blockers"] = [{"index": 1, "justification": "j", "evidence": [evidence]}]
        if accepted:
            assert parse_check_answer(json_answer(**fields), 1, files).justifications[0].evidence == [evidence]
        else:
            with pytest.raises(AnswerError, match="cites no code"):
                parse_check_answer(json_answer(**fields), 1, files)


@pytest.mark.parametrize("text", ["no json here", json_answer(verdict="maybe")])
def test_an_unreadable_answer_is_an_error(text: str) -> None:
    with pytest.raises(AnswerError):
        parse_check_answer(text, 1, FILES)


def test_review_answers() -> None:
    assert parse_review_answer(json_answer(verdict="Agree", reason="ok")).verdict == "agree"
    with pytest.raises(AnswerError):
        parse_review_answer(json_answer(verdict="approved"))
