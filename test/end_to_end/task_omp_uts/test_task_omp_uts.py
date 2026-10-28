# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduced version of BOTS uts (omp-tasks/uts/uts.c): one task per child
of a tree node in a loop (partialCount[i] = parTreeSearch(...)), a taskwait, and the summation of partialCount after
it. The expectations are those of the hand-written OpenMP version."""

from functools import lru_cache
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# uts.c: the task (omp-tasks/uts/uts.c:209) and the summation after the taskwait (omp-tasks/uts/uts.c:213ff)
TASK_LINE = "32"
SUM_LINE = "36"


@pytest.fixture(scope="module")  # type: ignore[misc]
def dot_discopop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_uts") / "src")


@lru_cache(maxsize=None)
def _explore(dot_discopop: Path) -> Any:
    return explore(dot_discopop, "task")


def _regions(result: Any) -> List[ParallelRegionInfo]:
    return [p for p in result.patterns.task if isinstance(p, ParallelRegionInfo)]


def _tasks(result: Any) -> List[TaskParallelismInfo]:
    return [p for p in result.patterns.task if isinstance(p, TaskParallelismInfo)]


def _dependences(region: ParallelRegionInfo) -> List[Tuple[str, str, str]]:
    return sorted((a["variable"], a["kind"], a["line"]) for a in region.after_dependences)


@pytest.mark.xfail(
    strict=True, reason="the explorer aborts on the loop around the recursive call: 'Invalid iteration structure'"
)  # type: ignore[misc]
def test_the_task_in_the_loop_is_one_group_joined_by_the_taskwait(dot_discopop: Path) -> None:
    regions = _regions(_explore(dot_discopop))
    region = next(r for r in regions if r.region_start_line == TASK_LINE)
    assert region.region_end_line == TASK_LINE
    assert len([t for t in _tasks(_explore(dot_discopop)) if t.region_start_line == TASK_LINE]) == 1


@pytest.mark.xfail(
    strict=True, reason="the explorer aborts on the loop around the recursive call: 'Invalid iteration structure'"
)  # type: ignore[misc]
def test_partial_counts_are_read_after_the_taskwait(dot_discopop: Path) -> None:
    region = next(r for r in _regions(_explore(dot_discopop)) if r.region_start_line == TASK_LINE)
    assert _dependences(region) == [("partialCount", "RAW", "1:" + SUM_LINE)]


@pytest.mark.xfail(
    strict=True, reason="the explorer aborts on the loop around the recursive call: 'Invalid iteration structure'"
)  # type: ignore[misc]
def test_the_task_shares_partial_count_and_privatizes_the_loop_state(dot_discopop: Path) -> None:
    task = next(t for t in _tasks(_explore(dot_discopop)) if t.region_start_line == TASK_LINE)
    assert "partialCount" in task.shared
    assert {"i", "nodePtr"} <= set(task.first_private)
