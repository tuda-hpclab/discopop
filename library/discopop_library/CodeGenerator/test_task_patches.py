# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The code generated for task groups: a PARALLELREGION entry of the pattern type "task" with its TASK entries."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from discopop_library.CodeGenerator.CodeGenerator import from_json_strings

SOURCE = """\
int h(int k, int n) {
  int a, b, c;
  a = f(k);
  b = f(n);
  c = f(b);
  return a + b + c;
}
"""


def _task(
    pattern_id: int, line: int, end: Optional[int] = None, shared: Optional[List[str]] = None, **extra: Any
) -> Dict[str, Any]:
    return {
        "pattern_id": pattern_id,
        "type": "TASK",
        "start_line": "1:1",
        "end_line": "1:7",
        "pragma": ["#pragma omp task"],
        "region_start_line": str(line),
        "region_end_line": str(end if end is not None else line),
        "shared": shared or [],
        "private": [],
        "first_private": [],
        **extra,
    }


def _region(task_ids: List[int], start: int, end: int, **extra: Any) -> Dict[str, Any]:
    return {
        "pattern_id": 99,
        "type": "PARALLELREGION",
        "start_line": "1:1",
        "end_line": "1:7",
        "pragma": ["#pragma omp parallel", "#pragma omp single"],
        "region_start_line": str(start),
        "region_end_line": str(end),
        "contains_patterns": task_ids,
        "task_dependences": [],
        "after_dependences": [],
        **extra,
    }


def _generate(tmp_path: Path, region: Dict[str, Any], tasks: List[Dict[str, Any]], source: str = SOURCE) -> str:
    source_file = tmp_path / "h.c"
    source_file.write_text(source)
    contained = {"task": [json.dumps(t) for t in tasks]}
    result = from_json_strings(
        {1: source_file}, {"task": [json.dumps(region)]}, skip_compilation_check=True, contained_patterns=contained
    )
    return result[1]


def test_a_group_is_a_parallel_region_with_the_tasks_inside_and_the_join_at_its_end(tmp_path: Path) -> None:
    tasks = [
        _task(0, 3, shared=["a"], first_private=["k"]),
        _task(1, 4, shared=["b"], first_private=["n"]),
    ]
    code = _generate(tmp_path, _region([0, 1], 3, 4), tasks)
    assert code.splitlines() == [
        "int h(int k, int n) {",
        "  int a, b, c;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp task shared(a) firstprivate(k)",
        "  a = f(k);",
        "  #pragma omp task shared(b) firstprivate(n)",
        "  b = f(n);",
        "  }",
        "  c = f(b);",
        "  return a + b + c;",
        "}",
    ]


def test_a_variable_occurs_in_one_data_sharing_clause_only(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a", "k"], first_private=["k", "n"], private=["n", "x"])]
    code = _generate(tmp_path, _region([0], 3, 3), tasks)
    assert "  #pragma omp task shared(a,k) firstprivate(n) private(x)" in code.splitlines()


def test_a_task_that_depends_on_an_earlier_one_waits_for_it(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"]), _task(1, 4, shared=["b"]), _task(2, 5, shared=["c"])]
    dependences = [{"from_task": 1, "to_task": 2, "variable": "b", "kind": "RAW"}]
    code = _generate(tmp_path, _region([0, 1, 2], 3, 5, task_dependences=dependences), tasks)
    lines = code.splitlines()
    assert lines[lines.index("  c = f(b);") - 2 :] == [
        "  #pragma omp taskwait",
        "  #pragma omp task shared(c)",
        "  c = f(b);",
        "  }",
        "  return a + b + c;",
        "}",
    ]
    assert code.count("taskwait") == 1


def test_the_region_of_tasks_per_loop_iteration_ends_after_the_loop(tmp_path: Path) -> None:
    source = "void g(int *res) {\n  for (int k = 0; k < 16; k++) {\n    store(&res[k], f(k));\n  }\n  use(res);\n}\n"
    task = _task(0, 3, shared=["res"], loop_start_line="1:2")
    region = _region([0], 2, 3, loop_start_line="1:2", loop_end_line="1:4")
    code = _generate(tmp_path, region, [task], source)
    assert code.splitlines() == [
        "void g(int *res) {",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  for (int k = 0; k < 16; k++) {",
        "    #pragma omp task shared(res)",
        "    store(&res[k], f(k));",
        "  }",
        "  }",
        "  use(res);",
        "}",
    ]


def test_a_loop_region_without_the_end_of_the_loop_is_left_to_the_reader(tmp_path: Path) -> None:
    task = _task(0, 3, loop_start_line="1:2")
    code = _generate(tmp_path, _region([0], 2, 3, loop_start_line="1:2"), [task])
    assert "#pragma" not in code
    assert "the end of the loop is unknown" in code


def test_groups_that_cannot_be_placed_only_get_a_comment_so_that_they_keep_a_patch(tmp_path: Path) -> None:
    cases = {
        "tasks share lines": ([_task(0, 3), _task(1, 3)], _region([0, 1], 3, 3)),
        "the end of a task is unknown": ([_task(0, 3), _task(1, 4, 262143)], _region([0, 1], 3, 262143)),
        "a task starts at the header of its scope": ([_task(0, 1, 3), _task(1, 4)], _region([0, 1], 1, 4)),
    }
    for reason, (tasks, region) in cases.items():
        code = _generate(tmp_path, region, tasks)
        assert "#pragma" not in code, reason
        assert reason in code, reason
        assert len(code.splitlines()) == len(SOURCE.splitlines()) + 1, reason
