# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import json
from typing import Any

import pytest

from discopop_explorer.classes.patterns.PatternDecisions import (
    ACCEPTED,
    DUPLICATE_OF_REJECTED_PATTERN,
    DUPLICATE_PATTERN,
    FORMAT_VERSION,
    LOOP_CARRIED_DEPENDENCY,
    NOT_REPORTED,
    PENDING,
    REJECTED,
    TOO_FEW_ITERATIONS,
    CodeRegion,
    DecisionReason,
    DependencyRecord,
    PatternDecisionLog,
    duplicate_pattern_reason,
    region_of_pet_node,
)
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

DETECTOR = "doall_reduction"
TYPES = ("doall", "reduction")


def _region(node_id: str, start: int, end: int, file_id: int = 1) -> CodeRegion:
    return CodeRegion(node_id=node_id, file_id=file_id, start_line=start, end_line=end, kind="loop")


def _dependency(variable: str = "x") -> DependencyRecord:
    return DependencyRecord(
        type="RAW", variable=variable, memory_region="3", source_line="1:7", sink_line="1:6", origin="dynamic"
    )


def _carried(variable: str = "x") -> DecisionReason:
    return DecisionReason(kind=LOOP_CARRIED_DEPENDENCY, message="m", dependency=_dependency(variable))


def _pattern(node_id: str, pattern_id: int, class_name: str = "DoAllInfo") -> Any:
    return type(class_name, (), {"node_id": node_id, "pattern_id": pattern_id})()


def test_copies_of_a_region_merge_into_one_decision_without_repeated_reasons() -> None:
    # the task graph holds a copy of a loop per dynamic execution context
    log = PatternDecisionLog()
    log.reject(DETECTOR, TYPES, _region("1:2", 5, 10), _carried())
    log.reject(DETECTOR, TYPES, _region("1:2", 5, 10), _carried())
    log.reject(DETECTOR, TYPES, _region("1:2", 5, 10), _carried("y"))
    assert len(log) == 1
    decision = log.get(DETECTOR, "1:2")
    assert decision is not None
    assert [r.dependency.variable for r in decision.reasons if r.dependency] == ["x", "y"]
    assert decision.outcome == PENDING


def test_finalize_sets_the_outcome_from_the_reported_patterns() -> None:
    log = PatternDecisionLog()
    log.consider(DETECTOR, TYPES, _region("1:2", 5, 10))
    log.reject(DETECTOR, TYPES, _region("1:3", 12, 14), _carried())
    log.consider(DETECTOR, TYPES, _region("1:4", 20, 22))
    # one copy of 1:5 was rejected, another one was suggested
    log.reject(DETECTOR, TYPES, _region("1:5", 30, 32), DecisionReason(kind=TOO_FEW_ITERATIONS, message="m"))
    log.finalize(DETECTOR, [_pattern("1:2", 7), _pattern("1:5", 9, "ReductionInfo")])

    outcomes = {d.region.node_id: d.outcome for d in log.decisions}
    assert outcomes == {"1:2": ACCEPTED, "1:3": REJECTED, "1:4": NOT_REPORTED, "1:5": ACCEPTED}
    accepted = log.get(DETECTOR, "1:5")
    assert accepted is not None
    assert accepted.patterns == [{"type": "reduction", "pattern_id": 9}]
    assert accepted.reasons == []


def test_finalize_keeps_a_duplicate_only_while_the_pattern_it_duplicates_is_reported() -> None:
    def _log() -> PatternDecisionLog:
        log = PatternDecisionLog()
        log.consider(DETECTOR, TYPES, _region("1:2", 5, 10))
        log.reject(DETECTOR, TYPES, _region("1:4", 5, 10), duplicate_pattern_reason(_pattern("1:2", 7)))
        # another candidate has a reason of its own besides the void reference
        log.reject(DETECTOR, TYPES, _region("1:6", 5, 10), duplicate_pattern_reason(_pattern("1:2", 7)))
        log.reject(DETECTOR, TYPES, _region("1:6", 5, 10), _carried())
        return log

    reported = _log()
    reported.finalize(DETECTOR, [_pattern("1:2", 7)])
    duplicate = reported.get(DETECTOR, "1:4")
    assert duplicate is not None and duplicate.outcome == REJECTED
    assert [(r.kind, r.details["pattern_id"]) for r in duplicate.reasons] == [(DUPLICATE_PATTERN, 7)]

    # pattern 7 was removed, and its own candidate has no reason: e.g. its type is not reported
    removed = _log()
    removed.finalize(DETECTOR, [])
    duplicate = removed.get(DETECTOR, "1:4")
    assert duplicate is not None and (duplicate.outcome, duplicate.reasons) == (NOT_REPORTED, [])
    other = removed.get(DETECTOR, "1:6")
    assert other is not None and other.outcome == REJECTED
    assert [r.kind for r in other.reasons] == [LOOP_CARRIED_DEPENDENCY]

    # pattern 7 was removed, since its own candidate was rejected
    rejected = _log()
    rejected.reject(DETECTOR, TYPES, _region("1:2", 5, 10), _carried("y"))
    rejected.finalize(DETECTOR, [])
    duplicate = rejected.get(DETECTOR, "1:4")
    assert duplicate is not None and duplicate.outcome == NOT_REPORTED
    assert [r.kind for r in duplicate.reasons] == [DUPLICATE_OF_REJECTED_PATTERN]
    assert duplicate.reasons[0].details["node_id"] == "1:2"
    assert duplicate.reasons[0].details["reasons"] == [LOOP_CARRIED_DEPENDENCY]


