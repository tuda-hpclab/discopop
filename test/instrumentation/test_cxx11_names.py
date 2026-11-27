# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Functions whose mangled name contains the libstdc++ ABI tag ``__cxx11`` (any signature with a std::string or a
std::list) are project code like any other. The filter of the C++ helpers (``__cxx_global_var_init``, ``__cxa_*``)
used to match the prefix ``__cx`` and left them uninstrumented."""

from pathlib import Path

from .utilities import compile_to_ir

SOURCE = """\
#include <string>

int length(const std::string& text) {
  int count = 0;
  for (char c : text) {
    count += c != ' ';
  }
  return count;
}

int main() { return length("a b") == 2 ? 0 : 1; }
"""


def test_a_function_with_a_std_string_parameter_is_instrumented(tmp_path: Path) -> None:
    program = compile_to_ir(SOURCE, directory=str(tmp_path))
    functions = [function for function in program.user_functions() if function.startswith("_Z6length")]
    assert len(functions) == 1, program.user_functions()
    counts = program.callback_counts(function=functions[0])
    assert counts.get("__dp_func_entry") == 1, program.describe()
    assert counts.get("__dp_loop_entry", 0) >= 1, program.describe()
