# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduction of omp-tasks/knapsack: two recursive tasks (without, with)
joined by one taskwait, after which both results are read (knapsack.c:226-234)."""

from pathlib import Path
from typing import Any, List, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_knapsack") / "src")
    return explore(dot_discopop, "task")


def _regions(result: Any) -> List[Any]:
    return [p for p in result.patterns.task if type(p) is ParallelRegionInfo]


def _tasks(result: Any) -> List[Any]:
    return [p for p in result.patterns.task if type(p) is TaskParallelismInfo]


def _lines(patterns: List[Any]) -> List[Tuple[str, str]]:
    return sorted((p.region_start_line, p.region_end_line) for p in patterns)


def test_the_group_of_the_two_tasks_is_found(result: Any) -> None:
    assert ("24", "26") in _lines(_regions(result))


def test_both_tasks_are_found(result: Any) -> None:
    assert {("24", "24"), ("26", "26")} <= set(_lines(_tasks(result)))


def test_each_task_and_the_group_are_reported_once(result: Any) -> None:
    assert _lines(_regions(result)) == [("24", "26")]
    assert _lines(_tasks(result)) == [("24", "24"), ("26", "26")]


def test_the_max_after_the_taskwait_reads_both_results(result: Any) -> None:
    region = next(r for r in _regions(result) if r.region_start_line == "24")
    assert {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences} == {
        ("with", "RAW", "1:28"),
        ("without", "RAW", "1:28"),
    }


@pytest.mark.xfail(  # type: ignore[misc]
    strict=True, reason="shared is empty: without and with are not reported as shared"
)
def test_data_sharing_of_the_tasks(result: Any) -> None:
    by_line = {t.region_start_line: t for t in _tasks(result)}
    assert "without" in by_line["24"].shared
    assert "with" in by_line["26"].shared
    for task in by_line.values():
        assert set(task.first_private) >= {"e", "c", "n", "v", "l"}
