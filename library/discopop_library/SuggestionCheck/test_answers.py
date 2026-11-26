# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import pytest

from discopop_library.SuggestionCheck.answers import (
    APPROVED,
    REJECTED,
    AnswerError,
    parse_check_answer,
    parse_review_answer,
)
from discopop_library.SuggestionCheck.conftest import approval, json_answer

PATCH = "===BEGIN PATCH 1===\n--- a\n+++ b\n@@ -1 +1,2 @@\n x\n+y\n===END PATCH 1==="


def test_a_rejection_needs_no_patch() -> None:
    answer = parse_check_answer(json_answer(verdict="Rejected", reason="order matters"), 2, [1])
    assert (answer.verdict, answer.reason) == (REJECTED, "order matters")


def test_a_complete_approval() -> None:
    answer = parse_check_answer(json_answer(**approval()) + "\n" + PATCH, 1, [1])
    assert answer.verdict == APPROVED
    assert [j.index for j in answer.justifications] == [1]
    assert sorted(answer.patches) == [1]


def test_the_json_object_with_the_verdict_counts_even_with_braces_in_the_patch() -> None:
    patch = PATCH.replace("+y", "+{ int z = 0; }")
    answer = parse_check_answer("Here: " + json_answer(**approval()) + "\n" + patch, 1, [1])
    assert answer.verdict == APPROVED


@pytest.mark.parametrize(
    "fields, problem",
    [
        ({**approval(), "assumption": ""}, "assumption"),
        ({**approval(), "blockers": []}, "Blocker 1 has no justification"),
        ({**approval(evidence=[" "])}, "cites no code"),
    ],
)
def test_an_incomplete_approval_is_an_error(fields: dict, problem: str) -> None:  # type: ignore[type-arg]
    with pytest.raises(AnswerError, match=problem):
        parse_check_answer(json_answer(**fields) + "\n" + PATCH, 1, [1])


def test_every_blocker_needs_a_justification() -> None:
    with pytest.raises(AnswerError, match="Blocker 2 has no justification"):
        parse_check_answer(json_answer(**approval()) + "\n" + PATCH, 2, [1])


def test_an_approval_needs_a_patch() -> None:
    with pytest.raises(AnswerError, match="no patch block"):
        parse_check_answer(json_answer(**approval()), 1, [1, 2])


@pytest.mark.parametrize("text", ["no json here", json_answer(verdict="maybe")])
def test_an_unreadable_answer_is_an_error(text: str) -> None:
    with pytest.raises(AnswerError):
        parse_check_answer(text, 1, [1])


def test_review_answers() -> None:
    assert parse_review_answer(json_answer(verdict="Agree", reason="ok")).verdict == "agree"
    with pytest.raises(AnswerError):
        parse_review_answer(json_answer(verdict="approved"))
