# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduction of omp-tasks/strassen: the seven recursive sub-multiplies
(tasks) joined by one taskwait, then the additions that read their results."""

import resource
from pathlib import Path
from typing import Any, Iterator, List, Optional, Set, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import PipelineError, build_and_profile, explore

SRC = Path(__file__).parent / "src"

# lines of the seven task statements in src/strassen.c (omp-tasks/strassen/strassen.c: 901, 905, ..., 925)
TASK_LINES = ["45", "47", "49", "51", "53", "55", "57"]
# the variables the additions after the taskwait read, with the line of the first read
AFTER = {
    ("M2", "1:63"),
    ("C11", "1:63"),
    ("T1", "1:64"),
    ("M5", "1:65"),
    ("C12", "1:65"),
    ("C22", "1:66"),
    ("C21", "1:67"),
}
EXPLORER_REASON = (
    "the explorer runs out of memory (it is stopped at 4 GiB) in the insertion of the data dependencies of a "
    "function with seven recursive calls, so it gives no task patterns at all"
)
MEMORY_LIMIT = 4 * 1024**3


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Optional[Any]]:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_strassen") / "src")
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, hard))  # inherited by the explorer process
    try:
        yield explore(dot_discopop, "task")
    except PipelineError:
        yield None
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


def _regions(result: Any) -> List[ParallelRegionInfo]:
    assert result is not None, "the explorer failed"
    return [
        p
        for p in result.patterns.task
        if isinstance(p, ParallelRegionInfo)
        and p.region_start_line == TASK_LINES[0]
        and p.region_end_line == TASK_LINES[-1]
    ]


def _tasks(result: Any, line: str) -> List[TaskParallelismInfo]:
    assert result is not None, "the explorer failed"
    return [
        p
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and p.region_start_line == line and p.region_end_line == line
    ]


def _after(region: ParallelRegionInfo) -> Set[Tuple[str, str]]:
    return {(a["variable"], a["line"]) for a in region.after_dependences if a["kind"] == "RAW"}


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
def test_the_seven_sub_multiplies_are_one_region(result: Any) -> None:
    assert len(_regions(result)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
@pytest.mark.parametrize("line", TASK_LINES)  # type: ignore[misc]
def test_each_sub_multiply_is_one_task(result: Any, line: str) -> None:
    assert len(_tasks(result, line)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON)  # type: ignore[misc]
def test_the_additions_after_the_taskwait_read_the_results_of_the_sub_multiplies(result: Any) -> None:
    assert _after(_regions(result)[0]) == AFTER
