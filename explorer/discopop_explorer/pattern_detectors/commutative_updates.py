# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Whether the dependencies which prevent a doall loop are commutative updates of shared memory
(``row_coefs[k] += v``, ``h[idx[i]]++``), which ``#pragma omp atomic`` makes safe to run in parallel.
See design/doall_commutative_updates.md, "The criterion".

A blocking dependency is fixable if both of its ends are update statements (UpdateSites), and so is
every other end of every dependency the loop has on those statements - not only the carried ones: a
read of the same memory anywhere else in the loop observes an intermediate value, which makes the
order of the updates matter. The statements are identified by the column of their operator, at which
the profiler reports their read-modify-write, so no variable name is involved: the profiler names a
dependency after its sink only, and the same memory goes by different names in different functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_explorer.utilities.ASTUtils.UpdateSites import UpdateSite

# why a blocking dependency is not fixable, besides the problems of an UpdateSite
UNRESOLVED_INSTRUCTION = "unresolved_instruction"  # an end has no instruction id or no position
END_NOT_AT_UPDATE = "end_not_at_update"  # an end is no update statement, e.g. the read in a[i+1] += a[i]
ACCESSED_ELSEWHERE = "accessed_elsewhere"  # the memory is accessed outside of the updates in the loop
MIXED_OPERATORS = "mixed_operators"  # e.g. += and *= on the same memory, which do not commute

DETAILS_KEY = "atomic_update"

# a position of an instruction: file id, line, column
Position = Tuple[int, int, int]


@dataclass(frozen=True)
class SiteKey:
    """An update statement, identified by its position."""

    file_id: int
    line: int
    first_column: int

    def __str__(self) -> str:
        return str(self.file_id) + ":" + str(self.line)


@dataclass(frozen=True)
class Classification:
    """Whether a blocking dependency is fixable by making update statements atomic."""

    # the update statements which have to be atomic, empty if not fixable
    sites: FrozenSet[SiteKey]
    # the class of their operator ("+", "*", "&", "|", "^"), None if not fixable
    operator_class: Optional[str]
    # why not, None if fixable (see the constants above and the problems of UpdateSite)
    problem: Optional[str] = None
    # where (file id:line:column) the problem was found
    location: Optional[str] = None
    # the variable the updated memory is reached through, at the first site found
    variable: Optional[str] = None

    @property
    def fixable(self) -> bool:
        return self.problem is None

    def to_details(self) -> Dict[str, object]:
        """the decision log's details of the reason the dependency was recorded as"""
        if self.fixable:
            return {
                DETAILS_KEY: {
                    "fixable": True,
                    "operation": self.operator_class,
                    "sites": sorted(str(site) for site in self.sites),
                }
            }
        details: Dict[str, object] = {"fixable": False, "problem": self.problem}
        if self.location is not None:
            details["location"] = self.location
        return {DETAILS_KEY: details}


def _not_fixable(problem: str, position: Optional[Position] = None) -> Classification:
    location = None if position is None else ":".join(str(part) for part in position)
    return Classification(sites=frozenset(), operator_class=None, problem=problem, location=location)


