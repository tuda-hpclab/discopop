# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end test of the task detection on a reduction of omp-tasks/health: a task per sub-village in a loop over
the villages, joined by one taskwait before the code that reads what the tasks changed in the village.

The loop walks the villages with a cursor (``vlist = vlist->next``), so it is no do-all loop; it is a loop of tasks
(the update stays with the creating thread, the task gets a copy of ``vlist``). The recursion is the only
parallelism of the program: the five ``check_patients_*`` calls after the loop depend on each other through the fields
of the village (omp-tasks has no task there either).

omp-tasks has the parallel region around the whole recursion, in the caller. The explorer reports the region of a
loop of tasks from the header of the loop to the task."""

from pathlib import Path
from typing import Any, List

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"

# (name of the omp-tasks variant, line of the loop header and of the task statement in src/health.c (the region covers
# the task statement, the loop header is its loop_start_line), line of the
# first read of what the tasks wrote: check_patients_realloc, after the taskwait of omp-tasks)
GROUPS = [("if_cutoff", 39, 40, 47), ("manual_cutoff", 56, 57, 64), ("plain", 73, 74, 81)]
VARIANTS = [(name, header, task) for name, header, task, _ in GROUPS]
JOIN_REASON = (
    "the join of tasks that reach their own function (recursion) is not reported: the code of the function cannot be "
    "told apart from the code of the recursive calls (task_suggestions.md, join points)"
)


@pytest.fixture(scope="module")  # type: ignore[misc]
def result(tmp_path_factory: pytest.TempPathFactory) -> Any:
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_omp_health") / "src")
    return explore(dot_discopop, "task")


def _regions(result: Any, header: int, line: int) -> List[ParallelRegionInfo]:
    return [
        p
        for p in result.patterns.task
        if isinstance(p, ParallelRegionInfo)
        and p.region_start_line == str(line)
        and p.region_end_line == str(line)
        and p.loop_start_line == f"1:{header}"
    ]


def _tasks(result: Any, line: int) -> List[TaskParallelismInfo]:
    return [
        p
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and p.region_start_line == str(line) and p.region_end_line == str(line)
    ]


def test_the_explorer_finishes_and_reports_task_patterns(result: Any) -> None:
    assert len(result.patterns.task) > 0


@pytest.mark.parametrize("variant,header,line", VARIANTS)  # type: ignore[misc]
def test_the_recursive_call_in_the_loop_is_a_region_of_one_task(
    result: Any, variant: str, header: int, line: int
) -> None:
    assert len(_regions(result, header, line)) == 1


@pytest.mark.parametrize("variant,header,line", VARIANTS)  # type: ignore[misc]
def test_the_recursive_call_in_the_loop_is_one_task(result: Any, variant: str, header: int, line: int) -> None:
    assert len(_tasks(result, line)) == 1


@pytest.mark.parametrize("variant,header,line", VARIANTS)  # type: ignore[misc]
def test_the_task_works_on_a_copy_of_the_cursor(result: Any, variant: str, header: int, line: int) -> None:
    """omp-tasks: ``vlist`` is a local variable of the creating function, so the task is created with its value."""
    (task,) = _tasks(result, line)
    assert task.first_private == ["vlist"]
    assert task.shared == [] and task.private == []


def test_nothing_else_is_a_task(result: Any) -> None:
    """The calls after the loop depend on each other (each reads what the one before wrote in the village), and
    omp-tasks has no task for them; the groups the explorer found for them have been wrong."""
    lines = {line for _, _, line in VARIANTS}
    others = [
        (p.region_start_line, p.region_end_line)
        for p in result.patterns.task
        if type(p) is TaskParallelismInfo and int(p.region_start_line) not in lines
    ]
    assert others == []


@pytest.mark.xfail(strict=True, reason=JOIN_REASON)  # type: ignore[misc]
@pytest.mark.parametrize("variant,header,line,after", GROUPS)  # type: ignore[misc]
def test_the_join_is_before_the_code_that_reads_what_the_tasks_wrote(
    result: Any, variant: str, header: int, line: int, after: int
) -> None:
    """omp-tasks: the taskwait is before check_patients_realloc, which reads the ``realloc_`` that the children's
    check_patients_assess wrote into the village."""
    (region,) = _regions(result, header, line)
    assert {a["line"] for a in region.after_dependences} == {f"1:{after}"}
