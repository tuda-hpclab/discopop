# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Directories of the project excluded with ``DP_PROJECT_EXCLUDE_DIRS`` are no project code.

Dependencies are often fetched below the project directory (``build/_deps`` of CMake's
FetchContent). Without an exclusion the pass instruments their code as the project's, maps their
headers in ``FileMapping.txt``, and the AST export keeps their declarations, which for template
libraries is gigabytes per translation unit. ``DP_PROJECT_EXCLUDE_DIRS`` lists directories
(separated by ``:``, absolute or relative to ``DP_PROJECT_ROOT_DIR``) whose files are none of it.
"""

import os
from pathlib import Path

import pytest

from .utilities import InstrumentedProgram, compile_to_ir

SOURCE = """\
#include "deps/library/library.hpp"
#include "deps2/other.hpp"

int sum(int* values, int count) {
  int total = 0;
  for (int i = 0; i < count; ++i) {
    total += values[i];
  }
  return total;
}

int main() {
  int values[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  return sum(values, 8) + library_sum(values, 8) + other_sum(values, 8) == 108 ? 0 : 1;
}
"""

LIBRARY = """\
inline int library_sum(int* values, int count) {
  int total = 0;
  for (int i = 0; i < count; ++i) {
    total += values[i];
  }
  return total;
}
"""

OTHER = """\
inline int other_sum(int* values, int count) {
  int total = 0;
  for (int i = 0; i < count; ++i) {
    total += values[i];
  }
  return total;
}
"""


def _project(directory: Path) -> Path:
    (directory / "deps" / "library").mkdir(parents=True)
    (directory / "deps" / "library" / "library.hpp").write_text(LIBRARY)
    (directory / "deps2").mkdir()
    (directory / "deps2" / "other.hpp").write_text(OTHER)
    return directory


def _function(program: InstrumentedProgram, part: str) -> str:
    # the mangled name of a C++ function "<name>(int*, int)" contains "<length><name>P"
    names = [name for name in program.user_functions() if f"{len(part)}{part}P" in name]
    assert len(names) == 1, program.user_functions()
    return names[0]


def _instrumented(program: InstrumentedProgram, part: str) -> bool:
    return program.callback_counts(function=_function(program, part)).get("__dp_func_entry", 0) > 0


def _mapped(program: InstrumentedProgram) -> list[str]:
    return sorted(os.path.relpath(path, program.directory) for path in program.file_mapping.values())


def test_without_exclusion_the_dependency_is_project_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    program = compile_to_ir(SOURCE, directory=str(_project(tmp_path)))
    assert _instrumented(program, "library_sum") and _instrumented(program, "other_sum")
    assert _mapped(program) == ["deps/library/library.hpp", "deps2/other.hpp", "test.cpp"]


@pytest.mark.parametrize("spelling", ["relative", "relative with slash", "absolute", "absolute through a link"])
def test_excluded_directory_is_neither_instrumented_nor_mapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    real = _project(tmp_path / "storage" / "project")
    link = tmp_path / "home_project"
    link.symlink_to(real)
    entry = {
        "relative": "deps",
        "relative with slash": "./deps/",
        "absolute": str(real / "deps"),
        "absolute through a link": str(link / "deps"),
    }[spelling]
    # an entry that matches nothing and an empty one do no harm
    monkeypatch.setenv("DP_PROJECT_EXCLUDE_DIRS", f"does_not_exist::{entry}")
    program = compile_to_ir(SOURCE, directory=str(real))
    assert not _instrumented(program, "library_sum")
    # "deps" must not exclude its namesake prefix "deps2"
    assert _instrumented(program, "other_sum") and _instrumented(program, "sum")
    assert _mapped(program) == ["deps2/other.hpp", "test.cpp"]


def test_several_excluded_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DP_PROJECT_EXCLUDE_DIRS", "deps/library:deps2")
    program = compile_to_ir(SOURCE, directory=str(_project(tmp_path)))
    assert not _instrumented(program, "library_sum") and not _instrumented(program, "other_sum")
    assert _mapped(program) == ["test.cpp"]
