# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Dependency detection of the profiler: one test per category (RAW, WAR, WAW, NONE), one subtest per case.

A case is a directory ``<category>/<case>/`` holding ``test.cpp``, a ``Makefile`` (``make`` compiles it with
``discopop_cxx`` and runs it) and ``expected.toml``::

    required = ["1:3 RAW 1:2|z"]          # each must be a substring of a reported dependency (dynamic or static)
    forbidden = [                         # optional: none of these may be reported by the dynamic profiling
        { type = "WAR", var = "x" },      #   a dependency type and variable
        { sink = "1:7", var = "y" },      #   a sink location and variable
    ]

The cases of a category are built and profiled in parallel, each in its own copy below the test's ``tmp_path``
(pytest keeps the last runs for inspection), and checked one after another. ``DP_TEST_PROFILER_CASES`` restricts a run
to the cases matching one of its comma separated glob patterns, e.g. ``DP_TEST_PROFILER_CASES=raw_52,war_4*``.
"""

import fnmatch
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
CATEGORIES = sorted(p.name for p in HERE.iterdir() if p.is_dir() and any(p.glob("*/expected.toml")))


def _selected_cases(category: str) -> list[Path]:
    cases = sorted(p.parent for p in (HERE / category).glob("*/expected.toml"))
    patterns = [p.strip() for p in os.environ.get("DP_TEST_PROFILER_CASES", "").split(",") if p.strip()]
    if patterns:
        cases = [c for c in cases if any(fnmatch.fnmatch(c.name, p) for p in patterns)]
    return cases


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


@pytest.mark.parametrize("category", CATEGORIES)
def test_dependencies(category: str, tmp_path: Path, subtests: pytest.Subtests) -> None:
    cases = _selected_cases(category)
    if not cases:
        pytest.skip("no case selected by DP_TEST_PROFILER_CASES")
    # all cores also when pytest-xdist runs the categories at the same time: the cases are short, idle cores cost more
    workers = os.cpu_count() or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        build_errors = list(pool.map(lambda case: _profile(case, tmp_path / case.name), cases))

    for case, build_error in zip(cases, build_errors):
        with subtests.test(msg=case.name):
            if build_error is not None:
                pytest.fail(build_error, pytrace=False)
            with open(case / "expected.toml", "rb") as f:
                expected = tomllib.load(f)
            problems = _problems(expected, tmp_path / case.name / ".discopop" / "profiler")
            if problems:
                pytest.fail(
                    f"{case.relative_to(HERE)} ({tmp_path / case.name}):\n  " + "\n  ".join(problems), pytrace=False
                )
