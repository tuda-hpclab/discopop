# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""`#pragma omp atomic update` lines shared by several applied suggestions.

A doall loop made parallel by atomic updates (the explorer's ``--atomic-updates``) inserts the
pragma before every update it relies on, possibly in a function it calls. Two suggestions can rely on
the same update -- an outer loop and a loop in the function it calls, or two loops calling one
function -- and every patch is a diff against the original sources, so applying both would insert
the pragma twice, which does not compile.

So an atomic line is owned by the applied suggestions together: it is inserted by the first of them
to be applied and removed by the last of them to be rolled back. A patch is filtered before it is
applied or rolled back: an atomic line whose *site* another applied suggestion also has becomes a
context line, i.e. ``patch`` checks that the pragma is there and leaves it alone.

The site of an atomic line is the line of the original file it precedes. Every patch of a file is a
diff against that same original, so the site is the same in all of them.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Set

ATOMIC_PRAGMA = "#pragma omp atomic update"

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _is_atomic_line(body: str) -> bool:
    return body.strip() == ATOMIC_PRAGMA


class _Hunk:
    def __init__(self, old_start: int, new_start: int, trailer: str) -> None:
        self.old_start = old_start
        self.new_start = new_start
        self.trailer = trailer
        self.lines: List[str] = []
        # lines turned into context lines here or in an earlier hunk: they exist in the file the filtered
        # patch is applied to, so they shift its old coordinates
        self.old_shift = 0
        self.counts_before = (0, 0)

    def counts(self) -> tuple[int, int]:
        old = sum(1 for line in self.lines if line[:1] in (" ", "-"))
        new = sum(1 for line in self.lines if line[:1] in (" ", "+"))
        return old, new

    def changes_something(self) -> bool:
        return any(line[:1] in ("+", "-") for line in self.lines)

    def render(self) -> List[str]:
        old, new = self.counts()
        old_start = self.old_start + self.old_shift
        # "-a,0" names the line an insertion follows; with context lines it names the first of them
        if self.counts_before[0] == 0 and old > 0:
            old_start += 1
        return ["@@ -%d,%d +%d,%d @@%s" % (old_start, old, self.new_start, new, self.trailer)] + self.lines


def _parse(patch_text: str) -> tuple[List[str], List[_Hunk]]:
    header: List[str] = []
    hunks: List[_Hunk] = []
    for line in patch_text.splitlines():
        match = _HUNK_HEADER.match(line)
        if match:
            hunks.append(_Hunk(int(match.group(1)), int(match.group(3)), match.group(5)))
        elif hunks:
            hunks[-1].lines.append(line)
        else:
            header.append(line)
    return header, hunks


def _sites_of_hunk(hunk: _Hunk) -> List[Optional[int]]:
    """per line of the hunk: the site if it is an added atomic line, else None"""
    sites: List[Optional[int]] = []
    old_line = hunk.old_start if hunk.counts()[0] > 0 else hunk.old_start + 1
    pending: List[int] = []
    for index, line in enumerate(hunk.lines):
        sites.append(None)
        kind = line[:1]
        if kind == "+" and _is_atomic_line(line[1:]):
            pending.append(index)
        elif kind in (" ", "-"):
            for atomic_index in pending:
                sites[atomic_index] = old_line
            pending = []
            old_line += 1
    # an atomic line at the end of a hunk precedes the line after it
    for atomic_index in pending:
        sites[atomic_index] = old_line
    return sites


def atomic_sites(patch_text: str) -> Set[int]:
    """the original lines the patch inserts an atomic pragma before"""
    _, hunks = _parse(patch_text)
    return {site for hunk in hunks for site in _sites_of_hunk(hunk) if site is not None}


def filter_patch(patch_text: str, taken: Set[int]) -> Optional[str]:
    """the patch without inserting (or, reversed, removing) the atomic lines at the sites in ``taken``.

    Returns the text unchanged if nothing is taken, and None if nothing is left to change: a hunk
    whose only change was such a line is dropped, and ``patch`` rejects a patch without hunks."""
    header, hunks = _parse(patch_text)
    converted = 0
    kept: List[_Hunk] = []
    for hunk in hunks:
        hunk.counts_before = hunk.counts()
        hunk.old_shift = converted
        for index, site in enumerate(_sites_of_hunk(hunk)):
            if site is not None and site in taken:
                hunk.lines[index] = " " + hunk.lines[index][1:]
                converted += 1
        if hunk.changes_something():
            kept.append(hunk)
    if converted == 0:
        return patch_text
    if not kept:
        return None
    lines = list(header)
    for hunk in kept:
        lines += hunk.render()
    terminator = "\r\n" if "\r\n" in patch_text else "\n"
    return terminator.join(lines) + terminator


def sites_taken(patch_generator_dir: str, suggestion_ids: List[str], patch_file_name: str) -> Set[int]:
    """the atomic sites the patches of ``suggestion_ids`` for one file insert"""
    taken: Set[int] = set()
    for suggestion_id in suggestion_ids:
        path = os.path.join(patch_generator_dir, suggestion_id, patch_file_name)
        if os.path.isfile(path):
            with open(path, "r", newline="") as f:
                taken |= atomic_sites(f.read())
    return taken


class FilteredPatches:
    """The patch files of one suggestion as they are to be applied or rolled back, given the suggestions
    that stay applied besides it. ``path(name)`` is the file to hand to ``patch``, None if nothing is
    left to do for that file. Temporary files are removed on ``close``."""

    def __init__(self, patch_generator_dir: str, suggestion_id: str, others: List[str]) -> None:
        self._directory = os.path.join(patch_generator_dir, suggestion_id)
        self._tempdir: Optional[str] = None
        self._paths: Dict[str, Optional[str]] = {}
        for name in sorted(os.listdir(self._directory)):
            original = os.path.join(self._directory, name)
            taken = sites_taken(patch_generator_dir, others, name)
            if not taken:
                self._paths[name] = original
                continue
            with open(original, "r", newline="") as f:
                text = f.read()
            filtered = filter_patch(text, taken)
            if filtered is None:
                self._paths[name] = None
            elif filtered == text:
                self._paths[name] = original
            else:
                if self._tempdir is None:
                    self._tempdir = tempfile.mkdtemp(prefix="discopop_shared_atomics_")
                path = os.path.join(self._tempdir, name)
                with open(path, "w", newline="") as f:
                    f.write(filtered)
                self._paths[name] = path

    def names(self) -> List[str]:
        return list(self._paths)

    def path(self, name: str) -> Optional[str]:
        return self._paths[name]

    def close(self) -> None:
        if self._tempdir is not None:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None
