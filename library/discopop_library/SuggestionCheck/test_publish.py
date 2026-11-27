# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from discopop_library.SuggestionCheck.publish import (
    load_approved,
    manage_published,
    marker_of,
    publish_approved,
    published_ids,
    withdraw_published,
)
from discopop_library.SuggestionCheck.results import APPROVED_DIR, APPROVED_FILE
from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.unsure import UNSURE_SUGGESTIONS_FILE, Fingerprint


@pytest.fixture
def dot(tmp_path: Path) -> Path:
    dot = tmp_path / ".discopop"
    (dot / "explorer").mkdir(parents=True)
    (dot / UNSURE_SUGGESTIONS_FILE).write_text("{}")
    check = dot / "suggestion_check"
    for pattern_id in (7, 9):
        (check / APPROVED_DIR / str(pattern_id)).mkdir(parents=True)
        (check / APPROVED_DIR / str(pattern_id) / "1.patch").write_text("patch " + str(pattern_id))
    (check / APPROVED_FILE).write_text(
        json.dumps(
            {
                "explorer_output": Fingerprint.of(str(dot / UNSURE_SUGGESTIONS_FILE)).to_dict(),
                "suggestions": [
                    {"pattern_id": 7, "assumption": "a7", "result_differences": "none", "model": "m"},
                    {"pattern_id": 9, "assumption": "a9", "result_differences": "rounding"},
                ],
            }
        )
    )
    return dot


def test_publishing_copies_the_patches_with_the_assumption(dot: Path) -> None:
    result = publish_approved(str(dot))
    assert result.published == [7, 9] and not result.skipped
    assert (dot / "patch_generator" / "7" / "1.patch").read_text() == "patch 7"
    marker = marker_of(str(dot), 9)
    assert marker is not None and marker["assumption"] == "a9" and marker["result_differences"] == "rounding"
    assert published_ids(str(dot)) == [7, 9]


def test_only_the_requested_ids(dot: Path) -> None:
    assert publish_approved(str(dot), [9]).published == [9]
    assert published_ids(str(dot)) == [9]


def test_a_suggestion_which_is_not_approved_is_skipped(dot: Path) -> None:
    result = publish_approved(str(dot), [3])
    assert result.published == [] and result.skipped == {3: "not approved"}


def test_a_generated_patch_is_never_replaced(dot: Path) -> None:
    generated = dot / "patch_generator" / "7"
    generated.mkdir(parents=True)
    (generated / "1.patch").write_text("generated")
    result = publish_approved(str(dot))
    assert result.published == [9] and 7 in result.skipped
    assert (generated / "1.patch").read_text() == "generated"
    assert published_ids(str(dot)) == [9]


def test_stale_approvals_are_not_published(dot: Path) -> None:
    (dot / UNSURE_SUGGESTIONS_FILE).write_text('{"newer": true}')
    result = publish_approved(str(dot))
    assert result.published == [] and set(result.skipped) == {7, 9}
    assert not (dot / "patch_generator").exists()


def test_withdrawing_removes_only_published_ones(dot: Path) -> None:
    publish_approved(str(dot))
    generated = dot / "patch_generator" / "12"
    generated.mkdir()
    (generated / "1.patch").write_text("generated")
    assert withdraw_published(str(dot), [7]) == [7]
    assert published_ids(str(dot)) == [9]
    assert withdraw_published(str(dot)) == [9]
    assert (generated / "1.patch").exists()


def test_publishing_again_replaces_a_published_one(dot: Path) -> None:
    publish_approved(str(dot), [7])
    (dot / "suggestion_check" / APPROVED_DIR / "7" / "1.patch").write_text("newer")
    publish_approved(str(dot), [7])
    assert (dot / "patch_generator" / "7" / "1.patch").read_text() == "newer"


def test_no_check_yet(tmp_path: Path) -> None:
    assert load_approved(str(tmp_path)) == {}
    assert publish_approved(str(tmp_path)).published == []


def test_the_command_line_side(dot: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = SuggestionCheckArguments(
        log_level="WARNING", write_log=False, dot_dp_path=str(dot), publish_approved=True, suggestions="7"
    )
    assert manage_published(args) == 0
    assert "Published: 7" in capsys.readouterr().out
    args = SuggestionCheckArguments(log_level="WARNING", write_log=False, dot_dp_path=str(dot), withdraw_published=True)
    assert manage_published(args) == 0
    assert "Withdrawn: 7" in capsys.readouterr().out
    assert not os.path.exists(dot / "patch_generator" / "7")
    with pytest.raises(ValueError):
        SuggestionCheckArguments(
            log_level="WARNING", write_log=False, dot_dp_path=str(dot), publish_approved=True, withdraw_published=True
        )
