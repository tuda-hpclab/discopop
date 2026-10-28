# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the dependences between tasks that only show in the functions the tasks call, on the profile of
``src/callees.c``.

Two tasks that call one function which writes the same variable through a pointer (``set(&d, n); set(&d, n + 1);``)
have an output dependence between them, although both accesses lie in the callee. Tasks that call a function with
locals but without a write the caller sees (the callee's locals reuse the same stack addresses in both calls) have
none."""

from pathlib import Path
from typing import Any, List

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

    def region(self, tag: str) -> ParallelRegionInfo:
        line = next(n for n, text in enumerate(self.source, start=1) if f"// {tag}" in text)
        task = next(t for t in self.tasks if t.region_start_line == str(line))
        return next(r for r in self.regions if task.pattern_id in r.contains_patterns)


@pytest.fixture(scope="module")  # type: ignore[misc]
def found(tmp_path_factory: pytest.TempPathFactory) -> _Found:
    result = run_pipeline(SRC, tmp_path_factory.mktemp("task_dependences_callees") / "src", "task")
    return _Found(result.patterns.task, (SRC / "callees.c").read_text().splitlines())


def test_two_tasks_that_write_the_same_variable_in_a_shared_callee_have_an_output_dependence(found: _Found) -> None:
    region = found.region("SHARED_FIRST")
    first, second = region.contains_patterns[:2]
    assert len(region.contains_patterns) == 2
    waw = [d for d in region.task_dependences if d["kind"] == "WAW"]
    assert waw, region.task_dependences
    assert all(d["from_task"] == first and d["to_task"] == second for d in waw)
    # a name of the scope of the group (the callee calls the variable ``p``, which the caller does not know) or none
    assert all(d["variable"] in ("d", "") for d in waw)


def test_tasks_that_call_a_function_with_locals_but_no_shared_write_have_no_dependence(found: _Found) -> None:
    assert found.region("CONTROL_FIRST").task_dependences == []


def test_tasks_that_call_a_function_with_local_arrays_and_structs_have_no_dependence(found: _Found) -> None:
    assert found.region("LOCALS_FIRST").task_dependences == []
