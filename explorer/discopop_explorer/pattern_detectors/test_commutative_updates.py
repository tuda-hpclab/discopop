# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The classification of blocking dependencies as commutative updates. See
design/doall_commutative_updates.md, "The criterion"."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.pattern_detectors import commutative_updates
from discopop_explorer.pattern_detectors.commutative_updates import (
    ACCESSED_ELSEWHERE,
    END_NOT_AT_UPDATE,
    MIXED_OPERATORS,
    UNRESOLVED_INSTRUCTION,
    Classification,
    CommutativeUpdateClassifier,
    SiteKey,
)
from discopop_explorer.utilities.ASTUtils.UpdateSites import NOT_A_STATEMENT, UpdateSite

CU_A = "1:3"  # a CU of the loop
CU_B = "1:4"  # another CU of the loop
CU_OUT = "1:5"  # a CU of main, outside of the loop
CU_CALLEE = "1:7"  # the CU of a called function
FUNC_CALLEE = "1:6"


def _site(
    line: int, first: int, last: Optional[int] = None, operator: str = "+=", operator_class: str = "+", **kw: Any
) -> UpdateSite:
    return UpdateSite(
        line=line,
        first_column=first,
        last_column=first if last is None else last,
        operator=operator,
        operator_class=operator_class,
        variable=kw.pop("variable", "h"),
        begin_column=kw.pop("begin_column", 5),
        end_column=kw.pop("end_column", 30),
        problem=kw.pop("problem", None),
    )


def _dependency(source: Optional[int], sink: Optional[int], dtype: Optional[DepType] = None) -> Dependency:
    dependency = Dependency(EdgeType.DATA)
    dependency.dtype = dtype
    dependency.source_instruction_id = source
    dependency.sink_instruction_id = sink
    return dependency


class _StubAST:
    """stands in for ASTPatternDetectionHelper"""

    def __init__(self, sites: Sequence[UpdateSite]) -> None:
        self.sites: Dict[Tuple[int, int], List[UpdateSite]] = {}
        for site in sites:
            self.sites.setdefault((1, site.line), []).append(site)

    def get_update_sites(self, file_id: int, line: int) -> List[UpdateSite]:
        return self.sites.get((file_id, line), [])


class _Scene:
    """main -> loop -> CU_A, CU_B (+ CU_OUT in main, and a callee called from CU_A)"""

    def __init__(self, make_node: Any, build_pet_graph: Any, sites: Sequence[UpdateSite]) -> None:
        self.main = make_node("1:1", NodeType.FUNC, name="main")
        self.loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=40)
        nodes: List[Node] = [
            self.main,
            self.loop,
            make_node(CU_A, NodeType.CU, name="a"),
            make_node(CU_B, NodeType.CU, name="b"),
            make_node(CU_OUT, NodeType.CU, name="out"),
            make_node(FUNC_CALLEE, NodeType.FUNC, name="callee"),
            make_node(CU_CALLEE, NodeType.CU, name="callee_cu"),
        ]
        self.edges: List[Tuple[str, str, Any]] = [
            ("1:1", "1:2", EdgeType.CHILD),
            ("1:1", CU_OUT, EdgeType.CHILD),
            ("1:2", CU_A, EdgeType.CHILD),
            ("1:2", CU_B, EdgeType.CHILD),
            (CU_A, FUNC_CALLEE, EdgeType.CALLSNODE),
            (FUNC_CALLEE, CU_CALLEE, EdgeType.CHILD),
        ]
        self._nodes = nodes
        self._build = build_pet_graph
        self.lines: Dict[str, str] = {}
        self.columns: Dict[str, int] = {}
        self.ast = _StubAST(sites)

    def instr(self, instruction: int, line: int, column: Optional[int]) -> int:
        self.lines[str(instruction)] = "1:" + str(line)
        if column is not None:
            self.columns[str(instruction)] = column
        return instruction

    def dep(
        self, sink_cu: str, sink: Optional[int], source_cu: str, source: Optional[int], dtype: DepType = DepType.RAW
    ) -> Dependency:
        """adds a DATA edge (sink first, as PEGraphX.from_parsed_input does) and returns its dependency"""
        dependency = _dependency(source, sink, dtype)
        self.edges.append((sink_cu, source_cu, dependency))
        return dependency

    def classifier(self) -> CommutativeUpdateClassifier:
        pet: PEGraphX = self._build(self._nodes, self.edges)
        pet.instruction_lines = self.lines
        pet.instruction_columns = self.columns
        return CommutativeUpdateClassifier(pet, DataEdgeIndex(pet), self.ast)  # type: ignore[arg-type]


