# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Loops rejected only because of a few dependencies between their iterations become unsure suggestions, see
design/agent_checked_suggestions.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import pytest

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.PatternDecisions import PatternDecisionLog
from discopop_explorer.classes.patterns.UnsureSuggestions import NOTE, UnsureSuggestions
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.new_do_all_detector import (
    DECISION_DETECTOR,
    identify_simple_doall_and_reduction,
)
from discopop_explorer.pattern_detectors.test_new_do_all_detector import _build_two_iteration_loop
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]


def _dependency(var_name: str, line: str, origin: DepOrigin = DepOrigin.DYNAMIC_ANALYSIS) -> Dependency:
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = var_name
    dep.source_line = LineID(line)
    dep.sink_line = LineID(line)
    dep.origin = origin
    return dep


def _loop(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    dependencies: List[Dependency],
) -> Tuple[TaskGraph, Node]:
    tg, loop, _loop_ctx, work1, work2 = _build_two_iteration_loop(
        make_node, build_pet_graph, build_task_graph, make_tg_node
    )
    for dep in dependencies:
        work1.register_outgoing_dependency(work2, dep)
    return tg, loop


def _detect(tg: TaskGraph, unsure: Optional[UnsureSuggestions]) -> List[Any]:
    patterns = identify_simple_doall_and_reduction(
        tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet), None, False, unsure
    )
    if unsure is not None:
        unsure.build()
    return patterns


@pytest.fixture
def graph(make_node: MakeNode, build_pet_graph: BuildPetGraph, build_task_graph: Any, make_tg_node: Any) -> Any:
    def build(dependencies: List[Dependency]) -> Tuple[TaskGraph, Node]:
        return _loop(make_node, build_pet_graph, build_task_graph, make_tg_node, dependencies)

    return build


def test_a_loop_with_few_dynamic_blockers_is_an_unsure_suggestion(graph: Any, isolated_pattern_id_cwd: Any) -> None:
    tg, loop = graph([_dependency("x", "1:7"), _dependency("y", "1:8")])
    unsure = UnsureSuggestions(max_blockers=4)
    assert _detect(tg, unsure) == []
    assert len(unsure.suggestions) == 1
    pattern, unsure_loop = unsure.suggestions[0]
    assert isinstance(pattern, DoAllInfo)
    assert pattern.node_id == loop.id
    assert unsure_loop.pet_node_id == loop.id
    assert [(b.type, b.accesses[0].variable, b.source_line, b.origin) for b in unsure_loop.blockers] == [
        ("RAW", "x", "1:7", "dynamic"),
        ("RAW", "y", "1:8", "dynamic"),
    ]


def test_a_loop_with_more_blockers_than_allowed_is_not_an_unsure_suggestion(
    graph: Any, isolated_pattern_id_cwd: Any
) -> None:
    tg, _loop_node = graph([_dependency("x", "1:7"), _dependency("y", "1:8")])
    unsure = UnsureSuggestions(max_blockers=1)
    _detect(tg, unsure)
    assert unsure.suggestions == []


def test_repetitions_of_a_blocker_count_once(graph: Any, isolated_pattern_id_cwd: Any) -> None:
    tg, _loop_node = graph([_dependency("x", "1:7"), _dependency("x", "1:7")])
    unsure = UnsureSuggestions(max_blockers=1)
    _detect(tg, unsure)
    assert len(unsure.suggestions) == 1
    assert len(unsure.suggestions[0][1].blockers) == 1


def test_dependencies_between_the_same_statements_are_one_blocker(graph: Any, isolated_pattern_id_cwd: Any) -> None:
    # e.g. a push_back changing the size, the data pointer and the elements of a vector
    tg, _loop_node = graph([_dependency("size", "1:7"), _dependency("data", "1:7"), _dependency("y", "1:8")])
    unsure = UnsureSuggestions(max_blockers=2)
    _detect(tg, unsure)
    [(_pattern, unsure_loop)] = unsure.suggestions
    assert [(b.source_line, [a.variable for a in b.accesses]) for b in unsure_loop.blockers] == [
        ("1:7", ["data", "size"]),
        ("1:8", ["y"]),
    ]


