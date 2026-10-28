# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end test of the task detection on a reduction of omp-tasks/health: a task per sub-village in a loop over
the villages, joined by one taskwait before the code that reads what the tasks changed in the village."""

from pathlib import Path
from typing import Any, List

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# (name of the omp-tasks variant, line of the task statement in src/health.c)
GROUPS = [("if_cutoff", 40), ("manual_cutoff", 57), ("plain", 74)]
EXPLORER_REASON = (
    "the explorer fails with 'Invalid iteration structure' on loops that contain a recursive call and run zero "
    "times in the leaf calls, so it gives no task patterns at all"
)


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_health") / "src")
    return explore(dot_discopop, "task")


def _regions(result: Any, line: int) -> List[ParallelRegionInfo]:
    return [
        p
        for p in result.patterns.task
        if isinstance(p, ParallelRegionInfo) and p.region_start_line == str(line) and p.region_end_line == str(line)
    ]


def _tasks(result: Any, line: int) -> List[TaskParallelismInfo]:
    return [
        p
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and p.region_start_line == str(line) and p.region_end_line == str(line)
    ]


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
@pytest.mark.parametrize("variant,line", GROUPS)  # type: ignore[misc]
def test_the_recursive_call_in_the_loop_is_a_region_of_one_task(result: Any, variant: str, line: int) -> None:
    assert len(_regions(result, line)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
@pytest.mark.parametrize("variant,line", GROUPS)  # type: ignore[misc]
def test_the_recursive_call_in_the_loop_is_one_task(result: Any, variant: str, line: int) -> None:
    assert len(_tasks(result, line)) == 1
