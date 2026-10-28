# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""End-to-end test of the join of a task group whose results are read after the function returned, and of the names the
dependences carry.

``h`` (lines 20-23) passes the pointer parameters on to tasks that write through them (``put`` stores ``*out``),
``main`` reads the results; ``h2`` (34-37) writes globals; ``h3`` (40-45) writes locals that a callee (``show``,
line 44) reads inside of the function. ``control`` runs after ``h`` and must not show up. Both tasks of a group call
the same function, so the callpath state tells which task wrote what."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from mcp_server.tools.task_groups import describe, task_groups
from test.end_to_end.pipeline import build_and_profile, explore

SRC = Path(__file__).parent / "src"


@pytest.fixture(scope="module")  # type: ignore[misc]
def entries(tmp_path_factory: pytest.TempPathFactory) -> List[Dict[str, Any]]:
    """The task entries of patterns.json."""
    dot_discopop = build_and_profile(SRC, tmp_path_factory.mktemp("task_join_return") / "src")
    explore(dot_discopop, "task")
    patterns = json.loads((dot_discopop / "explorer" / "patterns.json").read_text())
    found: List[Dict[str, Any]] = patterns["patterns"]["task"]
    return found


@pytest.fixture  # type: ignore[misc]
def regions(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The records of the groups by the first line of their region."""
    return {p["region_start_line"]: p for p in entries if p["type"] == "PARALLELREGION"}


def _after(region: Dict[str, Any]) -> List[Tuple[int, str, str, Any, bool]]:
    return sorted((a["task"], a["variable"], a["kind"], a["line"], a["at_return"]) for a in region["after_dependences"])


def test_the_results_a_caller_reads_are_a_join_before_the_function_returns_named_by_the_parameters(
    regions: Dict[str, Dict[str, Any]],
) -> None:
    """``main`` knows the results as ``a`` and ``b``; the group's function as ``r1`` and ``r2``, each of one task."""
    region = regions["21"]
    assert region["region_end_line"] == "22"
    first, second = region["contains_patterns"]
    assert _after(region) == [(first, "r1", "RAW", None, True), (second, "r2", "RAW", None, True)]


def test_a_global_a_task_writes_keeps_its_name(regions: Dict[str, Dict[str, Any]]) -> None:
    region = regions["35"]
    first, second = region["contains_patterns"]
    assert _after(region) == [(first, "g1", "RAW", None, True), (second, "g2", "RAW", None, True)]


def test_a_callee_that_reads_the_results_in_the_function_is_named_by_the_functions_variables(
    regions: Dict[str, Dict[str, Any]],
) -> None:
    """``show(&a, &b)`` reads them as ``*p`` and ``*q``; the join is the line of the call, not the return."""
    region = regions["42"]
    first, second = region["contains_patterns"]
    assert _after(region) == [(first, "a", "RAW", "1:44", False), (second, "b", "RAW", "1:44", False)]


def test_the_tool_names_the_join_before_the_function_returns(
    entries: List[Dict[str, Any]], regions: Dict[str, Dict[str, Any]]
) -> None:
    groups = task_groups({"task": entries})
    text = "\n".join(describe(groups[str(regions["21"]["pattern_id"])], "ret.c", []))
    first, second = regions["21"]["contains_patterns"]
    assert (
        "  join: the tasks have to be complete before the function returns, because its caller "
        f"reads r1 (task {first}), reads r2 (task {second})"
    ) in text
    in_function = "\n".join(describe(groups[str(regions["42"]["pattern_id"])], "ret.c", []))
    assert "before ret.c:44, which reads a" in in_function
    assert "before the function returns" not in in_function
