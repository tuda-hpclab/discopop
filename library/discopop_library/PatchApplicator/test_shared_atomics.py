# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Two applied suggestions relying on the same atomic update share one `#pragma omp atomic update`."""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

import pytest

from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.apply import apply_patches
from discopop_library.PatchApplicator.rollback import rollback_patches
from discopop_library.PatchApplicator.shared_atomics import atomic_sites, filter_patch

ORIGINAL = """\
void add(double* h, int k, double v) {
  h[k] += v;
}
void run(double* h, int* idx, int n) {
  for (int i = 0; i < n; i++) {
    add(h, idx[i], 1.0);
  }
}
void other(double* h, int n) {
  for (int i = 0; i < n; i++) {
    add(h, i % 4, 2.0);
  }
}
"""

ATOMIC_ONLY = """\
--- a.c
+++ a.c
@@ -1,3 +1,4 @@
 void add(double* h, int k, double v) {
+  #pragma omp atomic update
   h[k] += v;
 }
"""


def _unified(tmp_path: Path, modified: str) -> str:
    a = tmp_path / "orig.c"
    b = tmp_path / "mod.c"
    a.write_text(ORIGINAL)
    b.write_text(modified)
    return subprocess.run(["diff", "-u", str(a), str(b)], capture_output=True, text=True).stdout


def _insert(lines: List[str], before: Dict[int, str]) -> str:
    """the original with ``text`` inserted before original line ``n`` (1-based) for each entry"""
    out: List[str] = []
    for number, line in enumerate(lines, start=1):
        if number in before:
            out.append(before[number])
        out.append(line)
    return "\n".join(out) + "\n"


ORIGINAL_LINES = ORIGINAL.splitlines()
RUN = _insert(ORIGINAL_LINES, {2: "  #pragma omp atomic update", 5: "  #pragma omp parallel for"})
OTHER = _insert(ORIGINAL_LINES, {2: "  #pragma omp atomic update", 10: "  #pragma omp parallel for"})


def test_the_site_is_the_original_line_the_pragma_precedes() -> None:
    assert atomic_sites(ATOMIC_ONLY) == {2}


def test_a_commented_atomic_is_not_an_atomic() -> None:
    assert atomic_sites(ATOMIC_ONLY.replace("+  #pragma", "+  //<DiscoPoP-IGNORED> #pragma")) == set()


def test_a_patch_whose_only_change_is_a_taken_atomic_is_empty() -> None:
    assert filter_patch(ATOMIC_ONLY, {2}) is None


def test_nothing_taken_leaves_the_patch_unchanged() -> None:
    assert filter_patch(ATOMIC_ONLY, set()) == ATOMIC_ONLY
    assert filter_patch(ATOMIC_ONLY, {7}) == ATOMIC_ONLY


def test_a_taken_atomic_becomes_context_and_the_header_counts_follow(tmp_path: Path) -> None:
    patch = _unified(tmp_path, RUN)
    assert atomic_sites(patch) == {2}
    filtered = filter_patch(patch, {2})
    assert filtered is not None
    assert "+  #pragma omp atomic update" not in filtered
    assert "\n   #pragma omp atomic update\n" in filtered
    assert "+  #pragma omp parallel for" in filtered
    # applied to a file that already has the pragma, it adds only the loop pragma
    target = tmp_path / "target.c"
    target.write_text(_insert(ORIGINAL_LINES, {2: "  #pragma omp atomic update"}))
    (tmp_path / "f.patch").write_text(filtered)
    result = subprocess.run(["patch", "--batch", "--forward", str(target), str(tmp_path / "f.patch")])
    assert result.returncode == 0
    assert target.read_text() == RUN


def test_crlf_patches_keep_their_line_terminator() -> None:
    crlf = ATOMIC_ONLY.replace("\n", "\r\n").replace("+  #pragma", "+  #pragma")
    with_loop = crlf + "@@ -5,1 +6,2 @@\r\n+  #pragma omp parallel for\r\n   for (int i = 0; i < n; i++) {\r\n"
    filtered = filter_patch(with_loop, {2})
    assert filtered is not None and "\r\n" in filtered and "\n" not in filtered.replace("\r\n", "")


def _project(tmp_path: Path) -> tuple[Dict[int, Path], str, str, PatchApplicatorArguments]:
    source = tmp_path / "src" / "a.c"
    source.parent.mkdir()
    source.write_text(ORIGINAL)
    generator = tmp_path / "patch_generator"
    for suggestion, modified in (("1", RUN), ("2", OTHER)):
        (generator / suggestion).mkdir(parents=True)
        (generator / suggestion / "1.patch").write_text(_unified(tmp_path, modified))
    applied = tmp_path / "applied_suggestions.json"
    applied.write_text(json.dumps({"applied": []}))
    # the line mapping the applicator keeps up to date
    (tmp_path / "line_mapping.json").write_text(json.dumps({"1": {str(n): n for n in range(1, 14)}}))
    return (
        {1: source},
        str(applied),
        str(generator),
        PatchApplicatorArguments(
            verbose=False,
            apply=[],
            rollback=[],
            clear=False,
            load=False,
            list=False,
            log_level="WARNING",
            write_log=False,
        ),
    )


@pytest.mark.skipif(shutil.which("patch") is None, reason="needs patch(1)")
@pytest.mark.parametrize("apply_order,rollback_order", list(itertools.product(itertools.permutations("12"), repeat=2)))
def test_two_suggestions_share_the_atomic_in_every_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, apply_order: tuple[str, ...], rollback_order: tuple[str, ...]
) -> None:
    monkeypatch.chdir(tmp_path)
    files, applied, generator, arguments = _project(tmp_path)
    source = files[1]
    for suggestion in apply_order:
        result = apply_patches([suggestion], files, arguments, applied, generator)
        assert result.applied == [suggestion], source.read_text()
    text = source.read_text()
    assert text.count("#pragma omp atomic update") == 1
    assert text.count("#pragma omp parallel for") == 2
    first, second = rollback_order
    assert rollback_patches([first], files, arguments, applied, generator) == 0
    remaining = OTHER if first == "1" else RUN
    assert source.read_text() == remaining
    assert rollback_patches([second], files, arguments, applied, generator) == 0
    assert source.read_text() == ORIGINAL
