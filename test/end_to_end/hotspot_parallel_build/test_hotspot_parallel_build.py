# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A parallel build (`make -j`) with the hotspot detection gives every code region an id of its own.

All compiler processes of a build share the region counter (`hotspot_detection/private/temp.txt`), `cs_id.txt` and
`FileMapping.txt`; the pass holds a file lock while it hands out ids. Without it, two processes started from the same
counter value and handed out the same ids (on the program below, `make -j4` collided in every one of 10 builds).

The order of the ids differs between parallel builds, so the tests compare the set of regions (kind, line, file,
function) with the one of a serial build instead of the files themselves. The runtime, the analyzer and the project
manager rely on the ids being exactly 1..N, N = number of lines of cs_id.txt."""

import os
import pathlib
import shutil
import subprocess
from typing import Dict, List, Set, Tuple

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("discopop_hotspot_cxx") is None or shutil.which("make") is None,
    reason="discopop_hotspot_cxx or make not found",
)

TRANSLATION_UNITS = 16
FUNCTIONS_PER_UNIT = 20
LOOPS_PER_FUNCTION = 3
JOBS = 4

MAKEFILE = """\
SOURCES := $(wildcard *.cpp)
OBJECTS := $(SOURCES:.cpp=.o)

prog: $(OBJECTS)
\t$(CXX) $(OBJECTS) -o prog

%.o: %.cpp
\t$(CXX) -c $< -o $@
"""

RegionKey = Tuple[str, int, str, str]


def _unit_source(unit: int) -> str:
    lines = []
    for function in range(FUNCTIONS_PER_UNIT):
        lines.append(f"long f_{unit}_{function}(long n) {{")
        lines.append("  long s = 0;")
        for loop in range(LOOPS_PER_FUNCTION):
            lines.append("  for (long i = 0; i < n; ++i) {")
            lines.append(f"    s += i * {unit + function + loop + 1};")
            lines.append("  }")
        lines.append("  return s;")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _main_source() -> str:
    lines = []
    for unit in range(TRANSLATION_UNITS):
        for function in range(FUNCTIONS_PER_UNIT):
            lines.append(f"long f_{unit}_{function}(long n);")
    lines.append("int main() {")
    lines.append("  long s = 0;")
    for unit in range(TRANSLATION_UNITS):
        for function in range(FUNCTIONS_PER_UNIT):
            lines.append(f"  s += f_{unit}_{function}(3);")
    lines.append("  return s == 0;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _environment(project: pathlib.Path) -> Dict[str, str]:
    env = dict(os.environ)
    for name in list(env):
        if name in ("DOT_DISCOPOP", "DOT_DISCOPOP_PROFILER") or name.startswith("DP_PROJECT_"):
            del env[name]
    env["DOT_DISCOPOP"] = str(project / ".discopop")
    env["DP_PROJECT_ROOT_DIR"] = str(project)
    env["CXX"] = "discopop_hotspot_cxx"
    return env


def _build_and_run(root: pathlib.Path, jobs: int) -> pathlib.Path:
    """Builds the program with `make -j<jobs>` in a project of its own below root, runs it, returns the project."""
    project = root / f"j{jobs}"
    project.mkdir(parents=True)
    (project / ".discopop").mkdir()
    for unit in range(TRANSLATION_UNITS):
        (project / f"unit{unit}.cpp").write_text(_unit_source(unit))
    (project / "main.cpp").write_text(_main_source())
    (project / "Makefile").write_text(MAKEFILE)
    env = _environment(project)
    build = subprocess.run(
        ["make", f"-j{jobs}", "CXX=discopop_hotspot_cxx"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, build.stderr[-4000:]
    run = subprocess.run(["./prog"], cwd=project, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-4000:]
    return project


def _private(project: pathlib.Path) -> pathlib.Path:
    return project / ".discopop" / "hotspot_detection" / "private"


def _cs_ids(project: pathlib.Path) -> List[List[str]]:
    return [line.split() for line in (_private(project) / "cs_id.txt").read_text().splitlines() if line.strip()]


def _file_mapping(project: pathlib.Path) -> List[Tuple[int, str]]:
    entries = []
    for line in (project / ".discopop" / "FileMapping.txt").read_text().splitlines():
        if line.strip():
            file_id, name = line.split("\t", 1)
            entries.append((int(file_id), name))
    return entries


def _region_keys(project: pathlib.Path) -> Set[RegionKey]:
    files = dict(_file_mapping(project))
    return {
        (fields[1], int(fields[2]), files[int(fields[3])], fields[4] if len(fields) > 4 else "")
        for fields in _cs_ids(project)
    }


def _check_ids(project: pathlib.Path) -> None:
    rows = _cs_ids(project)
    ids = [int(fields[0]) for fields in rows]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"{len(duplicates)} region ids handed out more than once, e.g. {duplicates[:10]}"
    assert sorted(ids) == list(range(1, len(rows) + 1)), "the region ids are not exactly 1..N"
    counter = (_private(project) / "temp.txt").read_text().split()
    assert int(counter[-1]) == len(rows), "temp.txt does not continue after the last region id"

    mapping = _file_mapping(project)
    file_ids = [file_id for file_id, _ in mapping]
    names = [name for _, name in mapping]
    assert len(set(file_ids)) == len(file_ids), f"FileMapping.txt hands out a file id twice: {mapping}"
    assert len(set(names)) == len(names), f"FileMapping.txt holds a file twice: {mapping}"
    assert sorted(file_ids) == list(range(1, len(mapping) + 1)), f"the file ids are not exactly 1..N: {mapping}"

    results = sorted(_private(project).glob("hotspot_result_*.txt"))
    assert len(results) == 1
    assert len(results[0].read_text().splitlines()) == len(rows)


@pytest.fixture(scope="module")
def serial_build(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return _build_and_run(tmp_path_factory.mktemp("hotspot_build"), 1)


@pytest.fixture(scope="module")
def parallel_build(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return _build_and_run(tmp_path_factory.mktemp("hotspot_build"), JOBS)


def test_a_serial_build_numbers_all_regions(serial_build: pathlib.Path) -> None:
    _check_ids(serial_build)
    expected_regions = TRANSLATION_UNITS * FUNCTIONS_PER_UNIT * (1 + LOOPS_PER_FUNCTION) + 1  # + main
    assert len(_cs_ids(serial_build)) == expected_regions


def test_a_parallel_build_gives_every_region_an_id_of_its_own(parallel_build: pathlib.Path) -> None:
    _check_ids(parallel_build)


def test_a_parallel_build_instruments_the_same_regions_as_a_serial_one(
    serial_build: pathlib.Path, parallel_build: pathlib.Path
) -> None:
    def relative(keys: Set[RegionKey], project: pathlib.Path) -> Set[RegionKey]:
        return {(kind, line, os.path.relpath(name, project), function) for kind, line, name, function in keys}

    assert relative(_region_keys(parallel_build), parallel_build) == relative(_region_keys(serial_build), serial_build)
