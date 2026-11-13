# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The autotuner never considers a suggestion that patches files outside the project."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from discopop_library.EmpiricalAutotuning.utils import exclude_outside_project_patterns


def test_outside_suggestions_are_removed_from_the_search_space(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dot = tmp_path / "proj" / ".discopop"
    for suggestion_id, file_id in (("1", 1), ("2", 2), ("3", 1)):
        (dot / "patch_generator" / suggestion_id).mkdir(parents=True)
        (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_text("")
    (dot / "FileMapping.txt").write_text(f"1\t{tmp_path}/proj/a.c\n2\t{tmp_path}/shared/a.c\n")
    patterns: Any = SimpleNamespace(
        do_all=[SimpleNamespace(pattern_id=1), SimpleNamespace(pattern_id=2)],
        reduction=[SimpleNamespace(pattern_id=3)],
    )
    detection_result: Any = SimpleNamespace(patterns=patterns)

    with caplog.at_level(logging.WARNING):
        skipped = exclude_outside_project_patterns(detection_result, str(dot), logging.getLogger("autotuner-test"))

    assert skipped == {"2": [f"{tmp_path}/shared/a.c"]}
    assert [p.pattern_id for p in patterns.do_all] == [1] and [p.pattern_id for p in patterns.reduction] == [3]
    assert "Autotuner: skipping 1 suggestion(s) that patch files outside the project" in caplog.text


def test_nothing_is_removed_or_logged_when_everything_is_inside(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dot = tmp_path / "proj" / ".discopop"
    (dot / "patch_generator" / "1").mkdir(parents=True)
    (dot / "patch_generator" / "1" / "1.patch").write_text("")
    (dot / "FileMapping.txt").write_text(f"1\t{tmp_path}/proj/a.c\n")
    patterns: Any = SimpleNamespace(do_all=[SimpleNamespace(pattern_id=1)])
    detection_result: Any = SimpleNamespace(patterns=patterns)
    with caplog.at_level(logging.WARNING):
        skipped = exclude_outside_project_patterns(detection_result, str(dot), logging.getLogger("x"))
    assert skipped == {}
    assert len(patterns.do_all) == 1 and not caplog.records
