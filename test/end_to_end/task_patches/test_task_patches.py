# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the patches of task groups: they apply, compile with OpenMP and keep the output of the program.

The explorer writes the patches itself (discopop_patch_generator); a patch is applied with discopop_patch_applicator.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo
from test.end_to_end.pipeline import _environment, build_and_profile, explore

HERE = Path(__file__).parent


def _compiler() -> str:
    for candidate in ("gcc", "cc"):
        if shutil.which(candidate) is not None:
            return candidate
    pytest.skip("no C compiler")


def _patched_run(
    src_dir: Path, work_dir: Path, source_name: str, loop: bool = False
) -> Tuple[str, str, List[str], Any]:
    """(output of the program, output of the patched program, lines of the patched source, the regions)"""
    dot_discopop = build_and_profile(src_dir, work_dir)
    work = dot_discopop.parent
    env = _environment(work)
    run = subprocess.run(["./prog"], cwd=work, env=env, capture_output=True, text=True, check=True)
    # the profiled program reports that it wrote its results; its own output is the first line
    expected = run.stdout.splitlines()[0] + "\n"
    result = explore(dot_discopop, "task")
    regions = [
        p for p in result.patterns.task if isinstance(p, ParallelRegionInfo) and (p.loop_start_line is not None) == loop
    ]
    assert len(regions) == 1, [(r.region_start_line, r.region_end_line) for r in regions]
    patch_dir = dot_discopop / "patch_generator" / str(regions[0].pattern_id)
    assert list(patch_dir.glob("*.patch")), "the group has no patch"

    subprocess.run(
        ["discopop_patch_applicator", "-a", str(regions[0].pattern_id)],
        cwd=dot_discopop,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    source = work / source_name
    compiled = subprocess.run(
        [_compiler(), "-fopenmp", "-o", "patched", source_name], cwd=work, capture_output=True, text=True
    )
    assert compiled.returncode == 0, compiled.stderr
    patched = subprocess.run(["./patched"], cwd=work, capture_output=True, text=True, check=True).stdout
    return expected, patched, source.read_text().splitlines(), regions[0]


def test_the_patch_of_two_tasks_applies_compiles_and_keeps_the_output(tmp_path: Path) -> None:
    expected, patched, source, _ = _patched_run(HERE / "two_tasks", tmp_path / "src", "dep.c")
    assert patched == expected
    # the code after the group reads a and b: the patch waits for the tasks before the end of the region
    assert source[8:21] == [
        "int h(int k, int n) {",
        "  int a, b;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp task shared(a) firstprivate(k)",
        "  a = f(k);        // line 11",
        "  #pragma omp task shared(b) firstprivate(n)",
        "  b = f(n + 1);    // line 12",
        "  #pragma omp taskwait",
        "  }",
        "  return a + b;    // line 13",
        "}",
    ]


def test_the_patch_of_the_loop_tasks_ends_the_region_after_the_loop(tmp_path: Path) -> None:
    expected, patched, source, region = _patched_run(HERE / "loop", tmp_path / "src", "loop.c", loop=True)
    assert region.loop_start_line == "1:16"
    assert patched == expected
    assert source[13:25] == [
        "  int res[16];",
        "  int total;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  for (int k = 0; k < 16; k++) {",
        "    #pragma omp task shared(res) firstprivate(n)",
        "    store(&res[k], f(n + k));  // line 17",
        "  }",
        "  #pragma omp taskwait",
        "  }",
        "  total = res[3] + res[5];  // line 19",
    ]


def test_the_patch_of_tasks_writing_the_same_variable_orders_them_with_depend_clauses(tmp_path: Path) -> None:
    """Two writes of d: the output dependence is a depend clause of both tasks (they stay ordered, the result is the
    one of the serial program), the return statement reads d, so the patch waits for the tasks."""
    expected, patched, source, _ = _patched_run(HERE / "waw", tmp_path / "src", "waw.c")
    assert patched == expected
    text = "\n".join(source)
    assert text.count("depend(out: d)") == 2, text
    assert "#pragma omp taskwait" in text


def test_the_patch_of_a_reduction_loop_reduces_with_a_taskgroup(tmp_path: Path) -> None:
    expected, patched, source, region = _patched_run(HERE / "reduction", tmp_path / "src", "red.c", loop=True)
    assert patched == expected
    assert source[8:23] == [
        "int g(int n) {",
        "  int sum = 0;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp taskgroup task_reduction(+:sum)",
        "  {",
        "  for (int k = 0; k < 16; k++) {",
        "    #pragma omp task firstprivate(n) in_reduction(+:sum)",
        "    sum += f(n + k);  // line 11",
        "  }",
        "  }",
        "  }",
        "  return sum;",
        "}",
    ]


def test_the_patch_of_a_loop_task_with_a_last_private_variable_is_a_comment(tmp_path: Path) -> None:
    """Tasks have no lastprivate: the tasks of the iterations would race on last, so there is no pragma."""
    expected, patched, source, _ = _patched_run(HERE / "last_value", tmp_path / "src", "last.c", loop=True)
    assert patched == expected
    text = "\n".join(source)
    assert "#pragma omp" not in text
    assert "// DiscoPoP: task group not applicable as it is, the last iteration's value of last" in text
