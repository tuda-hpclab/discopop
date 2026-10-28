# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a profile whose callees write their results through pointers: the join
of the group, and that repeated runs of the explorer on one profile give the same groups."""

from pathlib import Path
from typing import Any, List, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"
RUNS = 5


@pytest.fixture(scope="module")  # type: ignore[misc]
def runs(tmp_path_factory: pytest.TempPathFactory) -> List[Any]:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_pointer_flow") / "src")
    return [explore(dot_discopop, "task") for _ in range(RUNS)]


def _regions(result: Any) -> List[Any]:
    return [p for p in result.patterns.task if isinstance(p, ParallelRegionInfo)]


def _description(result: Any) -> List[Tuple[Any, ...]]:
    return sorted(
        (
            r.region_start_line,
            r.region_end_line,
            sorted((a["variable"], a["kind"], a["line"]) for a in r.after_dependences),
        )
        for r in _regions(result)
    )


def test_repeated_runs_on_one_profile_find_the_same_groups(runs: List[Any]) -> None:
    assert len({str(_description(run)) for run in runs}) == 1


def test_the_values_the_callees_write_through_pointers_are_read_after_the_group(runs: List[Any]) -> None:
    region = next(r for r in _regions(runs[0]) if r.region_start_line == "15")
    assert region.region_end_line == "16"
    assert {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences} == {
        ("a", "RAW", "1:17"),
        ("b", "RAW", "1:17"),
    }