@pytest.fixture  # type: ignore[misc]
def scene_factory(make_node: Any, build_pet_graph: Any) -> Any:
    def factory(*sites: UpdateSite) -> _Scene:
        return _Scene(make_node, build_pet_graph, sites)

    return factory


def test_scatter_add_to_itself_is_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    load, store = scene.instr(100, 10, 20), scene.instr(101, 10, 20)
    blocker = scene.dep(CU_A, load, CU_A, store)
    scene.dep(CU_A, store, CU_A, load, DepType.WAR)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.fixable
    assert result.sites == {SiteKey(1, 10, 20)}
    assert result.operator_class == "+"
    assert result.variable == "h"


def test_dependency_through_callee_is_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20), _site(30, 12, 14))
    caller = scene.instr(100, 10, 20)
    callee = scene.instr(200, 30, 13)
    blocker = scene.dep(CU_CALLEE, callee, CU_A, caller)
    scene.dep(CU_CALLEE, callee, CU_CALLEE, callee, DepType.WAW)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.fixable
    assert result.sites == {SiteKey(1, 10, 20), SiteKey(1, 30, 12)}


def test_read_in_callee_is_accessed_elsewhere(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update = scene.instr(100, 10, 20)
    read = scene.instr(200, 31, 8)
    blocker = scene.dep(CU_A, update, CU_A, update, DepType.WAW)
    scene.dep(CU_CALLEE, read, CU_A, update)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == ACCESSED_ELSEWHERE
    assert result.location == "1:31:8"


def test_two_statements_on_the_same_memory_are_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20), _site(12, 15, operator="++"))
    first, second = scene.instr(100, 10, 20), scene.instr(101, 12, 15)
    blocker = scene.dep(CU_B, second, CU_A, first)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.fixable
    assert result.sites == {SiteKey(1, 10, 20), SiteKey(1, 12, 15)}
    assert result.operator_class == "+"


def test_prefix_sum_end_outside_of_site_columns_is_not_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 24))
    operator, rhs_read = scene.instr(100, 10, 24), scene.instr(101, 10, 27)
    blocker = scene.dep(CU_A, rhs_read, CU_A, operator)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == END_NOT_AT_UPDATE
    assert result.location == "1:10:27"
    assert not result.fixable
    assert result.sites == frozenset()


def test_end_on_line_without_any_site_is_not_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update, plain = scene.instr(100, 10, 20), scene.instr(101, 11, 3)
    blocker = scene.dep(CU_A, update, CU_A, plain)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == END_NOT_AT_UPDATE
    assert result.location == "1:11:3"


def test_read_elsewhere_in_the_loop_is_accessed_elsewhere(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update, read = scene.instr(100, 10, 20), scene.instr(102, 11, 9)
    blocker = scene.dep(CU_A, update, CU_A, update, DepType.WAW)
    scene.dep(CU_B, read, CU_A, update)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == ACCESSED_ELSEWHERE
    assert result.location == "1:11:9"


def test_read_in_a_cu_outside_of_the_loop_is_ignored(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update, read = scene.instr(100, 10, 20), scene.instr(102, 11, 9)
    blocker = scene.dep(CU_A, update, CU_A, update, DepType.WAW)
    scene.dep(CU_OUT, read, CU_A, update)  # sink outside
    scene.dep(CU_A, update, CU_OUT, read, DepType.WAR)  # source outside
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.fixable
    assert result.sites == {SiteKey(1, 10, 20)}


def test_mixed_operator_classes_are_not_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20), _site(12, 18, operator="*=", operator_class="*"))
    plus, times = scene.instr(100, 10, 20), scene.instr(101, 12, 18)
    blocker = scene.dep(CU_B, times, CU_A, plus)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == MIXED_OPERATORS
    assert result.location == "1:10:20"


