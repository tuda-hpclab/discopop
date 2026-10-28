# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduction of omp-tasks/sparselu/sparselu_single: the fwd and bdiv task
loops joined by one taskwait, then the bmod task loop joined by a second taskwait."""

from pathlib import Path
from typing import Any, List, Set, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# lines of the task statements in src/sparselu.c: fwd (omp-tasks line 229), bdiv (235), the block of bmod (246)
FWD = ("53", "53")
BDIV = ("57", "57")
BMOD = ("65", "66")
EXPLORER_REASON_GROUP_1 = (
    "the explorer gives one region per task loop (the lines 53 and 57) instead of one region with the two task "
    "statements, which one taskwait joins"
)
EXPLORER_REASON_CLAUSES = (
    "the data sharing differs from omp-tasks: the loop index (jj, ii) is not first_private, and BENCH, which the "
    "tasks write through, is not shared"
)


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_sparselu") / "src")
    return explore(dot_discopop, "task")


def _regions(result: Any, start: str, end: str) -> List[ParallelRegionInfo]:
    return [
        p
        for p in result.patterns.task
        if isinstance(p, ParallelRegionInfo) and p.region_start_line == start and p.region_end_line == end
    ]


def _tasks(result: Any, lines: Tuple[str, str]) -> List[TaskParallelismInfo]:
    return [
        p
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and (p.region_start_line, p.region_end_line) == lines
    ]


def _raw(region: ParallelRegionInfo) -> Set[Tuple[str, str]]:
    return {(a["variable"], a["line"]) for a in region.after_dependences if a["kind"] == "RAW"}


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON_GROUP_1)  # type: ignore[misc]
def test_fwd_and_bdiv_are_one_region(result: Any) -> None:
    assert len(_regions(result, "53", "57")) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON_GROUP_1)  # type: ignore[misc]
def test_the_blocks_written_by_fwd_and_bdiv_are_read_by_bmod_after_the_taskwait(result: Any) -> None:
    region = _regions(result, "53", "57")[0]
    assert _raw(region) == {("col", "1:66"), ("row", "1:66")}


@pytest.mark.parametrize("lines", [FWD, BDIV])  # type: ignore[misc]
def test_fwd_and_bdiv_are_one_task_each(result: Any, lines: Tuple[str, str]) -> None:
    assert len(_tasks(result, lines)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON_CLAUSES)  # type: ignore[misc]
@pytest.mark.parametrize("lines", [FWD, BDIV])  # type: ignore[misc]
def test_the_clauses_of_fwd_and_bdiv(result: Any, lines: Tuple[str, str]) -> None:
    task = _tasks(result, lines)[0]
    assert "BENCH" in task.shared
    assert "kk" in task.first_private
    assert ("jj" if lines == FWD else "ii") in task.first_private


def test_bmod_is_one_region(result: Any) -> None:
    assert len(_regions(result, *BMOD)) == 1


def test_bmod_is_one_task(result: Any) -> None:
    assert len(_tasks(result, BMOD)) == 1


@pytest.mark.xfail(strict=True, reason=EXPLORER_REASON_CLAUSES)  # type: ignore[misc]
def test_the_clauses_of_bmod(result: Any) -> None:
    task = _tasks(result, BMOD)[0]
    assert "BENCH" in task.shared
    assert {"kk", "jj", "ii"} <= set(task.first_private)
