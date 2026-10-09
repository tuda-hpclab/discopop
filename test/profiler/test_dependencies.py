# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Dependency detection of the profiler: one test class per category (RAW, WAR, WAW, NONE), one test per case.

A case is a directory ``<category>/<case>/`` holding ``test.cpp``, a ``Makefile`` (``make`` compiles it with
``discopop_cxx`` and runs it) and ``expected.toml``::

    required = ["1:3 RAW 1:2|z"]          # each must be a substring of a reported dependency (dynamic or static)
    forbidden = [                         # optional: none of these may be reported by the dynamic profiling
        { type = "WAR", var = "x" },      #   a dependency type and variable
        { sink = "1:7", var = "y" },      #   a sink location and variable
    ]

The tests are named ``Test<category>::test_dependencies[<case>]``. Before the first test of a class, the selected cases
of its category (e.g. only ``raw_52`` with ``-k raw_52``) are built and profiled in parallel, each in its own temporary
copy (pytest keeps the last runs for inspection); every test then checks the results of its case.
"""

import os
import shutil
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from test.profiler.utilities import get_dependencies

HERE = Path(__file__).parent


def _cases(category: str) -> list[Path]:
    return sorted(p.parent for p in (HERE / category).glob("*/expected.toml"))


def _profile(case: Path, work_dir: Path) -> str | None:
    """Copy the case to work_dir, build and run it; the output of make if that failed, otherwise None."""
    shutil.copytree(
        case, work_dir, ignore=shutil.ignore_patterns("expected.toml", ".discopop", "*.exe", "a.out", "__pycache__")
    )
    result = subprocess.run(["make"], cwd=work_dir, capture_output=True, text=True)
    if result.returncode != 0:
        return f"make failed (exit code {result.returncode}) in {work_dir}\n{result.stdout}\n{result.stderr}"
    return None


def _problems(expected: dict[str, Any], profiler_dir: Path) -> list[str]:
    dynamic_deps = get_dependencies(str(profiler_dir / "dynamic_dependencies.txt"))
    static_path = profiler_dir / "static_dependencies.txt"
    static_deps = get_dependencies(str(static_path)) if static_path.exists() else []
    deps = dynamic_deps + static_deps

    problems = [f"missing {r}" for r in expected["required"] if not any(r in dep for dep in deps)]
    # false positives are only checked in the exact dynamic trace: the static analysis is a conservative
    # may-analysis, a legitimate over-approximation of it must not fail the test
    for dep in dynamic_deps:
        properties = {"sink": dep.split(" ")[0], "type": dep.split(" ")[1], "var": dep.split("|")[1].split("(")[0]}
        for forbidden in expected.get("forbidden", []):
            if all(properties[key] == value for key, value in forbidden.items()):
                problems.append(f"forbidden {dep}")
    # a dependency is reported once per pair of callpath states, i.e. possibly several times
    return list(dict.fromkeys(problems))


@pytest.fixture(scope="class")
def profiled(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> dict[Path, Any]:
    """Build and profile the cases of the requesting class that are selected in this session, in parallel.

    Returns {case: (work directory, output of make if that failed, otherwise None)}.
    """
    selected = [
        item.callspec.params["case"]  # type: ignore[attr-defined]
        for item in request.session.items
        if getattr(item, "cls", None) is request.cls
    ]
    work_root = tmp_path_factory.mktemp(request.cls.CATEGORY)
    # all cores also when pytest-xdist runs the classes at the same time: the cases are short, idle cores cost more
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
        errors = pool.map(lambda case: _profile(case, work_root / case.name), selected)
        return {case: (work_root / case.name, error) for case, error in zip(selected, errors)}


class _Category:
    """Base of the test classes (not collected itself): CATEGORY is the directory of the cases."""

    CATEGORY: str

    def test_dependencies(self, case: Path, profiled: dict[Path, Any]) -> None:
        work_dir, build_error = profiled[case]
        if build_error is not None:
            pytest.fail(build_error, pytrace=False)
        with open(case / "expected.toml", "rb") as f:
            expected = tomllib.load(f)
        problems = _problems(expected, work_dir / ".discopop" / "profiler")
        if problems:
            pytest.fail(f"{case.relative_to(HERE)} ({work_dir}):\n  " + "\n  ".join(problems), pytrace=False)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if metafunc.cls is not None and issubclass(metafunc.cls, _Category) and "case" in metafunc.fixturenames:
        cases = _cases(metafunc.cls.CATEGORY)
        metafunc.parametrize("case", cases, ids=[case.name for case in cases])


class TestRAW(_Category):
    CATEGORY = "RAW"


class TestWAR(_Category):
    CATEGORY = "WAR"


class TestWAW(_Category):
    CATEGORY = "WAW"


class TestNONE(_Category):
    CATEGORY = "NONE"


# a new category directory needs its class here
assert {p.parent.parent.name for p in HERE.glob("*/*/expected.toml")} == {
    cls.CATEGORY for cls in _Category.__subclasses__()
}
