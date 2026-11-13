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


@pytest.mark.parametrize("root", ["deps/", "deps"])
def test_the_project_root_does_not_match_its_namesake_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    # the pass tests whether a path contains the root: "<project>/deps" must not take in "<project>/deps2"
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    project = _project(tmp_path)
    program = compile_to_ir(SOURCE, directory=str(project), project_root=str(project / root))

    def has_callbacks(part: str) -> bool:
        # main lies outside of the root here, so __dp_func_entry is not there to look for
        return sum(program.callback_counts(function=_function(program, part)).values()) > 0

    assert has_callbacks("library_sum")
    assert not has_callbacks("other_sum") and not has_callbacks("sum")
    assert _mapped(program) == ["deps/library/library.hpp"]


# DP_PROJECT_INCLUDE_DIRS: directories outside of the project root whose code is project code

OUTSIDE_SOURCE = """\
#include "outside/include/vendored.hpp"
#include "outside/include/skipped/skipped.hpp"

int main() {
  int values[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  return vendored_sum(values, 8) + skipped_sum(values, 8) == 72 ? 0 : 1;
}
"""


def _outside_project(base: Path) -> tuple[Path, Path]:
    """A project and a sibling directory with headers that the project includes ("outside" is found through -I)."""
    project = base / "project"
    outside = base / "outside" / "include"
    (outside / "skipped").mkdir(parents=True)
    project.mkdir()
    (outside / "vendored.hpp").write_text(LIBRARY.replace("library_sum", "vendored_sum"))
    (outside / "skipped" / "skipped.hpp").write_text(OTHER.replace("other_sum", "skipped_sum"))
    return project, outside


def _compile_outside(project: Path, base: Path) -> InstrumentedProgram:
    return compile_to_ir(OUTSIDE_SOURCE, directory=str(project), extra_arguments=[f"-I{base}"])


def _mapped_names(program: InstrumentedProgram) -> list[str]:
    return sorted(os.path.basename(path) for path in program.file_mapping.values())


def test_without_inclusion_a_directory_outside_the_project_is_no_project_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DP_PROJECT_INCLUDE_DIRS", raising=False)
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    project, _ = _outside_project(tmp_path)
    program = _compile_outside(project, tmp_path)
    assert _mapped_names(program) == ["test.cpp"]
    assert program.callback_counts(function=_function(program, "vendored_sum")) == {}


@pytest.mark.parametrize("spelling", ["absolute", "relative", "through a link"])
def test_included_directory_outside_the_project_is_instrumented_and_mapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    project, outside = _outside_project(tmp_path)
    link = tmp_path / "link_to_outside"
    link.symlink_to(outside.parent)
    entry = {
        "absolute": str(outside),
        "relative": "../outside/include",
        # the header is found by its real path, the variable names the directory through a link
        "through a link": str(link / "include"),
    }[spelling]
    # an entry that matches nothing and an empty one do no harm
    monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", f"does_not_exist::{entry}")
    program = compile_to_ir(OUTSIDE_SOURCE, directory=str(project), extra_arguments=[f"-I{tmp_path}"])
    assert _instrumented(program, "vendored_sum") and _instrumented(program, "skipped_sum")
    assert _mapped_names(program) == [
        "skipped.hpp",
        "test.cpp",
        "vendored.hpp",
    ]


def test_included_directory_does_not_match_its_namesake_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    project, outside = _outside_project(tmp_path)
    # "outside/include/skipped" is included, "outside/include/skipped2" would not be
    monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", str(outside / "skipped"))
    program = _compile_outside(project, tmp_path)
    assert _mapped_names(program) == ["skipped.hpp", "test.cpp"]
    # a project of its own: FileMapping.txt keeps the files of the first run
    other_project = tmp_path / "other_project"
    other_project.mkdir()
    monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", str(outside / "skip"))
    program = _compile_outside(other_project, tmp_path)
    assert _mapped_names(program) == ["test.cpp"]


@pytest.mark.parametrize("spelling", ["absolute", "through a link"])
def test_excluded_directory_below_an_included_one_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    project, outside = _outside_project(tmp_path)
    link = tmp_path / "link_to_outside"
    link.symlink_to(outside.parent)
    monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", str(outside))
    monkeypatch.setenv(
        "DP_PROJECT_EXCLUDE_DIRS", str(outside / "skipped" if spelling == "absolute" else link / "include" / "skipped")
    )
    program = _compile_outside(project, tmp_path)
    assert _instrumented(program, "vendored_sum")
    assert program.callback_counts(function=_function(program, "skipped_sum")) == {}
    assert _mapped_names(program) == ["test.cpp", "vendored.hpp"]


def test_relative_exclusion_stays_relative_to_the_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ "skipped" names <project>/skipped, not the directory of that name below an included one."""
    project, outside = _outside_project(tmp_path)
    monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", str(outside))
    monkeypatch.setenv("DP_PROJECT_EXCLUDE_DIRS", "skipped")
    program = _compile_outside(project, tmp_path)
    assert _mapped_names(program) == ["skipped.hpp", "test.cpp", "vendored.hpp"]
