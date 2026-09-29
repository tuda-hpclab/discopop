# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Reading a compiler's complaints, and mapping them back to DiscoPoP's file ids.

Two things make this less trivial than it looks:

* The paths in a diagnostic name the *project copy* the autotuner built and has since
  deleted, so they cannot be compared to the file mapping directly.
* They come in both shapes. ``compile.sh`` runs with the project copy as its working
  directory, so a project that compiles ``$CXX example.cpp`` produces
  ``example.cpp:24:69: error: ...`` -- relative to a directory that no longer exists --
  while a project building through CMake produces an absolute path into the copy. Both
  have to resolve to the same file id.

Matching is therefore by longest common path *suffix*, which is exactly the property
both shapes share with the original path. The result drives prompt budgeting: source
context is included in full for the files the errors implicate and dropped first for
the ones they do not.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path, PurePosixPath
import re
from typing import Dict, List, Optional

logger = logging.getLogger("PatchRepair").getChild("diagnostics")

# <path>:<line>[:<column>]: <severity>: <message>
# Matches clang's and gcc's shared format. Anything else is kept in the text but
# implicates no file, which costs prompt budgeting detail and nothing else.
DIAGNOSTIC = re.compile(
    r"^(?P<path>[^\s:][^:]*):(?P<line>\d+)(?::(?P<column>\d+))?:\s*(?P<severity>error|fatal error|warning|note):\s*(?P<message>.*)$",
    re.MULTILINE,
)

ERROR_SEVERITIES = ("error", "fatal error")


@dataclass
class Diagnostic:
    path: str
    line: int
    column: Optional[int]
    severity: str
    message: str
    # None when the path could not be resolved against the file mapping.
    file_id: Optional[int] = None

    @property
    def is_error(self) -> bool:
        return self.severity in ERROR_SEVERITIES

    def summary(self) -> str:
        return self.path + ":" + str(self.line) + ": " + self.severity + ": " + self.message


def parse_diagnostics(text: str, file_mapping: Dict[int, Path]) -> List[Diagnostic]:
    """Every diagnostic in ``text``, with its file id resolved where possible."""
    diagnostics: List[Diagnostic] = []
    for match in DIAGNOSTIC.finditer(text or ""):
        column = match.group("column")
        diagnostics.append(
            Diagnostic(
                path=match.group("path").strip(),
                line=int(match.group("line")),
                column=int(column) if column else None,
                severity=match.group("severity"),
                message=match.group("message").strip(),
                file_id=resolve_file_id(match.group("path").strip(), file_mapping),
            )
        )
    return diagnostics


def implicated_file_ids(diagnostics: List[Diagnostic], errors_only: bool = True) -> List[int]:
    """The file ids the diagnostics blame, in the order they are first blamed.

    First-blamed order rather than sorted order: the first error is the causal one far
    more often than not, so a prompt that has to drop material keeps the right file.
    """
    seen: List[int] = []
    for diagnostic in diagnostics:
        if errors_only and not diagnostic.is_error:
            continue
        if diagnostic.file_id is None or diagnostic.file_id in seen:
            continue
        seen.append(diagnostic.file_id)
    return seen


def first_error(text: str) -> str:
    """The first error line of a compiler's output, for a one-line report."""
    for match in DIAGNOSTIC.finditer(text or ""):
        if match.group("severity") in ERROR_SEVERITIES:
            return match.group(0).strip()
    for line in (text or "").splitlines():
        if "error" in line.lower():
            return line.strip()
    return ""


def resolve_file_id(path: str, file_mapping: Dict[int, Path]) -> Optional[int]:
    """The file id whose path shares the longest suffix with ``path``.

    A diagnostic's path points into a deleted project copy, either absolutely or
    relative to it, so only the tail is comparable. The longest match wins, and a tie
    or a match of nothing resolves to None rather than to a guess: attributing an error
    to the wrong file would send the agent to fix code that is not broken.
    """
    if not path:
        return None
    candidate_parts = _normalized_parts(path)
    if not candidate_parts:
        return None

    best_id: Optional[int] = None
    best_length = 0
    ambiguous = False
    for file_id, mapped in file_mapping.items():
        length = _common_suffix_length(candidate_parts, _normalized_parts(str(mapped)))
        if length == 0:
            continue
        if length > best_length:
            best_id, best_length, ambiguous = file_id, length, False
        elif length == best_length and file_id != best_id:
            ambiguous = True

    if ambiguous:
        logger.debug("Diagnostic path '" + path + "' matches several mapped files equally well; not resolving it.")
        return None
    return best_id


def _normalized_parts(path: str) -> List[str]:
    """``path`` as a list of components, with './' and trailing slashes removed."""
    pure = PurePosixPath(path.replace("\\", "/"))
    return [part for part in pure.parts if part not in (".", "/")]


def _common_suffix_length(left: List[str], right: List[str]) -> int:
    length = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        length += 1
    return length


def truncate_diagnostics(text: str, max_chars: int) -> str:
    """Shorten compiler output to ``max_chars``, keeping the *first* errors.

    The first errors are the causal ones; everything after them is usually the same
    mistake echoing through the rest of the translation unit, so truncating the tail
    keeps what an agent can act on.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    kept = text[:max_chars]
    # Do not end mid-line: a half-printed diagnostic reads as a different one.
    newline = kept.rfind("\n")
    if newline > 0:
        kept = kept[:newline]
    return kept + "\n[... " + str(len(text) - len(kept)) + " further characters of output omitted ...]\n"
