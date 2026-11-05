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
import subprocess
import tempfile
from pathlib import Path
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
        # leading context lines dropped to keep the context balanced, see _balance
        self.trimmed = 0

    def counts(self) -> tuple[int, int]:
        old = sum(1 for line in self.lines if line[:1] in (" ", "-"))
        new = sum(1 for line in self.lines if line[:1] in (" ", "+"))
        return old, new

    def changes_something(self) -> bool:
        return any(line[:1] in ("+", "-") for line in self.lines)

    def render(self) -> List[str]:
        old, new = self.counts()
        # "-a,0" names the line an insertion follows; with context lines it names the first of them
        first_old = self.old_start if self.counts_before[0] > 0 else self.old_start + 1
        old_start = first_old + self.old_shift + self.trimmed
        new_start = self.new_start + self.trimmed
        return ["@@ -%d,%d +%d,%d @@%s" % (old_start, old, new_start, new, self.trailer)] + self.lines

    def balance(self) -> None:
        """drop context lines from the longer end, so that the hunk has as many leading as trailing context
        lines: GNU patch takes a hunk with more on one side for one at the beginning or the end of the
        file, and rejects it anywhere else - which a context line made of an atomic line can cause"""
        leading = 0
        while leading < len(self.lines) and self.lines[leading][:1] == " ":
            leading += 1
        trailing = 0
        while trailing < len(self.lines) - leading and self.lines[len(self.lines) - 1 - trailing][:1] == " ":
            trailing += 1
        if leading > trailing:
            self.trimmed = leading - trailing
            self.lines = self.lines[self.trimmed :]
        elif trailing > leading:
            self.lines = self.lines[: len(self.lines) - (trailing - leading)]


def _parse(patch_text: str) -> tuple[List[str], List[_Hunk]]:
    header: List[str] = []
    hunks: List[_Hunk] = []
    # not splitlines(): that also splits at form feeds and other characters a source line may hold
    lines = patch_text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in (entry[:-1] if entry.endswith("\r") else entry for entry in lines):
        match = _HUNK_HEADER.match(line)
        if match:
            hunks.append(_Hunk(int(match.group(1)), int(match.group(3)), match.group(5)))
        elif hunks:
            hunks[-1].lines.append(line)
        else:
            header.append(line)
    return header, hunks


def _sites_of_hunk(hunk: _Hunk) -> List[Optional[int]]:
    """per line of the hunk: the site if it is an added atomic line followed by an unchanged line (the
    update it protects), else None. An atomic followed by a changed line (a rewritten update) is no site:
    which statement it ends up before is not the original line, so it is never shared - a clash then
    fails to build rather than silently moving a pragma."""
    sites: List[Optional[int]] = [None] * len(hunk.lines)
    old_line = hunk.old_start if hunk.counts()[0] > 0 else hunk.old_start + 1
    for index, line in enumerate(hunk.lines):
        kind = line[:1]
        if kind == "+" and _is_atomic_line(line[1:]):
            following = hunk.lines[index + 1] if index + 1 < len(hunk.lines) else None
            if following is not None and following[:1] == " ":
                sites[index] = old_line
        elif kind in (" ", "-"):
            old_line += 1
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
        converted_here = 0
        for index, site in enumerate(_sites_of_hunk(hunk)):
            if site is not None and site in taken:
                hunk.lines[index] = " " + hunk.lines[index][1:]
                converted_here += 1
        converted += converted_here
        if hunk.changes_something():
            if converted_here:
                hunk.balance()
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
            with open(path, "r", newline="", encoding="utf-8", errors="surrogateescape") as f:
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
            with open(original, "r", newline="", encoding="utf-8", errors="surrogateescape") as f:
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
                with open(path, "w", newline="", encoding="utf-8", errors="surrogateescape") as f:
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


def dry_run_all(file_mapping: Dict[int, Path], filtered: FilteredPatches, names: List[str], reverse: bool) -> bool:
    """whether every patch file of a suggestion applies (or, with ``reverse``, reverts) cleanly, checked
    with ``patch --dry-run`` before any of them is applied"""
    for name in names:
        target = file_mapping[int(name[: -len(".patch")] if name.endswith(".patch") else name)]
        command = ["patch", "--batch", "--forward", "--dry-run"] + (["-R"] if reverse else [])
        command += [target.as_posix(), str(filtered.path(name))]
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True
        )
        if result.returncode != 0:
            print("Patch", name, "does not apply cleanly:")
            print(result.stdout + result.stderr)
            return False
    return True
