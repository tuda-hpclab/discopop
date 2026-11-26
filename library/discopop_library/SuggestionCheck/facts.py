# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The facts about an unsure suggestion, as the agent is shown them: its description, the loop and every blocker in
words. Facts only: nothing here proposes how a blocker could be resolved (design/agent_checked_suggestions.md, §1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from discopop_library.SuggestionCheck.unsure import Blocker, Location, UnsureSuggestion

# lines shown around a blocker's statement outside the loop
CONTEXT_LINES = 6
# a loop longer than this is shown in part, around its blockers
MAX_LOOP_LINES = 200

_DEPENDENCY_WORDS = {
    "RAW": "reads data which {source} wrote in an earlier iteration",
    "WAW": "writes data which {source} also wrote in an earlier iteration",
    "WAR": "writes data which {source} read in an earlier iteration",
}
_ORIGIN_WORDS = {
    "dynamic": "observed during profiling",
    "static": "reported by the static analysis of the code",
}


@dataclass
class SourceFiles:
    """the source files of the project, with the paths the agent is shown"""

    file_mapping: Dict[int, Path]
    project_root: str

    def display_path(self, file_id: int) -> str:
        path = self.file_mapping.get(file_id)
        if path is None:
            return "<file " + str(file_id) + ">"
        try:
            relative = os.path.relpath(str(path), self.project_root)
        except ValueError:
            return str(path)
        return str(path) if relative.startswith("..") else relative

    def lines(self, file_id: int) -> List[str]:
        path = self.file_mapping.get(file_id)
        if path is None or not os.path.exists(path):
            return []
        with open(path, "r", errors="replace") as f:
            return f.read().splitlines()

    def line_text(self, location: Optional[Location]) -> str:
        if location is None:
            return ""
        lines = self.lines(location.file_id)
        if 1 <= location.line <= len(lines):
            return lines[location.line - 1].strip()
        return ""

    def where(self, location: Optional[Location]) -> str:
        if location is None:
            return "an unknown line"
        return self.display_path(location.file_id) + ":" + str(location.line)


def numbered(lines: List[str], first: int, last: int) -> str:
    """lines first..last (1-based, inclusive) with their line numbers"""
    first = max(first, 1)
    last = min(last, len(lines))
    width = len(str(last))
    return "\n".join(str(n).rjust(width) + " | " + lines[n - 1] for n in range(first, last + 1))


def describe_blocker(index: int, blocker: Blocker, files: SourceFiles) -> str:
    source = files.where(blocker.source)
    sink = files.where(blocker.sink)
    words = _DEPENDENCY_WORDS.get(blocker.type, "depends on {source} in an earlier iteration")
    lines = [
        "### Blocker " + str(index),
        "",
        "- "
        + blocker.type
        + " dependency: in one iteration, the statement at `"
        + sink
        + "` "
        + words.format(source="the statement at `" + source + "`")
        + ".",
        "- `" + source + "`: `" + files.line_text(blocker.source) + "`",
    ]
    if blocker.sink != blocker.source:
        lines.append("- `" + sink + "`: `" + files.line_text(blocker.sink) + "`")
    lines.append(
        "- " + _ORIGIN_WORDS.get(blocker.origin, blocker.origin).capitalize() + ". If such a line calls a function, "
        "the access may happen inside the called function."
    )
    accesses = []
    for access in blocker.accesses:
        name = "`" + str(access.variable) + "`"
        if access.element_access:
            name += " (an element of it)"
        accesses.append(name)
    if accesses:
        lines.append(
            "- Data involved, as named in the compiled program (names can be compiler generated or mangled): "
            + ", ".join(accesses)
            + "."
        )
    return "\n".join(lines)


def describe_blockers(suggestion: UnsureSuggestion, files: SourceFiles) -> str:
    return "\n\n".join(describe_blocker(i + 1, b, files) for i, b in enumerate(suggestion.blockers))


def code_excerpts(suggestion: UnsureSuggestion, files: SourceFiles) -> str:
    """the loop with line numbers, and the code around each blocker statement outside it"""
    sections: List[str] = []
    loop_file = suggestion.start.file_id
    lines = files.lines(loop_file)
    first, last = suggestion.start.line, suggestion.end.line
    if last - first + 1 > MAX_LOOP_LINES:
        last = first + MAX_LOOP_LINES - 1
    sections.append(
        "### The loop, `"
        + files.display_path(loop_file)
        + "` lines "
        + str(suggestion.start.line)
        + "-"
        + str(suggestion.end.line)
        + "\n\n```\n"
        + numbered(lines, first, last)
        + "\n```"
    )
    shown: Set[Tuple[int, int]] = set()
    for blocker in suggestion.blockers:
        for location in (blocker.source, blocker.sink):
            if location is None or (location.file_id, location.line) in shown:
                continue
            shown.add((location.file_id, location.line))
            if location.file_id == loop_file and first <= location.line <= last:
                continue
            excerpt = files.lines(location.file_id)
            if not excerpt:
                continue
            sections.append(
                "### `"
                + files.where(location)
                + "`\n\n```\n"
                + numbered(excerpt, location.line - CONTEXT_LINES, location.line + CONTEXT_LINES)
                + "\n```"
            )
    return "\n\n".join(sections)


_CLAUSES = (
    ("private", "private"),
    ("first_private", "firstprivate"),
    ("last_private", "lastprivate"),
    ("shared", "shared"),
)


def directive_without_blockers(suggestion: UnsureSuggestion) -> str:
    """the directive DiscoPoP would suggest for the loop if it had no blockers"""
    data = suggestion.data
    parts = [suggestion.pragma or "#pragma omp parallel for"]
    for key, clause in _CLAUSES:
        names = [str(v) for v in data.get(key) or []]
        if names:
            parts.append(clause + "(" + ", ".join(names) + ")")
    reductions: Dict[str, List[str]] = dict()
    for entry in data.get("reduction") or []:
        operation, _, name = str(entry).rpartition(":")
        reductions.setdefault(operation or "+", []).append(name)
    for operation, names in sorted(reductions.items()):
        parts.append("reduction(" + operation + ":" + ", ".join(names) + ")")
    return " ".join(parts)


def describe_suggestion(suggestion: UnsureSuggestion, files: SourceFiles) -> str:
    """the suggestion as the MCP server describes suggestions to agents: where, which pattern, which directive"""
    pattern = "reduction" if suggestion.type == "reduction" else "doall"
    lines = [
        "Suggestion "
        + str(suggestion.pattern_id)
        + ": loop "
        + files.display_path(suggestion.start.file_id)
        + ":"
        + str(suggestion.start.line)
        + "-"
        + str(suggestion.end.line)
        + ": "
        + pattern
        + ", "
        + str(len(suggestion.blockers))
        + " blocker"
        + ("" if len(suggestion.blockers) == 1 else "s")
        + ".",
        "",
        "Without the blockers, DiscoPoP would suggest this directive for the loop:",
        "",
        "    " + directive_without_blockers(suggestion),
        "",
        "Its data sharing clauses were derived as if the blockers did not exist.",
    ]
    for note in suggestion.data.get("sharing_notes") or []:
        lines.append("Note: " + str(note))
    return "\n".join(lines)
