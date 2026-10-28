# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the data flow of a loop task: what the code after the loop reads, and the data sharing."""

from pathlib import Path
from typing import Any

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from test.end_to_end.pipeline import run_pipeline

SRC = Path(__file__).parent / "src"


@pytest.fixture(scope="module")  # type: ignore[misc]
def loop_task(tmp_path_factory: pytest.TempPathFactory) -> Any:
    result = run_pipeline(SRC, tmp_path_factory.mktemp("task_loop_data_flow") / "src", "task")
    found = [p for p in result.patterns.task if getattr(p, "loop_start_line", None) is not None]
    tasks = [p for p in found if isinstance(p, TaskParallelismInfo) and not isinstance(p, ParallelRegionInfo)]
    regions = [p for p in found if isinstance(p, ParallelRegionInfo)]
    assert len(tasks) == 1 and len(regions) == 1, [(p.region_start_line, p.loop_start_line) for p in found]
    return tasks[0], regions[0]


def test_the_join_of_the_loop_task_is_the_line_that_reads_the_results(loop_task: Any) -> None:
    _, region = loop_task
    assert {(a["variable"], a["kind"], a["line"]) for a in region.after_dependences} == {("res", "RAW", "1:19")}


def test_the_loop_task_has_the_data_sharing_of_the_loop(loop_task: Any) -> None:
    task, _ = loop_task
    assert task.shared == ["res"]
    assert "n" in task.first_private
