# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end test of the task detection on a reduction of omp-tasks/floorplan (IF_CUTOFF variant): one task per
possible location of a cell in the nested loops, with private copies of the board, joined by one taskwait before
the return of the counters."""

import signal
from pathlib import Path
from types import FrameType
from typing import Any, List, Optional

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# the task statement is the block in src/floorplan.c lines 36 to 51, the code after the taskwait is line 55
TASK_START, TASK_END, AFTER_LINE = "36", "51", "1:55"
EXPLORER_TIMEOUT_SECONDS = 120
EXPLORER_REASON = (
    "the explorer does not finish: constructing the ContextTaskGraph (45142 nodes) slows down to under 100 nodes "
    "per second for the nested loops around the recursive call, so no task is detected within the time limit"
)


class _ExplorerTimeout(Exception):
    pass


def _raise_timeout(signum: int, frame: Optional[FrameType]) -> None:
    raise _ExplorerTimeout(f"the explorer did not finish within {EXPLORER_TIMEOUT_SECONDS} s")


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_floorplan") / "src")
    previous = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(EXPLORER_TIMEOUT_SECONDS)
    try:
        return explore(dot_discopop, "task")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _regions(result: Any) -> List[ParallelRegionInfo]:
    return [
        p
        for p in result.patterns.task
        if isinstance(p, ParallelRegionInfo) and p.region_start_line == TASK_START and p.region_end_line == TASK_END
    ]


def _tasks(result: Any) -> List[TaskParallelismInfo]:
    return [
        p
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and p.region_start_line == TASK_START and p.region_end_line == TASK_END
    ]


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
def test_the_cell_placement_block_is_a_region_of_one_task(result: Any) -> None:
    assert len(_regions(result)) == 1
    assert len(_tasks(result)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
def test_the_counter_nnc_is_read_after_the_taskwait(result: Any) -> None:
    region = _regions(result)[0]
    assert {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences} == {("nnc", "RAW", AFTER_LINE)}


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
def test_the_clauses_of_the_task(result: Any) -> None:
    task = _tasks(result)[0]
    assert "nnc" in task.shared
    assert {"board", "area"} <= set(task.private)
    assert {"i", "j", "id", "level"} <= set(task.first_private)
