# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the dependences of tasks (RAW, WAR, WAW) and of the reduction and last private variables of
loops of tasks, on the profile of ``src/dep.c``.

Statements with a RAW or WAR between them are never put into one group: the group ends before the dependent
statement, and the dependence is reported as what the code after the group needs (the join). Only a WAW registers no
data edge, so two tasks that write the same variable are one group with an output dependence between them."""

from pathlib import Path
from typing import Any, List, Set, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import run_pipeline

SRC = Path(__file__).parent / "src"


class _Found:
    def __init__(self, patterns: List[Any], source: List[str]) -> None:
        self.tasks: List[TaskParallelismInfo] = [
            p for p in patterns if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)
        ]
        self.regions: List[ParallelRegionInfo] = [p for p in patterns if isinstance(p, ParallelRegionInfo)]
        self.source = source

    def line(self, tag: str) -> int:
        return next(n for n, text in enumerate(self.source, start=1) if f"// {tag}" in text)

    def task(self, tag: str) -> TaskParallelismInfo:
        matching = [t for t in self.tasks if t.region_start_line == str(self.line(tag))]
        assert matching, (tag, [t.region_start_line for t in self.tasks])
        return matching[0]

    def region(self, tag: str) -> ParallelRegionInfo:
        task = self.task(tag)
        return next(r for r in self.regions if task.pattern_id in r.contains_patterns)


@pytest.fixture(scope="module")  # type: ignore[misc]
def found(tmp_path_factory: pytest.TempPathFactory) -> _Found:
    result = run_pipeline(SRC, tmp_path_factory.mktemp("task_dependences") / "src", "task")
    return _Found(result.patterns.task, (SRC / "dep.c").read_text().splitlines())


def _after(region: ParallelRegionInfo) -> Set[Tuple[str, str, str]]:
    return {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences}


def test_a_statement_that_reads_what_a_task_wrote_is_no_task_of_its_group_but_its_join(found: _Found) -> None:
    region = found.region("RAW_WRITE")
    assert region.task_dependences == []
    assert ("a", "RAW", f"1:{found.line('RAW_READ')}") in _after(region)
    assert all(t.region_start_line != str(found.line("RAW_READ")) for t in found.tasks)


def test_a_statement_that_overwrites_what_a_task_read_is_the_join_of_its_group_as_an_anti_dependence(
    found: _Found,
) -> None:
    region = found.region("WAR_READ")
    assert region.task_dependences == []
    assert ("p", "WAR", f"1:{found.line('WAR_WRITE')}") in _after(region)


def test_two_tasks_that_write_the_same_variable_have_an_output_dependence(found: _Found) -> None:
    first, second = found.task("WAW_FIRST"), found.task("WAW_SECOND")
    region = found.region("WAW_FIRST")
    assert region.task_dependences == [
        {"from_task": first.pattern_id, "to_task": second.pattern_id, "variable": "d", "kind": "WAW"}
    ]
    # both write it, so both are outs of the dependence, and it is shared
    assert first.out_dep == second.out_dep == ["d"]
    assert first.in_dep == second.in_dep == first.in_out_dep == second.in_out_dep == []
    assert first.shared == second.shared == ["d"]


def test_a_variable_that_the_iterations_of_a_loop_accumulate_into_is_a_reduction_of_the_loop_task(
    found: _Found,
) -> None:
    task = found.task("REDUCTION_BODY")
    assert task.loop_start_line is not None
    assert task.reduction == ["+:sum"]
    assert "sum" not in task.shared and "sum" not in task.private and "sum" not in task.first_private


def test_the_value_of_the_last_iteration_that_the_code_after_the_loop_needs_is_a_last_private_variable(
    found: _Found,
) -> None:
    task = found.task("LAST_BODY")
    assert task.loop_start_line is not None
    assert "last" in task.last_private
    assert "last" in task.shared  # the tasks write it to the variable of the caller
    assert task.reduction == []
