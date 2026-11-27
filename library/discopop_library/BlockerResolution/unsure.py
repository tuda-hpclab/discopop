# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The unsure suggestions as the explorer writes them (explorer/unsure_suggestions.json)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

UNSURE_SUGGESTIONS_FILE = os.path.join("explorer", "unsure_suggestions.json")
SUPPORTED_FORMAT_VERSION = 1


class UnsureSuggestionsError(Exception):
    """the explorer output cannot be used"""


@dataclass(frozen=True)
class Location:
    file_id: int
    line: int

    @staticmethod
    def parse(text: Optional[str]) -> Optional["Location"]:
        """a file_id:line string of the explorer, None if it is not one"""
        if text is None:
            return None
        parts = str(text).split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None
        return Location(int(parts[0]), int(parts[1]))

    def __str__(self) -> str:
        return str(self.file_id) + ":" + str(self.line)


@dataclass(frozen=True)
class Access:
    variable: Optional[str]
    memory_region: Optional[str]
    element_access: bool = False


@dataclass(frozen=True)
class Blocker:
    """dependencies between iterations of the loop with the same type, ends and origin"""

    type: str
    source: Optional[Location]
    sink: Optional[Location]
    origin: str
    accesses: Tuple[Access, ...]

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Blocker":
        return Blocker(
            type=str(data.get("type") or "data"),
            source=Location.parse(data.get("source_line")),
            sink=Location.parse(data.get("sink_line")),
            origin=str(data.get("origin") or "unknown"),
            accesses=tuple(
                Access(a.get("variable"), a.get("memory_region"), bool(a.get("element_access", False)))
                for a in data.get("accesses", [])
            ),
        )


@dataclass
class UnsureSuggestion:
    pattern_id: int
    type: str
    start: Location
    end: Location
    pragma: str
    blockers: List[Blocker]
    # everything the explorer wrote, e.g. the data sharing clauses
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Fingerprint:
    """identifies the explorer output a check belongs to: a later explorer run makes the check stale"""

    mtime_ns: int
    size: int

    @staticmethod
    def of(path: str) -> "Fingerprint":
        stat = os.stat(path)
        return Fingerprint(stat.st_mtime_ns, stat.st_size)

    def to_dict(self) -> Dict[str, int]:
        return {"mtime_ns": self.mtime_ns, "size": self.size}


def load_unsure_suggestions(dot_dp_path: str) -> List[UnsureSuggestion]:
    path = os.path.join(dot_dp_path, UNSURE_SUGGESTIONS_FILE)
    if not os.path.exists(path):
        raise UnsureSuggestionsError(
            "No unsure suggestions found (" + path + "). Run discopop_explorer --unsure-suggestions first."
        )
    with open(path) as f:
        data = json.load(f)
    version = data.get("format_version")
    if version != SUPPORTED_FORMAT_VERSION:
        raise UnsureSuggestionsError(
            path + " has format version " + str(version) + ", expected " + str(SUPPORTED_FORMAT_VERSION)
        )
    suggestions: List[UnsureSuggestion] = []
    for entry in data.get("suggestions", []):
        start = Location.parse(entry.get("start_line"))
        end = _loop_end(entry, start)
        if start is None or end is None:
            raise UnsureSuggestionsError("unsure suggestion without a location: " + str(entry.get("pattern_id")))
        suggestions.append(
            UnsureSuggestion(
                pattern_id=int(entry["pattern_id"]),
                type=str(entry.get("type", "do_all")),
                start=start,
                end=end,
                pragma=str(entry.get("pragma", "")),
                blockers=[Blocker.from_dict(b) for b in entry.get("blockers", [])],
                data=entry,
            )
        )
    return suggestions


def _loop_end(entry: Dict[str, Any], start: Optional[Location]) -> Optional[Location]:
    """the last line of the loop: from its region if recorded, since the pattern's end_line is that of the loop's
    entry CU, i.e. mostly its first line"""
    region = entry.get("region")
    if start is not None and isinstance(region, dict):
        try:
            file_id, end_line = int(region["file_id"]), int(region["end_line"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if file_id == start.file_id and end_line >= start.line:
                return Location(file_id, end_line)
    return Location.parse(entry.get("end_line"))
