# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""Code in the directories of ``DP_LIBRARY_DIRS`` is library code: instrumented for memory accesses only.

The accesses of a library function are reported with the constant instruction id 0 (``kLibraryAccessInstructionId``),
so that the runtime attributes them to the project call site that entered the library. The function itself gets no
entry, exit, loop, call or allocation callbacks, no instruction ids, and no ``__dp_read`` / ``__dp_write`` for the
stack slots it owns. Library files get no entry in ``FileMapping.txt``. Code that lies below the project root (or
below ``DP_PROJECT_INCLUDE_DIRS``) is project code, whatever ``DP_LIBRARY_DIRS`` says.
"""

from pathlib import Path

import pytest

from .utilities import InstrumentedProgram, compile_to_ir

SOURCE = """\
#include "lib.hpp"

int main() {
  int in[4] = {1, 2, 3, 4};
  int out[4];
  lib_copy(in, out, 4);
  return out[3] == 10 ? 0 : 1;
}
"""

# "local" and "i" belong to the library function: their accesses are not instrumented. The read of in[i] and the
# write of out[i] go through pointer parameters and are.
LIBRARY = """\
inline void lib_copy(const int* in, int* out, int count) {
  int local = 0;
  for (int i = 0; i < count; ++i) {
    local += in[i];
    out[i] = local;
  }
}
"""

#: Callbacks a library function must not contain.
FORBIDDEN_CALLBACKS = [
    "__dp_func_entry",
    "__dp_func_exit",
    "__dp_loop_entry",
    "__dp_loop_exit",
    "__dp_loop_incr",
    "__dp_call",
    "__dp_alloca",
]


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """The project directory and a library directory next to it, i.e. outside of the project root."""
    project = tmp_path / "project"
    library = tmp_path / "library"
    project.mkdir()
    library.mkdir()
    (library / "lib.hpp").write_text(LIBRARY)
    return project, library


def _compile(project: Path, library: Path) -> InstrumentedProgram:
    return compile_to_ir(SOURCE, directory=str(project), extra_arguments=["-I", str(library)])


def _function(program: InstrumentedProgram, name: str) -> str:
    names = [function for function in program.user_functions() if name in function]
    assert len(names) == 1, program.user_functions()
    return names[0]


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ["DP_LIBRARY_DIRS", "DP_PROJECT_INCLUDE_DIRS", "DP_PROJECT_EXCLUDE_DIRS"]:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def library_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InstrumentedProgram:
    project, library = _project(tmp_path)
    monkeypatch.setenv("DP_LIBRARY_DIRS", str(library))
    return _compile(project, library)


def test_library_function_has_only_accesses_with_instruction_id_zero(library_program: InstrumentedProgram) -> None:
    function = _function(library_program, "lib_copy")
    counts = library_program.callback_counts(function=function)
    for callback in FORBIDDEN_CALLBACKS:
        assert callback not in counts, library_program.describe()
    assert counts.get("__dp_read", 0) > 0 and counts.get("__dp_write", 0) > 0, library_program.describe()
    for call in library_program.calls(function=function):
        if call.callee in ("__dp_read", "__dp_write"):
            assert call.arg_int(0) == 0, call.text
            assert "dp.md.instr.id" not in call.text
    # no instruction of the function carries an instruction id
    assert all(instruction.instruction_id is None for instruction in library_program.functions[function])


def test_accesses_to_the_locals_of_the_library_function_are_not_instrumented(
    library_program: InstrumentedProgram,
) -> None:
    function = _function(library_program, "lib_copy")
    # the stack slots (the spilled parameters, local, i) are the function's own; what remains is the read of in[i]
    # and the write of out[i]
    assert library_program.callback_counts(function=function).get("__dp_read") == 1, library_program.describe()
    assert library_program.callback_counts(function=function).get("__dp_write") == 1, library_program.describe()


def test_library_file_is_not_mapped(library_program: InstrumentedProgram) -> None:
    names = [Path(path).name for path in library_program.file_mapping.values()]
    assert "test.cpp" in names
    assert "lib.hpp" not in names


def test_the_project_caller_is_instrumented_as_usual(library_program: InstrumentedProgram) -> None:
    main = _function(library_program, "main")
    assert library_program.callback_counts(function=main).get("__dp_func_entry", 0) == 1
    calls = [call for call in library_program.calls(function=main) if "lib_copy" in call.callee]
    assert len(calls) == 1
    assert any(
        call.callee == "__dp_call" and call.index < calls[0].index for call in library_program.calls(function=main)
    ), library_program.describe()


def test_without_library_dirs_the_header_function_is_not_instrumented(tmp_path: Path) -> None:
    project, library = _project(tmp_path)
    program = _compile(project, library)
    assert program.callback_counts(function=_function(program, "lib_copy")) == {}


@pytest.mark.parametrize("inside", ["project root", "included directory"])
def test_library_directory_that_is_project_code_is_instrumented_as_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inside: str
) -> None:
    project, library = _project(tmp_path)
    if inside == "project root":
        # the header moves below the project root
        inner = project / "include"
        inner.mkdir()
        (inner / "lib.hpp").write_text(LIBRARY)
        library = inner
    else:
        monkeypatch.setenv("DP_PROJECT_INCLUDE_DIRS", str(library))
    monkeypatch.setenv("DP_LIBRARY_DIRS", str(library))
    program = _compile(project, library)
    counts = program.callback_counts(function=_function(program, "lib_copy"))
    assert counts.get("__dp_func_entry", 0) > 0, program.describe()
    assert "lib.hpp" in [Path(path).name for path in program.file_mapping.values()]


# Box<int> is an explicit instantiation declared extern: the definition of set() in this translation unit is
# available_externally, only usable for inlining, and the always_inline attribute must survive, or main calls a symbol
# that nothing defines (libstdc++ 13: basic_string::_M_init_local_buf).
EXTERN_TEMPLATE_SOURCE = """\
#include "box.hpp"

int main() {
  Box<int> box;
  box.set(3);
  return box.value == 3 ? 0 : 1;
}
"""

EXTERN_TEMPLATE_LIBRARY = """\
template <typename T> struct Box {
  __attribute__((always_inline)) inline void set(T v) { value = v; }
  T value;
};
extern template struct Box<int>;
"""


def test_always_inline_function_of_an_extern_template_is_still_inlined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, library = _project(tmp_path)
    (library / "box.hpp").write_text(EXTERN_TEMPLATE_LIBRARY)
    monkeypatch.setenv("DP_LIBRARY_DIRS", str(library))
    program = compile_to_ir(EXTERN_TEMPLATE_SOURCE, directory=str(project), extra_arguments=["-I", str(library)])
    main = _function(program, "main")
    assert not [call for call in program.calls(function=main) if "3set" in call.callee], program.describe()
