# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for reading the profiler's loopstate_positions.txt and for assigning the loopstate positions
of a function's loops from it (TaskGraph.__assign_loopstate_positions_within_functions)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from discopop_explorer.classes.TaskGraph.Loops.TGStartLoopNode import TGStartLoopNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_explorer.classes.TaskGraph.loopstate_positions import (
    LoopstatePosition,
    read_loopstate_digit_counts,
    read_loopstate_positions,
)
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.aliases.NodeID import NodeID

FUNCTION = "_Z6kerneliiPdS_"

# The loops of
#    8: for k { if (...) { ... } else {
#   13:   for l { ... } } }
#   20: if (...) for g {
#   21:   for i { ... } }
# as (LoopNode id, entry CU id, start line).
LOOPS: List[Tuple[str, str, int]] = [("1:10", "1:2", 8), ("1:11", "1:5", 13), ("1:12", "1:7", 20), ("1:13", "1:8", 21)]


# --- reader -------------------------------------------------------------------------------


def test_reader_returns_none_without_file(tmp_path: Path) -> None:
    assert read_loopstate_positions(str(tmp_path / "loopstate_positions.txt")) is None


def test_reader_groups_entries_by_function(tmp_path: Path) -> None:
    path = tmp_path / "loopstate_positions.txt"
    path.write_text(
        "_Z1fv 0 0 1:3 1:8\n"
        "_Z1fv 1 1 - 1:13\n"
        "# a comment\n"
        "malformed line\n"
        "_Z1gv x 2 1:4 1:20\n"
        "_Z1gv 0 3 1:5 -\n"
        "_Z1fv 0 7 2:3 1:8\n"
    )

    mapping = read_loopstate_positions(str(path))

    assert mapping == {
        "_Z1fv": [
            LoopstatePosition("_Z1fv", 0, 0, "1:3", "1:8"),
            LoopstatePosition("_Z1fv", 1, 1, None, "1:13"),
            LoopstatePosition("_Z1fv", 0, 7, "2:3", "1:8"),
        ],
        "_Z1gv": [LoopstatePosition("_Z1gv", 0, 3, "1:5", None)],
    }


def test_digit_counts_are_read_from_the_callpath_labels(tmp_path: Path) -> None:
    path = tmp_path / "stateID_to_callpath_mapping.txt"
    path.write_text(
        "0 0 \n"
        "1 0 main\n"
        "2 1 main_loopstate03\n"
        "3 2 call_7\n"
        "4 3 _Z6kerneliiPdS_\n"
        "5 4 _Z6kerneliiPdS__loopstate033\n"
    )

    assert read_loopstate_digit_counts(str(path)) == {"main": 2, FUNCTION: 3}
    assert read_loopstate_digit_counts(str(tmp_path / "missing.txt")) == {}


# --- assignment ---------------------------------------------------------------------------


def _task_graph(build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path) -> TaskGraph:
    """A task graph of FUNCTION with the TGStartLoopNodes of LOOPS in a chain behind its function node.
    The PET holds the function, the LoopNodes and their entry CUs."""
    nodes = [make_node("1:0", NodeType.FUNC, name=FUNCTION, start_line=7, end_line=25)]
    edges = []
    for loop_node_id, cu_id, line in LOOPS:
        nodes.append(make_node(loop_node_id, NodeType.LOOP, name="loop", start_line=line, end_line=line + 1))
        nodes.append(make_node(cu_id, NodeType.CU, name="cu", start_line=line))
        edges.append(("1:0", loop_node_id, EdgeType.CHILD))
        edges.append((loop_node_id, cu_id, EdgeType.CHILD))
    pet = build_pet_graph(nodes, edges)
    tg: TaskGraph = build_task_graph(pet)
    previous: Any = TGFunctionNode(NodeID("1:0"), 0, 0)
    tg.add_node(previous)
    for index, (_, cu_id, _) in enumerate(LOOPS):
        loop = TGStartLoopNode(NodeID(cu_id), 1, index)
        tg.add_node(loop)
        tg.add_edge(previous, loop)
        previous = loop
    tg.dynamic_dependency_file = str(tmp_path / "dynamic_dependencies.txt")
    return tg


