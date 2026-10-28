# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the data flow of tasks: what the code after a group of tasks reads, and the data sharing."""

from pathlib import Path
from typing import Any, List

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import run_pipeline

SRC = Path(__file__).parent / "src"


@pytest.fixture(scope="module")  # type: ignore[misc]
def tasks(tmp_path_factory: pytest.TempPathFactory) -> Any:
    result = run_pipeline(SRC, tmp_path_factory.mktemp("task_data_flow") / "src", "task")
    found = result.patterns.task
    return (
        [p for p in found if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)],
        [p for p in found if isinstance(p, ParallelRegionInfo)],
    )


def _task_at(tasks: Any, line: int) -> TaskParallelismInfo:
    matching: List[TaskParallelismInfo] = [t for t in tasks[0] if t.region_start_line == str(line)]
    assert matching, [t.region_start_line for t in tasks[0]]
    return matching[0]


def test_the_result_of_a_task_that_the_code_after_the_group_reads_is_shared(tasks: Any) -> None:
    first = _task_at(tasks, 11)
    assert first.shared == ["a"]
    assert first.first_private == ["k"]


def test_the_group_reports_the_line_after_the_region_that_reads_the_results(tasks: Any) -> None:
    region = next(r for r in tasks[1] if r.region_start_line == "11")
    after = {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences}
    assert after == {("a", "RAW", "1:13"), ("b", "RAW", "1:13")}
    assert region.task_dependences == []
