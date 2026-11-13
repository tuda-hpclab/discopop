# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The patch repair never considers a suggestion that patches files outside the project."""

import logging
from pathlib import Path
from typing import Any, Dict

import pytest

from discopop_library.PatchRepair import candidates
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments


def _arguments(dot: Path, suggestions: Any = None) -> PatchRepairArguments:
    arguments = PatchRepairArguments.__new__(PatchRepairArguments)
    arguments.dot_dp_path = str(dot)
    arguments.configuration = "tiny"
    arguments.hotspot_types = "yes,maybe"
    arguments.suggestions = suggestions
    arguments.patch_generator_path = str(dot / "patch_generator")
    return arguments


@pytest.fixture
def dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Suggestion 1 patches a file of the project, suggestion 2 one outside of it."""
    dot = tmp_path / "proj" / ".discopop"
    for suggestion_id, file_id in (("1", 1), ("2", 2)):
        (dot / "patch_generator" / suggestion_id).mkdir(parents=True)
        (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_text("")
    (dot / "FileMapping.txt").write_text(f"1\t{tmp_path}/proj/a.c\n2\t{tmp_path}/shared/a.c\n")
    mapping: Dict[int, str] = {1: "yes", 2: "yes"}
    monkeypatch.setattr(candidates, "hotspot_type_by_suggestion", lambda *_: mapping)
    return dot


def test_outside_suggestions_are_not_candidates(dot: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = candidates.collect_candidates(_arguments(dot), detection_result=object())  # type: ignore[arg-type]
    assert [candidate.suggestion_id for candidate in result] == [1]
    assert "Patch repair: skipping 1 suggestion(s) that patch files outside the project" in caplog.text


def test_an_explicitly_named_outside_suggestion_is_skipped_as_well(dot: Path) -> None:
    result = candidates.collect_candidates(_arguments(dot, "1,2"), detection_result=object())  # type: ignore[arg-type]
    assert [candidate.suggestion_id for candidate in result] == [1]
