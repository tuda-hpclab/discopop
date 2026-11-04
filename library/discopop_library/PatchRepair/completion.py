# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Patch completion: filling in what the patch generator could not decide.

Some parts of a parallelization cannot be derived from the profile. The cutoff of a recursive task group is the
example: ``final(n <= 25)`` depends on the *meaning* of the arguments, which the dependence data does not show. The
generator therefore leaves a marker comment ``/* DiscoPoP TODO: ... */`` at the place, which keeps the patch
compilable and tells the reader what is missing. The completion mode of the patch repair tool hands such a patch to
an agent and asks it to replace the marker.

This module knows the markers. A new kind of placeholder is one entry in :data:`PLACEHOLDER_KINDS`: the text the
generator writes and what the agent should put there.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional

from discopop_library.CodeGenerator.classes.UnpackedSuggestion import RECURSIVE_TASK_CUTOFF_MARKER
from discopop_library.PatchRepair.patchset import PatchSet

# Any marker of the generator: a comment that starts with "DiscoPoP TODO:". Matching the family instead of the known
# kinds means a placeholder nobody registered here is still found, and still has to be replaced.
PLACEHOLDER = re.compile(r"/\*\s*DiscoPoP TODO:(?P<text>.*?)\*/")


@dataclass(frozen=True)
class PlaceholderKind:
    name: str
    # the text of the marker as the generator writes it, whitespace normalized
    marker: str
    # what the agent is asked to put in its place
    instruction: str


PLACEHOLDER_KINDS = (
    PlaceholderKind(
        name="recursive task cutoff",
        marker=" ".join(RECURSIVE_TASK_CUTOFF_MARKER.split()),
        instruction=(
            "Replace the marker comment by a `final(<condition>)` clause of the task directive it follows: the "
            "condition is true when the remaining work is too small to be worth a task, e.g. a bound on a parameter "
            "that shrinks with every recursive call. Without a cutoff, every call down to the smallest one creates "
            "a task, and the overhead of the tasks outweighs the work. `final` also runs the tasks below it without "
            "new tasks. Choose the threshold from the meaning of the arguments in the code; it can be tuned later by "
            "measuring."
        ),
    ),
)

_GENERIC_INSTRUCTION = (
    "Replace the marker comment by what it asks for, so that the directive is complete and the code compiles."
)


@dataclass(frozen=True)
class Placeholder:
    """One marker in the lines a patch adds."""

    file_id: int
    # the marker as written, ``/* DiscoPoP TODO: ... */``
    text: str
    # the added line that holds it, without the leading ``+``
    line: str
    kind: str
    instruction: str


def _normalize(text: str) -> str:
    return " ".join(text.split())


def kind_of(marker: str) -> Optional[PlaceholderKind]:
    normalized = _normalize(marker)
    for kind in PLACEHOLDER_KINDS:
        if kind.marker == normalized:
            return kind
    return None


def placeholders_in_patch(patch_text: str, file_id: int = 0) -> List[Placeholder]:
    """The markers on the lines a patch *adds*; a marker in context lines was in the code before."""
    found: List[Placeholder] = []
    for line in patch_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for match in PLACEHOLDER.finditer(line):
            known = kind_of(match.group(0))
            found.append(
                Placeholder(
                    file_id=file_id,
                    text=match.group(0),
                    line=line[1:].strip(),
                    kind=known.name if known is not None else "other",
                    instruction=known.instruction if known is not None else _GENERIC_INSTRUCTION,
                )
            )
    return found


def placeholders_of(patch_set: PatchSet) -> List[Placeholder]:
    found: List[Placeholder] = []
    for file_id, entry in sorted(patch_set.entries.items()):
        found.extend(placeholders_in_patch(entry.text, file_id))
    return found


def remaining_placeholders(candidate: PatchSet) -> Optional[str]:
    """The failure text for the agent when a marker is left in the answer, None when there is none."""
    left = placeholders_of(candidate)
    if not left:
        return None
    lines = ["The patch still contains a placeholder that has to be replaced:", ""]
    for placeholder in left:
        lines.append("* file id " + str(placeholder.file_id) + ": `" + placeholder.line + "`")
    lines.append("")
    lines.append("Replace every `/* DiscoPoP TODO: ... */` comment; do not keep it, not even next to the answer.")
    return "\n".join(lines)


def describe_placeholders(placeholders: List[Placeholder]) -> str:
    """The prompt section naming what has to be completed and how."""
    if not placeholders:
        return "(none)"
    lines: List[str] = []
    for placeholder in placeholders:
        lines.append("* file id " + str(placeholder.file_id) + ", " + placeholder.kind + ": `" + placeholder.line + "`")
    instructions: Dict[str, str] = {}
    for placeholder in placeholders:
        instructions.setdefault(placeholder.kind, placeholder.instruction)
    lines.append("")
    for kind, instruction in instructions.items():
        lines.append("What to do for " + kind + ": " + instruction)
    return "\n".join(lines)
