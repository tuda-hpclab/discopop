# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for reading a compiler's complaints and mapping them back to file ids.

The paths in a diagnostic name a project copy that has since been deleted, and they
come in two shapes depending on how the project builds, so matching them is the whole
problem here.
"""

from pathlib import Path
from typing import Dict

from discopop_library.PatchRepair.diagnostics import (
    first_error,
    implicated_file_ids,
    parse_diagnostics,
    resolve_file_id,
    truncate_diagnostics,
)

MAPPING: Dict[int, Path] = {
    1: Path("/home/user/project/example.cpp"),
    2: Path("/home/user/project/src/kernel.cpp"),
    3: Path("/home/user/project/other/kernel.cpp"),
}

CLANG_OUTPUT = """example.cpp:24:69: error: use of undeclared identifier 'does_not_exist'
   24 |   #pragma omp parallel for reduction(+:sum) private(does_not_exist)
      |                                                     ^~~~~~~~~~~~~~
1 error generated.
"""


def test_a_relative_path_resolves() -> None:
    """compile.sh runs with the project copy as its cwd, so clang prints 'example.cpp'."""
    assert resolve_file_id("example.cpp", MAPPING) == 1


def test_an_absolute_path_into_a_deleted_copy_resolves() -> None:
    # a CMake build prints the full path inside the copy, which no longer exists
    assert resolve_file_id("/tmp/tiny_par_project_3/src/kernel.cpp", MAPPING) == 2


def test_the_longest_matching_suffix_wins() -> None:
    # two files share a base name; only the directory above them tells them apart
    assert resolve_file_id("/tmp/copy/other/kernel.cpp", MAPPING) == 3
    assert resolve_file_id("/tmp/copy/src/kernel.cpp", MAPPING) == 2


def test_an_ambiguous_path_resolves_to_nothing() -> None:
    """Attributing an error to the wrong file would send the agent to fix working code."""
    assert resolve_file_id("kernel.cpp", MAPPING) is None


def test_an_unknown_path_resolves_to_nothing() -> None:
    assert resolve_file_id("/usr/include/stdio.h", MAPPING) is None
    assert resolve_file_id("", MAPPING) is None


def test_a_leading_dot_segment_does_not_prevent_a_match() -> None:
    assert resolve_file_id("./example.cpp", MAPPING) == 1


def test_clang_output_is_parsed_with_its_file_id() -> None:
    diagnostics = parse_diagnostics(CLANG_OUTPUT, MAPPING)
    errors = [d for d in diagnostics if d.is_error]
    assert len(errors) == 1
    assert errors[0].line == 24
    assert errors[0].column == 69
    assert errors[0].file_id == 1
    assert "does_not_exist" in errors[0].message


def test_gcc_output_is_parsed_too() -> None:
    gcc = "src/kernel.cpp:12:5: error: 'sum' is not a variable in clause 'private'\n"
    diagnostics = parse_diagnostics(gcc, MAPPING)
    assert diagnostics[0].file_id == 2
    assert diagnostics[0].severity == "error"


def test_a_fatal_error_counts_as_an_error() -> None:
    fatal = "example.cpp:1:10: fatal error: 'missing.h' file not found\n"
    assert parse_diagnostics(fatal, MAPPING)[0].is_error


def test_warnings_do_not_implicate_a_file() -> None:
    """Only errors are being repaired, so only errors decide what the prompt shows."""
    text = "src/kernel.cpp:3:1: warning: unused variable\nexample.cpp:24:1: error: broken\n"
    diagnostics = parse_diagnostics(text, MAPPING)
    assert implicated_file_ids(diagnostics) == [1]
    assert implicated_file_ids(diagnostics, errors_only=False) == [2, 1]


def test_files_are_implicated_in_the_order_they_are_first_blamed() -> None:
    # the first error is the causal one far more often than not
    text = "src/kernel.cpp:3:1: error: a\nexample.cpp:24:1: error: b\nsrc/kernel.cpp:9:1: error: c\n"
    assert implicated_file_ids(parse_diagnostics(text, MAPPING)) == [2, 1]


def test_the_first_error_line_is_reported() -> None:
    assert first_error(CLANG_OUTPUT).startswith("example.cpp:24:69: error:")


def test_the_first_error_falls_back_to_any_line_mentioning_one() -> None:
    assert first_error("ld: error: undefined symbol: foo") != ""


def test_no_error_yields_an_empty_summary() -> None:
    assert first_error("") == ""
    assert first_error("everything is fine\n") == ""


def test_truncation_keeps_the_first_errors() -> None:
    """Later errors are usually the same mistake echoing through the translation unit."""
    text = "".join("example.cpp:" + str(n) + ":1: error: number " + str(n) + "\n" for n in range(1, 200))
    truncated = truncate_diagnostics(text, 300)
    assert "number 1" in truncated
    assert "number 199" not in truncated
    assert "omitted" in truncated


def test_truncation_does_not_cut_a_line_in_half() -> None:
    # half a diagnostic reads as a different diagnostic
    text = "example.cpp:1:1: error: a long message that goes on for a while\n" * 5
    truncated = truncate_diagnostics(text, 100)
    body = truncated.split("[...")[0]
    assert body.endswith("\n")


def test_short_output_is_left_alone() -> None:
    assert truncate_diagnostics(CLANG_OUTPUT, 10000) == CLANG_OUTPUT
