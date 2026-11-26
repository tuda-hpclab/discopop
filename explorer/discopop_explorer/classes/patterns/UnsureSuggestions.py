# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Unsure suggestions: loops which are not parallelizable as they are, because of a few dependencies between their
iterations, see design/agent_checked_suggestions.md.

They are kept apart from the detection result on purpose. Many tools walk every list of the PatternStorage, and an
unsure suggestion must never be taken for a parallelization suggestion: its patch is incorrect without a change."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.patterns.PatternDecisions import DependencyRecord
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo

FORMAT_VERSION = 1
DEFAULT_MAX_BLOCKERS = 4
NOTE = (
    "Not parallelization suggestions: each loop below has dependencies between its iterations (blockers), and its "
    "patch is incorrect as it is."
)


@dataclass(frozen=True)
class Blocker:
    """the dependencies between iterations with the same ends: one statement depending on another (or itself) in an
    earlier iteration. Its accesses are the variables and memory regions involved, e.g. the size, the data pointer and
    the elements of a vector a push_back changes; counting them separately would make one problem look like several."""

    type: Optional[str]
    source_line: Optional[str]
    sink_line: Optional[str]
    origin: Optional[str]
    accesses: Tuple[DependencyRecord, ...]

    def to_dict(self) -> Dict[str, Any]:
        accesses: List[Dict[str, Any]] = []
        for record in self.accesses:
            access: Dict[str, Any] = {"variable": record.variable, "memory_region": record.memory_region}
            if record.element_access:
                access["element_access"] = True
            accesses.append(access)
        return {
            "type": self.type,
            "source_line": self.source_line,
            "sink_line": self.sink_line,
            "origin": self.origin,
            "accesses": accesses,
        }


def _sort_key(values: Iterable[Any]) -> Tuple[str, ...]:
    return tuple("" if v is None else str(v) for v in values)


def group_blockers(records: Iterable[DependencyRecord]) -> List[Blocker]:
    """the dependencies grouped by their type, ends and origin, without repetitions, sorted: the order in which they
    are found follows sets of the task graph, and varies between runs"""
    groups: Dict[Tuple[Optional[str], ...], Set[DependencyRecord]] = dict()
    for record in records:
        key = (record.type, record.source_line, record.sink_line, record.origin)
        groups.setdefault(key, set()).add(record)
    return [
        Blocker(
            key[0],
            key[1],
            key[2],
            key[3],
            tuple(sorted(groups[key], key=lambda r: _sort_key(r.to_dict().values()))),
        )
        for key in sorted(groups, key=_sort_key)
    ]


@dataclass
class UnsureLoop:
    """a loop rejected only because of dependencies between its iterations, as found by a detector"""

    pet_node_id: NodeID
    blockers: List[Blocker]
    # builds the pattern the loop would have had without its blockers. Called only once every detector has run,
    # since building a pattern allocates its pattern id (see UnsureSuggestions.build).
    build_pattern: Callable[[], PatternInfo]


class UnsureSuggestions:
    """collects the unsure loops of a pattern detection and writes explorer/unsure_suggestions.json"""

    def __init__(self, max_blockers: int = DEFAULT_MAX_BLOCKERS) -> None:
        if max_blockers < 1:
            raise ValueError("max_blockers must be at least 1, not " + str(max_blockers))
        self.max_blockers = max_blockers
        self._loops: Dict[NodeID, UnsureLoop] = dict()
        self.suggestions: List[Tuple[PatternInfo, UnsureLoop]] = []

    def accepts(self, blocker_count: int) -> bool:
        """whether a loop with this many blockers is a near miss"""
        return 0 < blocker_count <= self.max_blockers

    def add(self, loop: UnsureLoop) -> None:
        if not self.accepts(len(loop.blockers)):
            return
        # one per loop: the task graph holds several copies of a loop, and the first one rejected counts
        self._loops.setdefault(loop.pet_node_id, loop)

    def __len__(self) -> int:
        return len(self._loops)

    def build(self) -> None:
        """builds the patterns. To be called after all detectors have run: the pattern ids are then allocated after
        those of the parallelization suggestions, which therefore stay the same with and without unsure
        suggestions, and never collide with them."""
        for node_id in sorted(self._loops, key=str):
            loop = self._loops[node_id]
            self.suggestions.append((loop.build_pattern(), loop))
        self._loops.clear()

    def to_dict(self) -> Dict[str, Any]:
        # imported here: the serializer imports the library's result classes, which import the explorer
        from discopop_explorer.json_serializer import PatternBaseSerializer

        entries: List[Dict[str, Any]] = []
        for pattern, loop in self.suggestions:
            # the serializer removes the private members from the dict it is given, so it gets a copy
            entry: Dict[str, Any] = json.loads(json.dumps(copy.copy(pattern), cls=PatternBaseSerializer))
            entry["type"] = pattern_type_of(pattern)
            entry["blockers"] = [b.to_dict() for b in loop.blockers]
            entries.append(entry)
        return {
            "format_version": FORMAT_VERSION,
            "note": NOTE,
            "max_blockers": self.max_blockers,
            "suggestions": entries,
        }

    def save(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=1)
            f.write("\n")


def pattern_type_of(pattern: PatternInfo) -> str:
    """the key the pattern would be listed under in patterns.json"""
    # imported here to avoid an import cycle with the detectors
    from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo

    return "reduction" if isinstance(pattern, ReductionInfo) else "do_all"