class CommutativeUpdateClassifier:
    """Classifies the blocking dependencies of loops. Built once per detector run: the dependencies a
    loop has between its own instructions (the loop and the functions it calls) are collected once per
    loop and shared by its blockers - and by the copies of the loop in the task graph."""

    def __init__(self, pet: PEGraphX, data_edges: DataEdgeIndex, ast_helper: ASTPatternDetectionHelper) -> None:
        self._pet = pet
        self._data_edges = data_edges
        self._ast = ast_helper
        # per loop: the other ends of each instruction's dependencies inside the loop, and the
        # instructions of the loop by line, to find every instruction of a site
        self._incident: Dict[NodeID, Dict[int, Set[int]]] = {}
        self._by_line: Dict[NodeID, Dict[Tuple[int, int], List[Tuple[int, int]]]] = {}

    def classify(self, loop: Node, dependency: Dependency) -> Classification:
        """whether a dependency between iterations of the loop (its LoopNode) is fixable by atomic updates"""
        ends = (dependency.source_instruction_id, dependency.sink_instruction_id)
        seeds: List[Tuple[int, SiteKey, UpdateSite]] = []
        for instruction in ends:
            if instruction is None:
                return _not_fixable(UNRESOLVED_INSTRUCTION)
            resolved = self._site_of(instruction)
            if isinstance(resolved, Classification):
                return resolved
            seeds.append((instruction, resolved[0], resolved[1]))
        # the closure over the dependencies of the loop: every instruction touching the memory of a site
        # has to belong to a site
        incident = self._incident_in_loop(loop)
        by_line = self._by_line[loop.id]
        sites: Dict[SiteKey, UpdateSite] = {}
        pending: List[int] = []
        visited: Set[int] = set()

        def add_site(key: SiteKey, site: UpdateSite, instruction: int) -> None:
            pending.append(instruction)
            if key in sites:
                return
            sites[key] = site
            for column, other in by_line.get((key.file_id, key.line), []):
                if site.covers(column):
                    pending.append(other)

        for instruction, key, site in seeds:
            add_site(key, site, instruction)
        while pending:
            instruction = pending.pop()
            if instruction in visited:
                continue
            visited.add(instruction)
            for other in incident.get(instruction, ()):
                if other in visited:
                    continue
                resolved = self._site_of(other)
                if isinstance(resolved, Classification):
                    if resolved.problem == END_NOT_AT_UPDATE:
                        return _not_fixable(ACCESSED_ELSEWHERE, self._position(other))
                    return resolved
                add_site(resolved[0], resolved[1], other)
        operator_classes = {site.operator_class for site in sites.values()}
        if len(operator_classes) != 1:
            return _not_fixable(MIXED_OPERATORS, self._position(ends[0]))  # type: ignore[arg-type]
        first = min(sites, key=lambda key: (key.file_id, key.line, key.first_column))
        return Classification(
            sites=frozenset(sites),
            operator_class=next(iter(operator_classes)),
            variable=sites[first].variable,
        )

    def _position(self, instruction: int) -> Optional[Position]:
        line_id = self._pet.instruction_lines.get(str(instruction))
        column = self._pet.instruction_columns.get(str(instruction))
        if line_id is None or column is None:
            return None
        file_id, line = line_id.split(":")
        return int(file_id), int(line), column

    def _site_of(self, instruction: int) -> Tuple[SiteKey, UpdateSite] | Classification:
        """the update statement an instruction belongs to, or why it belongs to none usable"""
        position = self._position(instruction)
        if position is None:
            return _not_fixable(UNRESOLVED_INSTRUCTION)
        file_id, line, column = position
        for site in self._ast.get_update_sites(file_id, line):
            if site.covers(column):
                if site.problem is not None:
                    return _not_fixable(site.problem, position)
                return SiteKey(file_id, line, site.first_column), site
        return _not_fixable(END_NOT_AT_UPDATE, position)

    def _incident_in_loop(self, loop: Node) -> Dict[int, Set[int]]:
        """the dependencies between instructions of the loop and of the functions it calls, by instruction:
        any type and whether carried or not, since an access in the same iteration counts as much as one
        in another"""
        incident = self._incident.get(loop.id)
        if incident is not None:
            return incident
        incident = {}
        by_line: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        cus = subtree_of_type(self._pet, loop, CUNode, ignore_called_functions=False)
        cu_ids = {cu.id for cu in cus}
        for cu_id in cu_ids:
            for _sink_cu, source_cu, dependency in self._data_edges.out_edges(cu_id):
                if source_cu not in cu_ids or dependency.dtype not in (DepType.RAW, DepType.WAR, DepType.WAW):
                    continue
                source = dependency.source_instruction_id
                sink = dependency.sink_instruction_id
                if source is None or sink is None:
                    continue
                incident.setdefault(source, set()).add(sink)
                incident.setdefault(sink, set()).add(source)
        for instruction in incident:
            position = self._position(instruction)
            if position is not None:
                by_line.setdefault((position[0], position[1]), []).append((position[2], instruction))
        self._incident[loop.id] = incident
        self._by_line[loop.id] = by_line
        return incident
