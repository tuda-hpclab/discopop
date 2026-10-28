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


def test_the_dependences_between_the_tasks_are_depend_clauses_and_need_no_taskwait(tmp_path: Path) -> None:
    tasks = [
        _task(0, 3, shared=["a"]),
        _task(1, 4, shared=["b"], out_dep=["b"]),
        _task(2, 5, shared=["c"], in_dep=["b"], in_out_dep=["a"]),
    ]
    dependences = [{"from_task": 1, "to_task": 2, "variable": "b", "kind": "RAW"}]
    code = _generate(tmp_path, _region([0, 1, 2], 3, 5, task_dependences=dependences), tasks)
    lines = code.splitlines()
    assert lines[lines.index("  #pragma omp task shared(c) depend(inout: a) depend(in: b)") :] == [
        "  #pragma omp task shared(c) depend(inout: a) depend(in: b)",
        "  c = f(b);",
        "  }",
        "  return a + b + c;",
        "}",
    ]
    assert "  #pragma omp task shared(b) depend(out: b)" in lines
    assert "  #pragma omp task shared(c) depend(inout: a) depend(in: b)" in lines
    assert "  #pragma omp task shared(a)" in lines  # no dependences, no clause
    assert code.count("taskwait") == 0


def test_a_variable_is_in_one_depend_clause_only(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"], in_dep=["a", "b"], out_dep=["a"], in_out_dep=["a", ""])]
    code = _generate(tmp_path, _region([0], 3, 3), tasks)
    assert "  #pragma omp task shared(a) depend(inout: a) depend(in: b)" in code.splitlines()


def test_a_taskwait_ends_the_group_if_the_code_after_it_needs_the_results(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"]), _task(1, 4, shared=["b"])]
    after = [{"task": 1, "variable": "b", "kind": "RAW", "line": "1:5", "at_return": False}]
    code = _generate(tmp_path, _region([0, 1], 3, 4, after_dependences=after), tasks)
    lines = code.splitlines()
    assert lines[lines.index("  b = f(n);") :] == [
        "  b = f(n);",
        "  #pragma omp taskwait",
        "  }",
        "  c = f(b);",
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


LOOP_SOURCE = (
    "void g(int n) {\n  int sum = 0;\n  for (int k = 0; k < n; k++) {\n    sum += f(k);\n  }\n  use(sum);\n}\n"
)


def _loop_group(tmp_path: Path, **task_extra: Any) -> str:
    task = _task(0, 4, **task_extra, loop_start_line="1:3")
    region = _region([0], 3, 4, loop_start_line="1:3", loop_end_line="1:5")
    return _generate(tmp_path, region, [task], LOOP_SOURCE)


def test_a_reduction_of_loop_tasks_is_a_taskgroup_around_the_loop_and_an_in_reduction_clause(tmp_path: Path) -> None:
    code = _loop_group(tmp_path, reduction=["+:sum"], shared=["sum"], first_private=["sum", "n"])
    assert code.splitlines() == [
        "void g(int n) {",
        "  int sum = 0;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp taskgroup task_reduction(+:sum)",
        "  {",
        "  for (int k = 0; k < n; k++) {",
        "    #pragma omp task firstprivate(n) in_reduction(+:sum)",
        "    sum += f(k);",
        "  }",
        "  }",
        "  }",
        "  use(sum);",
        "}",
    ]


def test_a_reduction_group_needs_no_taskwait_after_the_taskgroup(tmp_path: Path) -> None:
    after = [{"task": 0, "variable": "sum", "kind": "RAW", "line": "1:6", "at_return": False}]
    task = _task(0, 4, reduction=["+:sum"], loop_start_line="1:3")
    region = _region([0], 3, 4, loop_start_line="1:3", loop_end_line="1:5", after_dependences=after)
    code = _generate(tmp_path, region, [task], LOOP_SOURCE)
    assert code.count("taskwait") == 0
    assert code.count("{") == code.count("}")


def test_tasks_of_a_group_reducing_the_same_variable_share_one_taskgroup(tmp_path: Path) -> None:
    source = "void g(int n) {\n  int sum = 0;\n  sum += f(n);\n  sum += f(n + 1);\n  use(sum);\n}\n"
    tasks = [
        _task(0, 3, first_private=["n"], reduction=["+:sum"]),
        _task(1, 4, first_private=["n"], reduction=["+:sum"], in_out_dep=["sum"]),
    ]
    code = _generate(tmp_path, _region([0, 1], 3, 4), tasks, source)
    assert code.splitlines() == [
        "void g(int n) {",
        "  int sum = 0;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp taskgroup task_reduction(+:sum)",
        "  {",
        "  #pragma omp task firstprivate(n) in_reduction(+:sum)",
        "  sum += f(n);",
        "  #pragma omp task firstprivate(n) in_reduction(+:sum) depend(inout: sum)",
        "  sum += f(n + 1);",
        "  }",
        "  }",
        "  use(sum);",
        "}",
    ]


def test_a_reduction_of_an_unknown_operation_is_left_to_the_reader(tmp_path: Path) -> None:
    code = _loop_group(tmp_path, reduction=["?:sum"])
    assert "#pragma" not in code
    assert "// DiscoPoP: task group not applicable as it is, the operation of the reduction of sum is unknown" in code


def test_a_variable_with_two_reduction_operations_is_left_to_the_reader(tmp_path: Path) -> None:
    source = "void g(int n) {\n  int sum = 0;\n  sum += f(n);\n  sum *= f(n + 1);\n}\n"
    tasks = [_task(0, 3, reduction=["+:sum"]), _task(1, 4, reduction=["*:sum"])]
    code = _generate(tmp_path, _region([0, 1], 3, 4), tasks, source)
    assert "#pragma" not in code
    assert "the reduction of sum has different operations" in code


def test_a_dependence_without_a_variable_name_is_a_taskwait_before_the_dependent_task(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"]), _task(1, 4, shared=["b"]), _task(2, 5, shared=["c"])]
    dependences = [{"from_task": 0, "to_task": 2, "variable": "", "kind": "RAW"}]
    code = _generate(tmp_path, _region([0, 1, 2], 3, 5, task_dependences=dependences), tasks)
    lines = code.splitlines()
    assert lines[lines.index("  b = f(n);") :] == [
        "  b = f(n);",
        "  #pragma omp taskwait",
        "  #pragma omp task shared(c)",
        "  c = f(b);",
        "  }",
        "  return a + b + c;",
        "}",
    ]
    assert code.count("taskwait") == 1


def test_a_named_dependence_needs_no_taskwait(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"], out_dep=["a"]), _task(1, 4, shared=["b"], in_dep=["a"])]
    dependences = [{"from_task": 0, "to_task": 1, "variable": "a", "kind": "RAW"}]
    code = _generate(tmp_path, _region([0, 1], 3, 4, task_dependences=dependences), tasks)
    assert "taskwait" not in code


def test_a_last_private_variable_of_loop_tasks_makes_the_group_not_applicable_as_it_is(tmp_path: Path) -> None:
    code = _loop_group(tmp_path, shared=["last"], last_private=["last"])
    assert "#pragma" not in code
    expected = "// DiscoPoP: task group not applicable as it is, the last iteration's value of last is needed"
    assert expected + " after the loop, see the suggestion" in code


# --- recursion: the parallel region belongs around the call that enters it ---------------------------------------

FIB = """\
long fib(int n) {
  long x, y;
  if (n < 2) return n;
  x = fib(n - 1);
  y = fib(n - 2);
  return x + y;
}
"""
MAIN = """\
long fib(int n);
int main() {
  long r;
  r = fib(20);
  return 0;
}
"""


def _recursive(tmp_path: Path, entries: List[str], main: str = MAIN, **region_extra: Any) -> Dict[int, str]:
    (tmp_path / "fib.c").write_text(FIB)
    (tmp_path / "main.c").write_text(main)
    tasks = [_task(0, 4, shared=["x"], first_private=["n"]), _task(1, 5, shared=["y"], first_private=["n"])]
    region = _region([0, 1], 4, 5, entry_call_lines=entries, **region_extra)
    return from_json_strings(
        {1: tmp_path / "fib.c", 2: tmp_path / "main.c"},
        {"task": [json.dumps(region)]},
        skip_compilation_check=True,
        contained_patterns={"task": [json.dumps(t) for t in tasks]},
    )


def test_a_recursive_group_has_no_region_in_the_function_but_tasks_and_a_taskwait(tmp_path: Path) -> None:
    code = _recursive(tmp_path, ["2:4"])[1]
    assert code.splitlines() == [
        "long fib(int n) {",
        "  long x, y;",
        "  if (n < 2) return n;",
        "  #pragma omp task shared(x) firstprivate(n)",
        "  x = fib(n - 1);",
        "  #pragma omp task shared(y) firstprivate(n)",
        "  y = fib(n - 2);",
        "  #pragma omp taskwait",
        "  return x + y;",
        "}",
    ]


def test_the_entry_call_of_another_file_gets_the_region_in_the_patch_of_that_file(tmp_path: Path) -> None:
    result = _recursive(tmp_path, ["2:4"])
    assert "#pragma omp parallel" not in result[1]
    assert result[2].splitlines() == [
        "long fib(int n);",
        "int main() {",
        "  long r;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  r = fib(20);",
        "  return 0;",
        "}",
    ]


def test_every_entry_call_gets_a_region(tmp_path: Path) -> None:
    main = "void a() {\n  fib(1);\n}\nvoid b() {\n  fib(2);\n}\n"
    result = _recursive(tmp_path, ["2:2", "2:5"], main=main)
    assert result[2].count("#pragma omp parallel") == 2 and result[2].count("#pragma omp single") == 2


def test_an_entry_call_that_declares_a_variable_leaves_the_group_to_the_reader(tmp_path: Path) -> None:
    result = _recursive(tmp_path, ["2:3"], main=MAIN.replace("long r;\n  r = fib(20);", "long r = fib(20);\n"))
    assert "#pragma" not in result[1] and "#pragma" not in result.get(2, "")
    assert "declares a variable" in result[1]


def test_the_reduction_taskgroup_of_a_recursion_is_the_join(tmp_path: Path) -> None:
    (tmp_path / "s.c").write_text(
        "long s(int n) {\n  long sum = 0;\n  sum += s(n - 1);\n  sum += s(n - 2);\n  return sum;\n}\n"
    )
    tasks = [
        _task(0, 3, reduction=["+:sum"], first_private=["n"]),
        _task(1, 4, reduction=["+:sum"], first_private=["n"]),
    ]
    region = _region([0, 1], 3, 4, entry_call_lines=["1:9"])
    result = from_json_strings(
        {1: tmp_path / "s.c"},
        {"task": [json.dumps(region)]},
        skip_compilation_check=True,
        contained_patterns={"task": [json.dumps(t) for t in tasks]},
    )
    code = result[1]
    assert "#pragma omp taskgroup task_reduction(+:sum)" in code
    assert "#pragma omp taskwait" not in code and "#pragma omp parallel" not in code
    assert code.count("{") == 2 and code.count("}") == 2


def test_a_group_without_entry_calls_keeps_its_region_in_the_function(tmp_path: Path) -> None:
    tasks = [_task(0, 3, shared=["a"], first_private=["k"]), _task(1, 4, shared=["b"], first_private=["n"])]
    code = _generate(tmp_path, _region([0, 1], 3, 4, entry_call_lines=[]), tasks)
    assert "#pragma omp parallel" in code


def test_is_declaration() -> None:
    from discopop_library.CodeGenerator.classes.UnpackedSuggestion import _is_declaration

    for text in ("long long r = fib(n);", "  const int *p = f();", "std::vector<int> v(f());", "struct s t = g();"):
        assert _is_declaration(text), text
    for other in ("res = fib(n);", "  a[i] = fib(n);", "fib(n);", "return fib(n);", "else fib(n);", "*p = f();", None):
        assert not _is_declaration(other), other