def test_operator_mixed_in_only_through_the_closure_is_not_fixable(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20), _site(12, 18, operator="*=", operator_class="*"))
    plus, times = scene.instr(100, 10, 20), scene.instr(101, 12, 18)
    blocker = scene.dep(CU_A, plus, CU_A, plus, DepType.WAW)
    scene.dep(CU_B, times, CU_A, plus)
    assert scene.classifier().classify(scene.loop, blocker).problem == MIXED_OPERATORS


def test_site_with_a_problem_reports_that_problem(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20, problem=NOT_A_STATEMENT))
    update = scene.instr(100, 10, 20)
    blocker = scene.dep(CU_A, update, CU_A, update)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == NOT_A_STATEMENT
    assert result.location == "1:10:20"


def test_site_with_a_problem_found_through_the_closure_is_reported(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20), _site(12, 15, problem=NOT_A_STATEMENT))
    good, bad = scene.instr(100, 10, 20), scene.instr(101, 12, 15)
    blocker = scene.dep(CU_A, good, CU_A, good, DepType.WAW)
    scene.dep(CU_B, bad, CU_A, good)
    result = scene.classifier().classify(scene.loop, blocker)
    assert result.problem == NOT_A_STATEMENT
    assert result.location == "1:12:15"


def test_end_without_instruction_id_is_unresolved(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update = scene.instr(100, 10, 20)
    classifier = scene.classifier()
    for source, sink in ((None, update), (update, None)):
        result = classifier.classify(scene.loop, _dependency(source, sink))
        assert result.problem == UNRESOLVED_INSTRUCTION
        assert result.location is None


def test_end_without_column_or_line_is_unresolved(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update, no_column = scene.instr(100, 10, 20), scene.instr(101, 10, None)
    blocker = scene.dep(CU_A, no_column, CU_A, update)
    assert scene.classifier().classify(scene.loop, blocker).problem == UNRESOLVED_INSTRUCTION
    unknown = _dependency(update, 999)
    assert scene.classifier().classify(scene.loop, unknown).problem == UNRESOLVED_INSTRUCTION


def test_to_details_of_a_fixable_classification() -> None:
    result = Classification(sites=frozenset({SiteKey(1, 12, 15), SiteKey(1, 10, 20)}), operator_class="+", variable="h")
    assert result.to_details() == {"atomic_update": {"fixable": True, "operation": "+", "sites": ["1:10", "1:12"]}}


def test_to_details_of_a_not_fixable_classification(scene_factory: Any) -> None:
    scene = scene_factory(_site(10, 24))
    operator, rhs_read = scene.instr(100, 10, 24), scene.instr(101, 10, 27)
    blocker = scene.dep(CU_A, rhs_read, CU_A, operator)
    details = scene.classifier().classify(scene.loop, blocker).to_details()
    assert details == {"atomic_update": {"fixable": False, "problem": END_NOT_AT_UPDATE, "location": "1:10:27"}}
    # without a location, the key is left out
    assert Classification(frozenset(), None, problem=UNRESOLVED_INSTRUCTION).to_details() == {
        "atomic_update": {"fixable": False, "problem": UNRESOLVED_INSTRUCTION}
    }


def test_edges_of_a_loop_are_collected_once(scene_factory: Any, monkeypatch: Any) -> None:
    scene = scene_factory(_site(10, 20))
    update = scene.instr(100, 10, 20)
    blocker = scene.dep(CU_A, update, CU_A, update, DepType.WAW)
    calls: List[Any] = []
    original = subtree_of_type

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(commutative_updates, "subtree_of_type", counting)  # type: ignore[attr-defined]
    classifier = scene.classifier()
    first = classifier.classify(scene.loop, blocker)
    second = classifier.classify(scene.loop, blocker)
    assert first == second and first.fixable
    assert len(calls) == 1
    assert len(classifier._incident) == 1
