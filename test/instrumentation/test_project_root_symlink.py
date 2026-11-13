# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A project reached through a symbolic link is still instrumented as project code.

A checkout is often reached through a symbolic link (``/home/<user>/git -> /mnt/storage/...``), so
``DP_PROJECT_ROOT_DIR`` and the paths in the debug information can name the same directory in two
spellings: the shell's ``$PWD`` keeps the link, ``realpath()`` and ``getcwd()`` resolve it. The
pass decides by the project directory which files get an id in ``FileMapping.txt`` and which
functions it instruments; comparing one spelling with the other lost the whole project: no
``FileMapping.txt``, no file ids, no AST of the project.
"""

import os
from pathlib import Path

import pytest

from .utilities import InstrumentedProgram, compile_to_ir

SOURCE = """\
int sum(int* values, int count) {
  int total = 0;
  for (int i = 0; i < count; ++i) {
    total += values[i];
  }
  return total;
}

int main() {
  int values[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  return sum(values, 8) == 36 ? 0 : 1;
}
"""


@pytest.fixture()
def linked_project(tmp_path: Path) -> tuple[Path, Path]:
    """A project directory (the real one) and a symbolic link to it."""
    real = tmp_path / "storage" / "project"
    real.mkdir(parents=True)
    link = tmp_path / "home_project"
    link.symlink_to(real)
    return real, link


def _sum_function(program: InstrumentedProgram) -> str:
    """The (mangled) name of ``sum`` in the IR."""
    names = [name for name in program.user_functions() if "sum" in name]
    assert len(names) == 1, program.user_functions()
    return names[0]


def _assert_instrumented_as_project_code(program: InstrumentedProgram) -> None:
    mapped = [os.path.basename(path) for path in program.file_mapping.values()]
    assert mapped == ["test.cpp"], f"FileMapping.txt: {program.file_mapping}"
    counts = program.callback_counts(function=_sum_function(program))
    assert counts.get("__dp_func_entry", 0) >= 1, f"sum is not instrumented: {counts}"
    assert program.instruction_locations, "no instruction has a location in a mapped file"


@pytest.mark.parametrize(
    "build_through_link, root_through_link",
    [(True, True), (True, False), (False, True)],
    ids=["build+root via link", "build via link, resolved root", "resolved build, root via link"],
)
def test_project_behind_a_symbolic_link(
    linked_project: tuple[Path, Path], build_through_link: bool, root_through_link: bool
) -> None:
    real, link = linked_project
    directory = link if build_through_link else real
    root = link if root_through_link else real
    program = compile_to_ir(SOURCE, directory=str(directory), project_root=str(root))
    _assert_instrumented_as_project_code(program)


def test_files_outside_the_project_stay_unmapped(linked_project: tuple[Path, Path], tmp_path: Path) -> None:
    """Both spellings of the project directory count, but nothing else does."""
    real, link = linked_project
    other = tmp_path / "elsewhere"
    other.mkdir()
    program = compile_to_ir(SOURCE, directory=str(other), project_root=str(link))
    assert program.file_mapping == {}
    assert program.callback_counts(function=_sum_function(program)).get("__dp_func_entry", 0) == 0
