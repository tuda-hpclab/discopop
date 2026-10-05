# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Why a code region did or did not become a parallelization suggestion.

A detector records every code region it considers as a candidate, and for each rejected
candidate the reasons it was rejected for, e.g. the dependency which prevents a doall loop.
After the detection, the log is finalized against the patterns which made it into the result,
so that each candidate carries one of the outcomes below. The log is written to
explorer/pattern_decisions.json and read back by tools which explain the detection result.

The format is not tied to a detector or a kind of code region: a detector names itself and the
pattern types it can produce, a region names its kind, and a reason has a kind, a message and
free-form details next to the optional dependency it refers to.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.Dependency import Dependency
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
    from discopop_explorer.classes.patterns.PatternBase import PatternBase

FORMAT_VERSION = 1

# outcomes of a candidate
ACCEPTED = "accepted"  # part of the detection result
REJECTED = "rejected"  # see its reasons
NOT_REPORTED = "not_reported"  # passed the checks, but is not part of the result, e.g. pattern type not enabled
PENDING = "pending"  # not finalized yet
OUTCOMES = (ACCEPTED, REJECTED, NOT_REPORTED, PENDING)

# reason kinds recorded by the doall / reduction detector
TOO_FEW_ITERATIONS = "too_few_iterations"
LOOP_CARRIED_DEPENDENCY = "loop_carried_dependency"
UNPRIVATIZABLE_STATIC_DEPENDENCY = "unprivatizable_static_dependency"
DUPLICATE_PATTERN = "duplicate_pattern"  # an equivalent pattern was reported for other code already
# an equivalent pattern registered for other code took this one's place, but was rejected itself, so
# neither is reported. Only with outcome not_reported, see PatternDecisionLog.finalize.
DUPLICATE_OF_REJECTED_PATTERN = "duplicate_of_rejected_pattern"
NO_PATTERN_NODE = "no_pattern_node"  # the checks passed, but there is no node to attach the pattern to
# the loop can be left early (break, return, exit()); the analysis cut these exits
CUT_EARLY_EXIT = "early_exit"
# the loop contains an exception handler, which the analysis cut together with its dependencies
CUT_EXCEPTION_HANDLER = "exception_handler"

# the profiler's name for an access through a computed address, e.g. an array element or a field
GEP_RESULT_PREFIX = "GEPRESULT_"

_ORIGIN_NAMES = {DepOrigin.DYNAMIC_ANALYSIS: "dynamic", DepOrigin.STATIC_ANALYSIS: "static"}


@dataclass(frozen=True)
class DependencyRecord:
    """The parts of a Dependency which explain a decision. Lines are file_id:line."""

    type: Optional[str]  # RAW, WAR, WAW, INIT
    variable: Optional[str]
    memory_region: Optional[str]
    source_line: Optional[str]
    sink_line: Optional[str]
    origin: Optional[str]  # dynamic, static
    # the access goes to an element of the variable (e.g. a[i]) rather than to the variable itself
    element_access: bool = False

    @classmethod
    def from_dependency(cls, dep: Dependency) -> DependencyRecord:
        variable = dep.var_name
        element_access = variable is not None and variable.startswith(GEP_RESULT_PREFIX)
        if variable is not None and element_access:
            # as in the PET, see parser.py
            variable = variable[len(GEP_RESULT_PREFIX) :]
        return cls(
            type=dep.dtype.name if dep.dtype is not None else None,
            variable=variable,
            memory_region=str(dep.memory_region) if dep.memory_region is not None else None,
            source_line=str(dep.source_line) if dep.source_line is not None else None,
            sink_line=str(dep.sink_line) if dep.sink_line is not None else None,
            origin=_ORIGIN_NAMES.get(dep.origin) if dep.origin is not None else None,
            element_access=element_access,
        )

    def describe(self) -> str:
        """e.g. "RAW dependency on elements of 'a'" """
        target = ("elements of '" if self.element_access else "'") + str(self.variable) + "'"
        return (self.type or "data") + " dependency on " + target

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type,
            "variable": self.variable,
            "memory_region": self.memory_region,
            "source_line": self.source_line,
            "sink_line": self.sink_line,
            "origin": self.origin,
        }
        if self.element_access:
            data["element_access"] = True
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DependencyRecord:
        return cls(
            type=data.get("type"),
            variable=data.get("variable"),
            memory_region=data.get("memory_region"),
            source_line=data.get("source_line"),
            sink_line=data.get("sink_line"),
            origin=data.get("origin"),
            element_access=bool(data.get("element_access", False)),
        )


