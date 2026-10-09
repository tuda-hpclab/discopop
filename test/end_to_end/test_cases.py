# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Data-driven end-to-end tests: one test per directory under ``cases/`` that contains an ``expected.toml``.

Each case directory holds the test program in ``src/`` (a Makefile building ``prog`` with $CC/$CXX) and the
expected suggestions in ``expected.toml``::

    enable_patterns = "doall,reduction"   # optional, passed to discopop_explorer --enable-patterns
    run_args = "64"                       # optional, the arguments of the profiled run (./prog 64)
    xfail = "why the case fails today"    # optional, the case is expected to fail (strict: a pass is reported)

    [do_all]                              # one table per pattern type expected to be found
    lines = ["1:9"]                       # start lines (file id:line) of the expected patterns, exactly these
                                          # instead of lines, for a case that pins only some of them:
                                          #   includes = [...]  patterns that must be found, others are allowed
                                          #   excludes = [...]  patterns that must not be found

    [reduction]
    lines = ["1:42"]
    [reduction.clauses]                   # optional: the clauses every found pattern of this type must have
    reduction = ["+:d"]                   #   reductions are written as "operation:variable"
    shared = ["r1", "r2", "dr"]
    [reduction.allowed_clauses]           # optional: clauses that may additionally be found (a warning is issued)
    first_private = ["nd"]

A pattern type without a table must not be found at all. The pipeline runs in a temporary copy of ``src/`` (kept by
pytest for the last runs); a failing stage is reported as an error of the test, a mismatch as a failure.
"""

import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest

from discopop_library.result_classes.DetectionResult import DetectionResult
from test.end_to_end.pipeline import run_pipeline

CASES_DIR = Path(__file__).parent / "cases"
DEFAULT_ENABLE_PATTERNS = "doall,reduction"

_CASE_KEYS = {"enable_patterns", "run_args", "xfail"}
_PATTERN_KEYS = {"lines", "includes", "excludes", "clauses", "allowed_clauses"}
# the clause lists of a pattern checked for unexpected entries; "reduction" is only checked for missing ones
_SHARING_CLAUSES = ["private", "shared", "first_private", "last_private"]


def _load_expectation(case_dir: Path) -> dict[str, Any]:
    with open(case_dir / "expected.toml", "rb") as f:
        expectation = tomllib.load(f)
    for key, value in expectation.items():
        if key in _CASE_KEYS:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{case_dir}/expected.toml: unknown key '{key}'")
        unknown = set(value) - _PATTERN_KEYS
        if unknown:
            raise ValueError(f"{case_dir}/expected.toml: unknown keys {sorted(unknown)} in [{key}]")
        if "lines" in value and ("includes" in value or "excludes" in value):
            raise ValueError(f"{case_dir}/expected.toml: [{key}] has lines and includes/excludes")
    return expectation


def _collect_cases() -> list[Any]:
    params = []
    for expected_file in sorted(CASES_DIR.rglob("expected.toml")):
        case_dir = expected_file.parent
        expectation = _load_expectation(case_dir)
        marks = []
        if "xfail" in expectation:
            marks.append(pytest.mark.xfail(reason=expectation["xfail"], strict=True))
        params.append(pytest.param(case_dir, id=case_dir.relative_to(CASES_DIR).as_posix(), marks=marks))
    return params


@pytest.fixture
def detection(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[dict[str, Any], DetectionResult]:
    """Run the pipeline for the case; a failing stage makes the test an error rather than a failure."""
    case_dir: Path = request.param
    expectation = _load_expectation(case_dir)
    enable_patterns = expectation.get("enable_patterns", DEFAULT_ENABLE_PATTERNS)
    run_args = expectation.get("run_args", "")
    return expectation, run_pipeline(case_dir / "src", tmp_path / "src", enable_patterns, run_args)


def _clause_problems(pattern: Any, clauses: dict[str, list[str]], allowed: dict[str, list[str]]) -> list[str]:
    problems = []
    missing = []
    for clause_type, variables in clauses.items():
        found = pattern.__dict__.get(clause_type, [])
        for variable in variables:
            if clause_type == "reduction":
                operation, _, name = variable.partition(":")
                hit = any(v.operation == operation and v.name == name for v in found)
            else:
                hit = any(v.name == variable for v in found)
            if not hit:
                missing.append(f"{clause_type}({variable})")
    unexpected = []
    for clause_type in _SHARING_CLAUSES:
        for v in pattern.__dict__.get(clause_type, []):
            if v.name in clauses.get(clause_type, []):
                continue
            if v.name in allowed.get(clause_type, []):
                warnings.warn(
                    f"pattern at {pattern.start_line}: allowed but unnecessary clause {clause_type}({v.name})"
                )
            else:
                unexpected.append(f"{clause_type}({v.name})")
    if missing:
        problems.append(f"missing clauses {', '.join(missing)}")
    if unexpected:
        problems.append(f"unexpected clauses {', '.join(unexpected)}")
    return problems


def _compare(expectation: dict[str, Any], result: DetectionResult) -> list[str]:
    """All differences between the expectation and the detected patterns, one line each."""
    found_patterns: dict[str, list[Any]] = result.patterns.__dict__
    problems = []
    for pattern_type in sorted(set(expectation) - _CASE_KEYS - set(found_patterns)):
        problems.append(f"{pattern_type}: not a pattern type of the detection result ({sorted(found_patterns)})")
    for pattern_type, patterns in sorted(found_patterns.items()):
        expected = expectation.get(pattern_type, {})
        found_lines = {p.start_line for p in patterns}
        if "includes" in expected or "excludes" in expected:
            missing = sorted(set(expected.get("includes", [])) - found_lines)
            unexpected = sorted(set(expected.get("excludes", [])) & found_lines)
        else:
            expected_lines = set(expected.get("lines", []))
            missing = sorted(expected_lines - found_lines)
            unexpected = sorted(found_lines - expected_lines)
        if missing:
            problems.append(f"{pattern_type}: missing patterns at {', '.join(missing)}")
        if unexpected:
            problems.append(f"{pattern_type}: unexpected patterns at {', '.join(unexpected)}")
        if "clauses" in expected:
            for pattern in patterns:
                for problem in _clause_problems(pattern, expected["clauses"], expected.get("allowed_clauses", {})):
                    problems.append(f"{pattern_type} at {pattern.start_line}: {problem}")
    return problems


@pytest.mark.parametrize("detection", _collect_cases(), indirect=True)
def test_case(detection: tuple[dict[str, Any], DetectionResult]) -> None:
    expectation, result = detection
    problems = _compare(expectation, result)
    if problems:
        pytest.fail("detected patterns differ from expected.toml:\n  " + "\n  ".join(problems), pytrace=False)
