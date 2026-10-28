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
    assert source[8:20] == [
        "int h(int k, int n) {",
        "  int a, b;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  #pragma omp task shared(a) firstprivate(k)",
        "  a = f(k);        // line 11",
        "  #pragma omp task shared(b) firstprivate(n)",
        "  b = f(n + 1);    // line 12",
        "  }",
        "  return a + b;    // line 13",
        "}",
    ]


def test_the_patch_of_the_loop_tasks_ends_the_region_after_the_loop(tmp_path: Path) -> None:
    expected, patched, source, region = _patched_run(HERE / "loop", tmp_path / "src", "loop.c", loop=True)
    assert region.loop_start_line == "1:16"
    assert patched == expected
    assert source[13:24] == [
        "  int res[16];",
        "  int total;",
        "  #pragma omp parallel",
        "  #pragma omp single",
        "  {",
        "  for (int k = 0; k < 16; k++) {",
        "    #pragma omp task shared(res) firstprivate(n)",
        "    store(&res[k], f(n + k));  // line 17",
        "  }",
        "  }",
        "  total = res[3] + res[5];  // line 19",
    ]