def test_an_unprivatizable_static_dependency_is_a_blocker(graph: Any, isolated_pattern_id_cwd: Any) -> None:
    tg, _loop_node = graph([_dependency("x", "1:7", DepOrigin.STATIC_ANALYSIS)])
    unsure = UnsureSuggestions()
    assert _detect(tg, unsure) == []
    assert [(b.accesses[0].variable, b.origin) for b in unsure.suggestions[0][1].blockers] == [("x", "static")]


def test_a_parallelizable_loop_is_no_unsure_suggestion(graph: Any, isolated_pattern_id_cwd: Any) -> None:
    tg, loop = graph([])
    unsure = UnsureSuggestions()
    patterns = _detect(tg, unsure)
    assert [p.node_id for p in patterns] == [loop.id]
    assert unsure.suggestions == []


@pytest.mark.parametrize("dependencies", [[], [("x", "1:7")], [("x", "1:7"), ("y", "1:8")]])
def test_the_suggestions_and_their_ids_do_not_depend_on_unsure_suggestions(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
    dependencies: List[Tuple[str, str]],
) -> None:
    def detect(unsure: Optional[UnsureSuggestions]) -> List[Tuple[Any, ...]]:
        (Path(isolated_pattern_id_cwd) / "next_free_pattern_id.txt").write_text("0")
        tg, _loop_node = _loop(
            make_node, build_pet_graph, build_task_graph, make_tg_node, [_dependency(*d) for d in dependencies]
        )
        return [(p.pattern_id, p.node_id, type(p).__name__) for p in _detect(tg, unsure)]

    assert detect(UnsureSuggestions()) == detect(None)


def test_unsure_suggestions_are_written_with_their_blockers(
    graph: Any, isolated_pattern_id_cwd: Any, tmp_path: Path
) -> None:
    tg, loop = graph([_dependency("x", "1:7")])
    unsure = UnsureSuggestions(max_blockers=3)
    _detect(tg, unsure)
    path = tmp_path / "explorer" / "unsure_suggestions.json"
    unsure.save(str(path))
    data = json.loads(path.read_text())
    assert data["format_version"] == 1
    assert data["note"] == NOTE
    assert data["max_blockers"] == 3
    [entry] = data["suggestions"]
    assert entry["type"] == "do_all"
    assert entry["node_id"] == loop.id
    assert entry["pragma"] == "#pragma omp parallel for"
    assert entry["blockers"] == [
        {
            "type": "RAW",
            "source_line": "1:7",
            "sink_line": "1:7",
            "origin": "dynamic",
            "accesses": [{"variable": "x", "memory_region": None}],
        }
    ]
    assert not any(key.startswith("_") for key in entry)


@pytest.mark.parametrize("all_blocking_dependencies", [False, True])
def test_the_decisions_do_not_depend_on_unsure_suggestions(
    make_node: MakeNode,
    build_pet_graph: BuildPetGraph,
    build_task_graph: Any,
    make_tg_node: Any,
    isolated_pattern_id_cwd: Any,
    all_blocking_dependencies: bool,
) -> None:
    def reasons(unsure: Optional[UnsureSuggestions]) -> List[Any]:
        tg, loop = _loop(
            make_node,
            build_pet_graph,
            build_task_graph,
            make_tg_node,
            [_dependency("x", "1:7"), _dependency("y", "1:8")],
        )
        decisions = PatternDecisionLog()
        identify_simple_doall_and_reduction(
            tg, ASTPatternDetectionHelper(), DataEdgeIndex(tg.pet), decisions, all_blocking_dependencies, unsure
        )
        decision = decisions.get(DECISION_DETECTOR, loop.id)
        assert decision is not None
        return sorted(str(r.dependency) for r in decision.reasons)

    without = reasons(None)
    assert len(without) == (2 if all_blocking_dependencies else 1)
    assert reasons(UnsureSuggestions()) == without


def test_max_blockers_must_be_positive() -> None:
    with pytest.raises(ValueError):
        UnsureSuggestions(max_blockers=0)