def test_finalize_keeps_a_duplicate_without_a_reference() -> None:
    # as recorded before the reference was kept
    log = PatternDecisionLog()
    log.reject(DETECTOR, TYPES, _region("1:4", 5, 10), DecisionReason(kind=DUPLICATE_PATTERN, message="m"))
    log.finalize(DETECTOR, [])
    decision = log.get(DETECTOR, "1:4")
    assert decision is not None and decision.outcome == REJECTED


def test_finalize_leaves_other_detectors_alone() -> None:
    log = PatternDecisionLog()
    log.consider("other", ["task"], _region("1:2", 5, 10))
    log.finalize(DETECTOR, [_pattern("1:2", 7)])
    decision = log.get("other", "1:2")
    assert decision is not None and decision.outcome == PENDING


def test_query_returns_overlapping_regions_innermost_first() -> None:
    log = PatternDecisionLog()
    log.consider(DETECTOR, TYPES, _region("1:2", 5, 30))  # outer
    log.consider(DETECTOR, TYPES, _region("1:3", 8, 12))  # inner
    log.consider(DETECTOR, TYPES, _region("1:4", 40, 45))  # elsewhere
    log.consider(DETECTOR, TYPES, _region("2:2", 5, 30, file_id=2))  # other file

    assert [d.region.node_id for d in log.query(1, 10)] == ["1:3", "1:2"]
    assert [d.region.node_id for d in log.query(1, 20)] == ["1:2"]
    assert [d.region.node_id for d in log.query(1, 25, 42)] == ["1:4", "1:2"]
    assert log.query(1, 100) == []


def test_round_trip_through_a_file(tmp_path: Any) -> None:
    log = PatternDecisionLog()
    log.reject(DETECTOR, TYPES, _region("1:3", 12, 14), _carried())
    log.reject(DETECTOR, TYPES, _region("1:3", 12, 14), DecisionReason(kind="other", message="m", details={"n": 1}))
    log.consider(DETECTOR, TYPES, _region("1:2", 5, 10))
    log.finalize(DETECTOR, [_pattern("1:2", 7)])
    path = str(tmp_path / "explorer" / "pattern_decisions.json")
    log.save(path)

    with open(path) as f:
        assert json.load(f)["format_version"] == FORMAT_VERSION
    loaded = PatternDecisionLog.load(path)
    assert loaded.to_dict() == log.to_dict()
    # reasons stay deduplicated after loading
    loaded.reject(DETECTOR, TYPES, _region("1:3", 12, 14), _carried())
    reloaded = loaded.get(DETECTOR, "1:3")
    assert reloaded is not None and len(reloaded.reasons) == 2


def test_an_unknown_format_version_is_refused() -> None:
    with pytest.raises(ValueError):
        PatternDecisionLog.from_dict({"format_version": FORMAT_VERSION + 1, "decisions": []})


def test_an_entry_cu_is_widened_to_its_loop(make_node: Any, build_pet_graph: Any) -> None:
    # patterns are attached to a loop's entry CU, which only covers the loop header
    main = make_node("1:1", NodeType.FUNC, name="main")
    loop = make_node("1:2", NodeType.LOOP, name="loop", start_line=5, end_line=10)
    entry = make_node("1:3", NodeType.CU, name="entry", start_line=5, end_line=5)
    body = make_node("1:4", NodeType.CU, name="body", start_line=6, end_line=9)
    pet = build_pet_graph(
        [main, loop, entry, body],
        [(main.id, loop.id, EdgeType.CHILD), (loop.id, entry.id, EdgeType.CHILD), (loop.id, body.id, EdgeType.CHILD)],
    )
    assert region_of_pet_node(pet, entry.id) == CodeRegion("1:3", 1, 5, 10, "loop")
    assert region_of_pet_node(pet, loop.id) == CodeRegion("1:2", 1, 5, 10, "loop")
    # a CU which is not a loop's entry keeps its own lines
    assert region_of_pet_node(pet, body.id) == CodeRegion("1:4", 1, 6, 9, "cu")


def test_an_element_access_is_named_after_its_variable() -> None:
    # the profiler names an access through a computed address GEPRESULT_<variable>
    dep = Dependency(EdgeType.DATA)
    dep.dtype = DepType.RAW
    dep.var_name = "GEPRESULT_a"
    dep.origin = DepOrigin.DYNAMIC_ANALYSIS
    record = DependencyRecord.from_dependency(dep)
    assert (record.variable, record.element_access) == ("a", True)
    assert record.describe() == "RAW dependency on elements of 'a'"
    assert DependencyRecord.from_dict(record.to_dict()) == record
    assert "element_access" not in _dependency().to_dict()


def test_the_detectors_that_ran_are_kept_and_unknown_for_older_logs(tmp_path: Any) -> None:
    log = PatternDecisionLog()
    assert log.detectors == {}
    log.ran("doall_reduction", ["reduction", "doall"])
    path = str(tmp_path / "decisions.json")
    log.save(path)
    assert PatternDecisionLog.load(path).detectors == {"doall_reduction": ["doall", "reduction"]}

    older = log.to_dict()
    del older["detectors"]
    assert PatternDecisionLog.from_dict(older).detectors is None