def _assign(tg: TaskGraph) -> Dict[str, Optional[int]]:
    tg._TaskGraph__assign_loopstate_positions_within_functions()  # type: ignore[attr-defined]
    return {str(n.pet_node_id): n.loopstate_position for n in tg.graph.nodes if isinstance(n, TGStartLoopNode)}


def test_positions_are_taken_from_the_mapping(
    build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path, caplog: Any
) -> None:
    """The profiler did not number the loop at line 13 (as for a loop it does not instrument): it gets
    no position, and the loops behind it keep the profiler's positions instead of shifting by one."""
    tg = _task_graph(build_pet_graph, make_node, build_task_graph, tmp_path)
    (tmp_path / "loopstate_positions.txt").write_text(
        f"{FUNCTION} 0 0 1:10 1:8\n" f"{FUNCTION} 1 2 1:12 1:20\n" f"{FUNCTION} 2 3 1:13 1:21\n"
    )

    with caplog.at_level(logging.WARNING, logger="Explorer"):
        positions = _assign(tg)

    assert positions == {"1:2": 0, "1:5": None, "1:7": 1, "1:8": 2}
    assert "Loop 1:5 of function " + FUNCTION + " is not listed" in caplog.text


def test_positions_are_matched_by_location_without_loop_node_id(
    build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path
) -> None:
    tg = _task_graph(build_pet_graph, make_node, build_task_graph, tmp_path)
    (tmp_path / "loopstate_positions.txt").write_text(
        f"{FUNCTION} 0 0 - 1:8\n"
        f"{FUNCTION} 1 1 - 1:13\n"
        f"{FUNCTION} 2 2 1:99 1:20\n"  # loop node id unknown to the PET
        # two loops starting at line 21 cannot be told apart by their location
        f"{FUNCTION} 3 3 - 1:21\n"
        f"{FUNCTION} 4 4 - 1:21\n"
    )

    assert _assign(tg) == {"1:2": 0, "1:5": 1, "1:7": 2, "1:8": None}


def test_functions_missing_from_the_mapping_get_no_positions(
    build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path
) -> None:
    tg = _task_graph(build_pet_graph, make_node, build_task_graph, tmp_path)
    (tmp_path / "loopstate_positions.txt").write_text("_Z5otherv 0 0 1:10 1:8\n")

    assert _assign(tg) == {"1:2": None, "1:5": None, "1:7": None, "1:8": None}


def test_without_mapping_positions_follow_the_start_lines(
    build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path, caplog: Any
) -> None:
    """Old profiles: the loops are numbered by start line, and a function whose loop count differs
    from its number of loopstate digits is reported as untrustworthy."""
    tg = _task_graph(build_pet_graph, make_node, build_task_graph, tmp_path)
    (tmp_path / "stateID_to_callpath_mapping.txt").write_text(f"1 0 {FUNCTION}\n2 1 {FUNCTION}_loopstate033\n")

    with caplog.at_level(logging.WARNING, logger="Explorer"):
        positions = _assign(tg)

    assert positions == {"1:2": 0, "1:5": 1, "1:7": 2, "1:8": 3}
    assert "Loopstate positions of function " + FUNCTION + " are untrustworthy: 4 loops, but 3" in caplog.text


@pytest.mark.parametrize("digits", ["0333", None])  # type: ignore[misc]
def test_without_mapping_matching_digit_counts_are_not_reported(
    build_pet_graph: Any, make_node: Any, build_task_graph: Any, tmp_path: Path, caplog: Any, digits: Optional[str]
) -> None:
    tg = _task_graph(build_pet_graph, make_node, build_task_graph, tmp_path)
    if digits is not None:
        (tmp_path / "stateID_to_callpath_mapping.txt").write_text(f"2 1 {FUNCTION}_loopstate{digits}\n")

    with caplog.at_level(logging.WARNING, logger="Explorer"):
        _assign(tg)

    assert "untrustworthy" not in caplog.text
