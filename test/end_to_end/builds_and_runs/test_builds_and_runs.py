# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Build once, run many times: the project manager's command line with the real profiler.

A dp build is compiled once and kept; every run writes into a run directory of its own; activating a run puts its
data into the project, with the paths of the project, where the explorer finds suggestions.
"""

import json
import pathlib
import subprocess
from typing import Any, Dict, List

MAIN_CPP = """#include <cstdio>
int main(int argc, char** argv) {
  const int n = 100;
  int a[n];
  for (int i = 0; i < n; ++i) { a[i] = i * 2; }
  long sum = 0;
  for (int i = 0; i < n; ++i) { sum += a[i]; }
  std::printf("%ld\\n", sum);
  return 0;
}
"""

COMPILE_SH = """#!/bin/bash
$CXX $CXXFLAGS main.cpp -o prog
"""

EXECUTE_SH = """#!/bin/bash
./prog
"""


def _manager(root: pathlib.Path, *arguments: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["discopop_project_manager", "-p", str(root), *arguments], capture_output=True, text=True, timeout=600
    )


def _project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.cpp").write_text(MAIN_CPP)
    _manager(root, "--init")
    configs = root / ".discopop" / "project" / "configs"
    (configs / "tiny").mkdir()
    for path, content in ((configs / "compile.sh", COMPILE_SH), (configs / "tiny" / "execute.sh", EXECUTE_SH)):
        path.write_text(content)
        path.chmod(0o755)
    return root


def _manifest(root: pathlib.Path) -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads((root / ".discopop" / "project" / "builds" / "tiny_dp.json").read_text())
    return data


def _runs(tmp_path: pathlib.Path) -> List[pathlib.Path]:
    directory = tmp_path / "proj_discopop_builds" / "tiny_dp.runs"
    return sorted(directory.iterdir()) if directory.exists() else []


def test_a_build_serves_several_runs_and_a_run_can_be_activated(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    first = _manager(root, "-x", "tiny:dp:2")
    assert first.returncode == 0, first.stdout + first.stderr
    built_at = _manifest(root)["built_at"]
    assert (tmp_path / "proj_discopop_builds" / "tiny_dp" / "prog").exists()
    # nothing was built or run in the project
    assert not (root / "prog").exists() and not (root / ".discopop" / "profiler").exists()

    second = _manager(root, "-x", "tiny:dp:2")
    assert "Reusing the build tiny_dp" in second.stdout, second.stdout + second.stderr
    assert _manifest(root)["built_at"] == built_at
    runs = _runs(tmp_path)
    assert len(runs) == 2
    for run in runs:
        assert (run / "profiler" / "dynamic_dependencies.txt").stat().st_size > 0

    # a change of the sources makes the build stale: the next run compiles again, the runs stay
    (root / "main.cpp").write_text(MAIN_CPP + "// changed\n")
    assert "stale" in _manager(root, "--list-builds").stdout
    third = _manager(root, "-x", "tiny:dp:2")
    assert "Reusing" not in third.stdout and _manifest(root)["built_at"] > built_at
    assert len(_runs(tmp_path)) == 3 and all(run.is_dir() for run in runs)

    activated = _manager(root, "--activate-run")
    assert activated.returncode == 0, activated.stdout + activated.stderr
    mapping = (root / ".discopop" / "FileMapping.txt").read_text()
    assert str(root / "main.cpp") in mapping and "_discopop_builds" not in mapping
    assert (root / ".discopop" / "profiler" / "dynamic_dependencies.txt").exists()

    explorer = subprocess.run(
        ["discopop_explorer", "--enable-patterns", "reduction,doall"],
        cwd=root / ".discopop",
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert explorer.returncode == 0, explorer.stdout + explorer.stderr
    # the same suggestions as profiling in the project itself (-i) finds
    patches = sorted(p.name for p in (root / ".discopop" / "patch_generator").iterdir())
    assert patches, explorer.stdout + explorer.stderr


def test_builds_and_runs_are_only_deleted_on_request(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    _manager(root, "-x", "tiny:dp:2")
    _manager(root, "-x", "tiny:dp:2")
    assert len(_runs(tmp_path)) == 2
    deleted = _manager(root, "--delete-runs", _runs(tmp_path)[0].name)
    assert "Deleted 1 run(s)" in deleted.stdout and len(_runs(tmp_path)) == 1
    assert "Deleted 1 build(s)" in _manager(root, "--delete-builds").stdout
    assert not (tmp_path / "proj_discopop_builds" / "tiny_dp").exists()
    # the run does not need its build any more
    assert len(_runs(tmp_path)) == 1
    assert (root / "main.cpp").exists()
