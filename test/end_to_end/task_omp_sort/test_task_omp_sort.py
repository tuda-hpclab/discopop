# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the task detection on a reduced version of BOTS sort (omp-tasks/sort/sort.c): cilkmerge spawns
two recursive merges and waits; cilksort spawns four recursive sorts, waits, spawns two merges, waits, and merges the
two halves itself. The expectations are those of the hand-written OpenMP version: three groups of tasks, each joined
by one taskwait."""

import signal
from pathlib import Path
from types import FrameType
from typing import Any, Dict, List, Optional, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"
EXPLORER_TIMEOUT_SECONDS = 90

# (first task line, last task line) of the groups joined by one taskwait, and the lines of their tasks
CILKMERGE = ("53", "56")  # omp-tasks/sort/sort.c:348-353
CILKSORT_SORTS = ("74", "81")  # omp-tasks/sort/sort.c:384-392
CILKSORT_MERGES = ("83", "86")  # omp-tasks/sort/sort.c:394-398
TASK_LINES = {
    CILKMERGE: ["54", "56"],
    CILKSORT_SORTS: ["75", "77", "79", "81"],
    CILKSORT_MERGES: ["84", "86"],
}

XFAIL_REASON = (
    "the explorer does not finish: constructing the ContextTaskGraph takes minutes for a function with four "
    "recursive call sites (cilksort has seven calls), so no task is detected within the time limit"
)

_results: Dict[Path, Any] = {}


class _ExplorerTimeout(Exception):
    pass


def _raise_timeout(signum: int, frame: Optional[FrameType]) -> None:
    raise _ExplorerTimeout(f"the explorer did not finish within {EXPLORER_TIMEOUT_SECONDS} s")


def _explore(dot_discopop: Path) -> Any:
    """The result of the explorer on dot_discopop; a failure (or timeout) is kept and raised again for every test."""
    if dot_discopop not in _results:
        previous = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(EXPLORER_TIMEOUT_SECONDS)
        try:
            _results[dot_discopop] = explore(dot_discopop, "task")
        except Exception as error:
            _results[dot_discopop] = error
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    result = _results[dot_discopop]
    if isinstance(result, Exception):
        raise result
    return result


@pytest.fixture(scope="module")  # type: ignore[misc]
def dot_discopop(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_sort") / "src")


def _region(result: Any, group: Tuple[str, str]) -> ParallelRegionInfo:
    regions = [p for p in result.patterns.task if isinstance(p, ParallelRegionInfo)]
    return next(r for r in regions if r.region_start_line == group[0] and r.region_end_line == group[1])


def _task_lines(result: Any, group: Tuple[str, str]) -> List[str]:
    tasks = [p for p in result.patterns.task if isinstance(p, TaskParallelismInfo)]
    return sorted(t.region_start_line for t in tasks if int(group[0]) <= int(t.region_start_line) <= int(group[1]))


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)  # type: ignore[misc]
def test_cilkmerge_joins_its_two_recursive_merges(dot_discopop: Path) -> None:
    result = _explore(dot_discopop)
    _region(result, CILKMERGE)
    assert _task_lines(result, CILKMERGE) == TASK_LINES[CILKMERGE]


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)  # type: ignore[misc]
def test_cilksort_joins_its_four_recursive_sorts(dot_discopop: Path) -> None:
    result = _explore(dot_discopop)
    _region(result, CILKSORT_SORTS)
    assert _task_lines(result, CILKSORT_SORTS) == TASK_LINES[CILKSORT_SORTS]


@pytest.mark.xfail(strict=True, reason=XFAIL_REASON)  # type: ignore[misc]
def test_cilksort_joins_its_two_merges(dot_discopop: Path) -> None:
    result = _explore(dot_discopop)
    _region(result, CILKSORT_MERGES)
    assert _task_lines(result, CILKSORT_MERGES) == TASK_LINES[CILKSORT_MERGES]
