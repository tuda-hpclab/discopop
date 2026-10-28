# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduction of omp-tasks/nqueens: tasks in a loop, joined by one taskwait
after the loop, whose results (csols) are summed after the taskwait. Two variants of the function are profiled
(IF_CUTOFF, nqueens.c:160-175, and the default one, nqueens.c:350-365)."""

from pathlib import Path
from typing import Any, List, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# (first line of the task body, last line of the task body, line of the sum over csols after the taskwait)
VARIANTS = [(29, 32, 36), (51, 54, 58)]


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_nqueens") / "src")
    return explore(dot_discopop, "task")


def _regions(result: Any) -> List[Any]:
    return [p for p in result.patterns.task if type(p) is ParallelRegionInfo]


def _tasks(result: Any) -> List[Any]:
    return [p for p in result.patterns.task if type(p) is TaskParallelismInfo]


def _lines(patterns: List[Any]) -> List[Tuple[str, str]]:
    return sorted((p.region_start_line, p.region_end_line) for p in patterns)


@pytest.mark.parametrize("first,last,_join", VARIANTS)  # type: ignore[misc]
def test_the_task_in_the_loop_is_found_once(result: Any, first: int, last: int, _join: int) -> None:
    assert _lines(_tasks(result)).count((str(first), str(last))) == 1


@pytest.mark.parametrize("first,last,_join", VARIANTS)  # type: ignore[misc]
@pytest.mark.xfail(  # type: ignore[misc]
    strict=True, reason="the region also covers the line of the for loop that creates the tasks"
)
def test_the_region_covers_exactly_the_task_statement(result: Any, first: int, last: int, _join: int) -> None:
    assert (str(first), str(last)) in _lines(_regions(result))


@pytest.mark.parametrize("first,last,join", VARIANTS)  # type: ignore[misc]
@pytest.mark.xfail(  # type: ignore[misc]
    strict=True, reason="the region has no after_dependences: the read of csols after the taskwait is not reported"
)
def test_the_sum_after_the_taskwait_reads_csols(result: Any, first: int, last: int, join: int) -> None:
    region = next(r for r in _regions(result) if r.region_end_line == str(last))
    assert {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences} == {("csols", "RAW", f"1:{join}")}


@pytest.mark.parametrize("first,last,_join", VARIANTS)  # type: ignore[misc]
@pytest.mark.xfail(  # type: ignore[misc]
    strict=True, reason="shared and private are empty: csols is not reported as shared, b not as private"
)
def test_data_sharing_of_the_task(result: Any, first: int, last: int, _join: int) -> None:
    task = next(t for t in _tasks(result) if t.region_start_line == str(first))
    assert "csols" in task.shared
    assert "b" in task.private
    assert set(task.first_private) >= {"n", "j", "a"}
