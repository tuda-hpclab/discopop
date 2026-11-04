# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""A doall loop made parallel by atomic updates (the explorer's --atomic-updates) gets
`#pragma omp atomic update` before each listed update, possibly in another file, and stays
sequential if one of them cannot be inserted."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from discopop_library.CodeGenerator.CodeGenerator import from_json_strings
from discopop_library.CodeGenerator.classes.ContentBuffer import ContentBuffer

LOOP = """\
void add(double* h, int k, double v);
void run(double* h, int* idx, int n) {
  for (int i = 0; i < n; i++) {
    add(h, idx[i], 1.0);
  }
}
"""

CALLEE = """\
void add(double* h, int k, double v) {
  h[k] += v;
}
"""


def _doall(**extra: Any) -> Dict[str, Any]:
    return {
        "pattern_id": 7,
        "type": "DOALL",
        "node_id": "1:3",
        "start_line": "1:3",
        "end_line": "1:5",
        "pragma": "#pragma omp parallel for",
        "first_private": [],
        "private": [],
        "last_private": [],
        "shared": [],
        "reduction": [],
        **extra,
    }


def _generate(tmp_path: Path, pattern: Dict[str, Any]) -> Dict[int, List[str]]:
    (tmp_path / "loop.c").write_text(LOOP)
    (tmp_path / "callee.c").write_text(CALLEE)
    result = from_json_strings(
        {1: tmp_path / "loop.c", 2: tmp_path / "callee.c"},
        {"do_all": [json.dumps(pattern)]},
        skip_compilation_check=True,
    )
    return {file_id: code.splitlines() for file_id, code in result.items()}


ATOMICS = [{"file_id": 2, "line": 2, "operation": "+=", "variable": "h"}]


def test_each_atomic_update_gets_its_pragma_in_its_own_file(tmp_path: Path) -> None:
    result = _generate(tmp_path, _doall(atomic_updates=ATOMICS))
    assert result[1][2] == "  #pragma omp parallel for "
    assert result[2] == ["void add(double* h, int k, double v) {", "  #pragma omp atomic update", "  h[k] += v;", "}"]


def test_a_loop_without_atomic_updates_changes_only_its_own_file(tmp_path: Path) -> None:
    result = _generate(tmp_path, _doall())
    assert "#pragma omp parallel for " in "\n".join(result[1])
    assert 2 not in result or "omp atomic" not in "\n".join(result[2])


def test_the_loop_stays_sequential_if_an_atomic_update_cannot_be_inserted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ContentBuffer.add_pragma

    def failing_atomics(self: ContentBuffer, *args: Any, **kwargs: Any) -> bool:
        pragma = args[1]
        if kwargs.get("add_as_comment", False):
            # the fallback compiles its result, which needs no compiler here
            return original(self, *args, **{**kwargs, "skip_compilation_check": True})
        if "omp atomic" in pragma.pragma_str:
            return False
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContentBuffer, "add_pragma", failing_atomics)
    result = _generate(tmp_path, _doall(atomic_updates=ATOMICS))
    assert "//<DiscoPoP-IGNORED> #pragma omp parallel for " in "\n".join(result[1])
    # the atomic is left out rather than commented: a comment would take the line another suggestion's
    # atomic before the same update goes to
    assert 2 not in result or "omp atomic" not in "\n".join(result[2])
