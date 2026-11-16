# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Builds without DOT_DISCOPOP: the compiler calls and the instrumented program find the .discopop directory of the
project (the nearest one from the current directory upwards, see dputil::FindDotDiscopop and
profiler/scripts/dp_environment.sh), and the program remembers it, so it writes its results there from any directory.

The environment of every call has no DOT_DISCOPOP and no DP_PROJECT_* variable."""

import os
import pathlib
import shutil
import subprocess
from typing import Dict, List

import pytest

MAIN_CPP = """#include <cstdio>

int main() {
  int a[100];
  long sum = 0;
  for (int i = 0; i < 100; ++i) {
    a[i] = i;
  }
  for (int i = 0; i < 100; ++i) {
    sum += a[i];
  }
  std::printf("%ld\\n", sum);
  return 0;
}
"""

CMAKE_LISTS = """cmake_minimum_required(VERSION 3.10)
project(discovery CXX)
add_executable(prog src/main.cpp)
"""


def _environment() -> Dict[str, str]:
    env = dict(os.environ)
    for name in list(env):
        if name in ("DOT_DISCOPOP", "DOT_DISCOPOP_PROFILER") or name.startswith("DP_PROJECT_"):
            del env[name]
    return env


def _run(command: List[str], cwd: pathlib.Path, env: Dict[str, str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "build").mkdir()
    (root / "src" / "main.cpp").write_text(MAIN_CPP)
    (root / "CMakeLists.txt").write_text(CMAKE_LISTS)
    return root


def _dot_discopop_directories(root: pathlib.Path) -> List[pathlib.Path]:
    return sorted(path for path in root.rglob(".discopop") if path.is_dir())


def _compile_in_build(root: pathlib.Path) -> "subprocess.CompletedProcess[str]":
    return _run(["discopop_cxx", "../src/main.cpp", "-o", "prog"], root / "build", _environment())


def test_a_build_directory_below_the_project_uses_the_dot_discopop_of_the_project(project: pathlib.Path) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    process = _compile_in_build(project)
    assert process.returncode == 0, process.stderr
    assert "WARNING: DOT_DISCOPOP" not in process.stderr
    # everything is in the .discopop of the project, nothing in the directory the compiler was called from
    assert _dot_discopop_directories(project) == [project / ".discopop"]
    for name in ("FileMapping.txt", "profiler/Data.xml", "profiler/ast_dump.json"):
        assert (project / ".discopop" / name).is_file(), name
    mapped = [
        line.split("\t")[1].strip() for line in (project / ".discopop" / "FileMapping.txt").read_text().splitlines()
    ]
    assert mapped == [str(project / "src" / "main.cpp")]


def test_the_program_writes_its_results_to_the_project_from_any_directory(
    project: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    assert _compile_in_build(project).returncode == 0
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    process = _run([str(project / "build" / "prog")], elsewhere, _environment())
    assert process.returncode == 0, process.stderr
    assert process.stdout.splitlines()[0] == "4950"
    assert (project / ".discopop" / "profiler" / "dynamic_dependencies.txt").stat().st_size > 0
    assert not (elsewhere / ".discopop").exists()


def test_dot_discopop_of_the_environment_wins_over_the_recorded_directory(
    project: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    assert _compile_in_build(project).returncode == 0
    other = tmp_path / "other" / ".discopop"
    (other / "profiler").mkdir(parents=True)
    process = _run([str(project / "build" / "prog")], tmp_path, {**_environment(), "DOT_DISCOPOP": str(other)})
    assert process.returncode == 0, process.stderr
    assert (other / "profiler" / "dynamic_dependencies.txt").stat().st_size > 0
    assert not (project / ".discopop" / "profiler" / "dynamic_dependencies.txt").exists()


def test_dot_discopop_of_the_environment_wins_in_the_build(project: pathlib.Path, tmp_path: pathlib.Path) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    explicit = tmp_path / "explicit" / ".discopop"
    explicit.parent.mkdir()
    process = _run(
        ["discopop_cxx", "../src/main.cpp", "-o", "prog"],
        project / "build",
        {**_environment(), "DOT_DISCOPOP": str(explicit), "DP_PROJECT_ROOT_DIR": str(project)},
    )
    assert process.returncode == 0, process.stderr
    assert (explicit / "FileMapping.txt").is_file()
    assert not (project / ".discopop" / "FileMapping.txt").exists()


def test_the_scope_is_the_project_directory(project: pathlib.Path) -> None:
    # without DP_PROJECT_ROOT_DIR the pass instruments what it is given ("/"): the root of the .discopop is the scope
    (project / ".discopop" / "project").mkdir(parents=True)
    outside = pathlib.Path("/tmp") / f"dp_outside_{os.getpid()}.cpp"
    outside.write_text("int g() { return 2; }\n")
    try:
        process = _run(["discopop_cxx", "-c", str(outside), "-o", "outside.o"], project / "build", _environment())
    finally:
        outside.unlink()
    assert process.returncode == 0, process.stderr
    mapping = project / ".discopop" / "FileMapping.txt"
    assert not mapping.exists() or str(outside) not in mapping.read_text()


def test_a_build_without_any_dot_discopop_warns_and_uses_the_current_directory(project: pathlib.Path) -> None:
    process = _compile_in_build(project)
    assert process.returncode == 0, process.stderr
    assert "no .discopop directory exists in the current directory or above" in process.stderr
    assert _dot_discopop_directories(project) == [project / "build" / ".discopop"]


def test_a_leftover_directory_below_the_project_is_the_nearest_but_reported(project: pathlib.Path) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    (project / "build" / ".discopop" / "profiler").mkdir(parents=True)
    process = _compile_in_build(project)
    assert process.returncode == 0, process.stderr
    assert "holds no project configuration" in process.stderr
    # the nearest one is used (and its directory is the scope, which does not contain the source file)
    assert not (project / ".discopop" / "FileMapping.txt").exists()
    assert (project / "build" / ".discopop" / "profiler").is_dir()


def test_a_build_outside_of_the_project_finds_the_project_from_the_source_file(
    project: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    build = tmp_path / "out_of_tree"
    build.mkdir()
    process = _run(["discopop_cxx", str(project / "src" / "main.cpp"), "-o", "prog"], build, _environment())
    assert process.returncode == 0, process.stderr
    assert (project / ".discopop" / "FileMapping.txt").is_file()
    assert not (build / ".discopop").exists()


@pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake not found")
def test_a_cmake_build_uses_one_dot_discopop(project: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """CMake compiles its test programs in directories of its own below build/: every one of them would have got a
    .discopop (with ids that do not fit together), and the compiler checks need a working compiler."""
    (project / ".discopop" / "project").mkdir(parents=True)
    wrapper = pathlib.Path(shutil.which("discopop_cxx") or "")
    configure = _run(
        ["cmake", "-S", "..", "-B", ".", f"-DCMAKE_CXX_COMPILER={wrapper}", "-DCMAKE_BUILD_TYPE=Release"],
        project / "build",
        _environment(),
    )
    assert configure.returncode == 0, configure.stdout + configure.stderr
    build = _run(["cmake", "--build", "."], project / "build", _environment())
    assert build.returncode == 0, build.stdout + build.stderr
    assert _dot_discopop_directories(project) == [project / ".discopop"]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    process = _run([str(project / "build" / "prog")], elsewhere, _environment())
    assert process.returncode == 0, process.stderr
    assert (project / ".discopop" / "profiler" / "dynamic_dependencies.txt").stat().st_size > 0


@pytest.mark.skipif(shutil.which("discopop_hotspot_cxx") is None, reason="discopop_hotspot_cxx not found")
def test_the_hotspot_detection_finds_the_dot_discopop_of_the_project_as_well(
    project: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (project / ".discopop" / "project").mkdir(parents=True)
    process = _run(["discopop_hotspot_cxx", "../src/main.cpp", "-o", "prog"], project / "build", _environment())
    assert process.returncode == 0, process.stderr
    assert _dot_discopop_directories(project) == [project / ".discopop"]
    assert (project / ".discopop" / "hotspot_detection" / "private" / "cs_id.txt").is_file()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    process = _run([str(project / "build" / "prog")], elsewhere, _environment())
    assert process.returncode == 0, process.stderr
    assert list((project / ".discopop" / "hotspot_detection" / "private").glob("hotspot_result_*.txt"))
    assert not (elsewhere / ".discopop").exists()