@dataclass
class DecisionReason:
    kind: str
    message: str
    dependency: Optional[DependencyRecord] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> Tuple[Any, ...]:
        """identifies a reason for deduplication: the same loop exists in several copies of the
        task graph, which reject it for the same reason."""
        return (self.kind, self.dependency, json.dumps(self.details, sort_keys=True))

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.dependency is not None:
            data["dependency"] = self.dependency.to_dict()
        if self.details:
            data["details"] = self.details
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DecisionReason:
        dependency = data.get("dependency")
        return cls(
            kind=data["kind"],
            message=data.get("message", ""),
            dependency=DependencyRecord.from_dict(dependency) if dependency is not None else None,
            details=dict(data.get("details", {})),
        )


@dataclass(frozen=True)
class CodeRegion:
    """A region of source code a candidate covers. node_id is the PET node the detector keys the
    candidate by, and the one the resulting patterns carry as their node_id."""

    node_id: str
    file_id: int
    start_line: int
    end_line: int
    kind: str  # e.g. loop, function

    def overlaps(self, file_id: int, start_line: int, end_line: int) -> bool:
        return self.file_id == file_id and self.start_line <= end_line and start_line <= self.end_line

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "file_id": self.file_id,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CodeRegion:
        return cls(
            node_id=str(data["node_id"]),
            file_id=int(data["file_id"]),
            start_line=int(data["start_line"]),
            end_line=int(data["end_line"]),
            kind=str(data.get("kind", "")),
        )


@dataclass
class CandidateDecision:
    detector: str
    pattern_types: List[str]  # the pattern types the detector could have suggested for the region
    region: CodeRegion
    outcome: str = PENDING
    patterns: List[Dict[str, Any]] = field(default_factory=list)  # {"type": ..., "pattern_id": ...}
    reasons: List[DecisionReason] = field(default_factory=list)
    _reason_keys: set[Tuple[Any, ...]] = field(default_factory=set, repr=False, compare=False)

    def add_reason(self, reason: DecisionReason) -> None:
        key = reason.key()
        if key in self._reason_keys:
            return
        self._reason_keys.add(key)
        self.reasons.append(reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector": self.detector,
            "pattern_types": list(self.pattern_types),
            "region": self.region.to_dict(),
            "outcome": self.outcome,
            "patterns": list(self.patterns),
            "reasons": [r.to_dict() for r in self.reasons],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CandidateDecision:
        decision = cls(
            detector=data["detector"],
            pattern_types=list(data.get("pattern_types", [])),
            region=CodeRegion.from_dict(data["region"]),
            outcome=data.get("outcome", PENDING),
            patterns=list(data.get("patterns", [])),
        )
        for reason in data.get("reasons", []):
            decision.add_reason(DecisionReason.from_dict(reason))
        return decision


def pattern_type_name(pattern: PatternBase) -> str:
    """doall for DoAllInfo, reduction for ReductionInfo, ..."""
    name = type(pattern).__name__
    if name.endswith("Info"):
        name = name[: -len("Info")]
    return name.lower()


def duplicate_pattern_reason(pattern: PatternBase) -> DecisionReason:
    """the reason for dropping a candidate's pattern as a duplicate of `pattern`, which was
    registered in its place. Provisional until the log is finalized: `pattern` can still be
    removed from the result afterwards, see PatternDecisionLog.finalize."""
    return DecisionReason(
        kind=DUPLICATE_PATTERN,
        message="An equivalent suggestion (pattern "
        + str(pattern.pattern_id)
        + ") was reported for other code, so this one was dropped as its duplicate.",
        details={
            "pattern_id": pattern.pattern_id,
            "pattern_type": pattern_type_name(pattern),
            "node_id": str(pattern.node_id),
        },
    )


def _duplicated_pattern_id(reason: DecisionReason) -> Optional[Any]:
    """the id of the pattern a duplicate_pattern reason refers to; None for any other reason, and
    for a duplicate_pattern reason which names none (recorded before the reference was kept)"""
    if reason.kind != DUPLICATE_PATTERN:
        return None
    return reason.details.get("pattern_id")


def region_of_pet_node(pet: PEGraphX, node_id: NodeID) -> CodeRegion:
    """The region of a PET node. Patterns are attached to a loop's entry CU, which only spans the
    first lines of the loop, so a CU node is widened to the loop it is the entry of."""
    node = pet.node_at(node_id)
    region_node = node
    if not isinstance(node, LoopNode):
        for parent_id, _, _ in in_edges(pet, node_id, EdgeType.CHILD):
            parent = pet.node_at(parent_id)
            if isinstance(parent, LoopNode) and parent.file_id == node.file_id and parent.start_line == node.start_line:
                region_node = parent
                break
    kind = "loop" if isinstance(region_node, LoopNode) else type(region_node).__name__.replace("Node", "").lower()
    return CodeRegion(
        node_id=str(node_id),
        file_id=int(region_node.file_id),
        start_line=int(region_node.start_line),
        end_line=int(region_node.end_line),
        kind=kind,
    )


class PatternDecisionLog:
    """All candidates considered during a pattern detection, keyed by detector and node id."""

    def __init__(self) -> None:
        self._decisions: Dict[Tuple[str, str], CandidateDecision] = dict()
        # detector -> the pattern types it reported. None for a log written before this was
        # recorded, where it is unknown.
        self._detectors: Optional[Dict[str, List[str]]] = dict()

    def __len__(self) -> int:
        return len(self._decisions)

    @property
    def decisions(self) -> List[CandidateDecision]:
        return sorted(
            self._decisions.values(),
            key=lambda d: (d.region.file_id, d.region.start_line, -d.region.end_line, d.region.node_id, d.detector),
        )

    @property
    def detectors(self) -> Optional[Dict[str, List[str]]]:
        """the detectors that ran and recorded their decisions, with the pattern types each one
        reported; None if unknown. A region no detector considered was not analysed at all."""
        return None if self._detectors is None else dict(self._detectors)

    def ran(self, detector: str, reported_pattern_types: Iterable[str]) -> None:
        """notes that `detector` ran, whether or not it considered any candidate"""
        if self._detectors is None:
            self._detectors = dict()
        self._detectors[detector] = sorted(reported_pattern_types)

    def get(self, detector: str, node_id: str) -> Optional[CandidateDecision]:
        return self._decisions.get((detector, str(node_id)))

    def consider(self, detector: str, pattern_types: Iterable[str], region: CodeRegion) -> CandidateDecision:
        """registers a candidate, or returns the one already registered for its region"""
        key = (detector, region.node_id)
        decision = self._decisions.get(key)
        if decision is None:
            decision = CandidateDecision(detector=detector, pattern_types=list(pattern_types), region=region)
            self._decisions[key] = decision
        return decision

    def reject(
        self, detector: str, pattern_types: Iterable[str], region: CodeRegion, reason: DecisionReason
    ) -> CandidateDecision:
        decision = self.consider(detector, pattern_types, region)
        decision.add_reason(reason)
        return decision

    def finalize(self, detector: str, patterns: Iterable[PatternBase]) -> None:
        """sets the outcome of every candidate of `detector` from the patterns which are part of
        the final detection result.

        A candidate dropped as the duplicate of another pattern is only rejected as such if that
        pattern is part of the result. The duplicate check runs inside the detector, before
        patterns are removed again, e.g. because another copy of their loop turned out to be
        prevented, or because their pattern type is not reported. If the pattern it refers to was
        removed, the reference is void: the candidate's outcome then follows from its remaining
        reasons or, without any, it is not reported, like the pattern which took its place. If
        that pattern was rejected, the candidate says so (DUPLICATE_OF_REJECTED_PATTERN), since it
        passed its checks but is left without a suggestion of its own."""
        by_node: Dict[str, List[Dict[str, Any]]] = dict()
        for pattern in patterns:
            by_node.setdefault(str(pattern.node_id), []).append(
                {"type": pattern_type_name(pattern), "pattern_id": pattern.pattern_id}
            )
        reported_ids = {p["pattern_id"] for found in by_node.values() for p in found}
        # the not reported candidates whose duplicate_pattern reasons were void, with those reasons
        void_duplicates: List[Tuple[CandidateDecision, List[DecisionReason]]] = []
        for (decision_detector, node_id), decision in self._decisions.items():
            if decision_detector != detector:
                continue
            found = by_node.get(node_id)
            if found:
                decision.outcome = ACCEPTED
                decision.patterns = sorted(found, key=lambda p: (p["pattern_id"], p["type"]))
                # some copy of the region was rejected, another one was not: the region is
                # parallelizable as reported, so those reasons do not apply to it
                decision.reasons = []
                decision._reason_keys = set()
                continue
            decision.patterns = []
            void = [r for r in decision.reasons if _duplicated_pattern_id(r) not in reported_ids | {None}]
            if void:
                decision.reasons = [r for r in decision.reasons if all(r is not v for v in void)]
                decision._reason_keys = {r.key() for r in decision.reasons}
            if decision.reasons:
                decision.outcome = REJECTED
            else:
                decision.outcome = NOT_REPORTED
                if void:
                    void_duplicates.append((decision, void))
        # only now, since the outcome of the candidate the removed pattern was built for is final
        for decision, void in void_duplicates:
            for reason in void:
                other = self._decisions.get((detector, str(reason.details.get("node_id"))))
                if other is None or other.outcome != REJECTED:
                    # e.g. its pattern type is not reported, which applies to this candidate as well
                    continue
                decision.add_reason(
                    DecisionReason(
                        kind=DUPLICATE_OF_REJECTED_PATTERN,
                        message="This code passed the checks, but an equivalent suggestion for other code "
                        "was registered in place of its own and rejected afterwards, so neither is "
                        "reported. The region of the other code carries the reasons it was rejected for.",
                        details={
                            "pattern_type": reason.details.get("pattern_type"),
                            "node_id": other.region.node_id,
                            "file_id": other.region.file_id,
                            "start_line": other.region.start_line,
                            "end_line": other.region.end_line,
                            "reasons": sorted({r.kind for r in other.reasons}),
                        },
                    )
                )

    def query(self, file_id: int, start_line: int, end_line: Optional[int] = None) -> List[CandidateDecision]:
        """the candidates whose region overlaps the given lines, innermost (shortest) first"""
        end = start_line if end_line is None else end_line
        matches = [d for d in self._decisions.values() if d.region.overlaps(file_id, start_line, end)]
        return sorted(
            matches,
            key=lambda d: (d.region.end_line - d.region.start_line, -d.region.start_line, d.region.node_id, d.detector),
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"format_version": FORMAT_VERSION}
        if self._detectors is not None:
            data["detectors"] = {name: list(types) for name, types in sorted(self._detectors.items())}
        data["decisions"] = [d.to_dict() for d in self.decisions]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PatternDecisionLog:
        version = data.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"Unsupported pattern decisions format version: {version} (expected {FORMAT_VERSION})")
        log = cls()
        # absent in logs written before it was recorded
        detectors = data.get("detectors")
        log._detectors = None if detectors is None else {str(k): list(v) for k, v in detectors.items()}
        for entry in data.get("decisions", []):
            decision = CandidateDecision.from_dict(entry)
            log._decisions[(decision.detector, decision.region.node_id)] = decision
        return log

    def save(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path: str) -> PatternDecisionLog:
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))
