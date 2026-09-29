# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the structured apply result.

The point of the result is that an unapplied suggestion can never be mistaken for an
applied one: a run of the unmodified code must not be attributed to a parallelization
that is not in it.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest

from discopop_library.PatchApplicator.PatchApplicationResult import (
    PatchApplicationResult,
    read_application_result,
    write_application_result,
)
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.apply import apply_patches

ORIGINAL = "int main() {\n  int i = 0;\n  return i;\n}\n"
PATCHED = "int main() {\n  int i = 1;\n  return i;\n}\n"


def _arguments() -> PatchApplicatorArguments:
    return PatchApplicatorArguments(
        verbose=False,
        apply=[],
        rollback=[],
        clear=False,
        load=False,
        list=False,
        log_level="WARNING",
        write_log=False,
    )


@pytest.fixture
def in_tmp_cwd(tmp_path: Path) -> Iterator[Path]:
    """Run inside ``tmp_path``: applying a patch updates ``line_mapping.json`` there."""
    previous = os.getcwd()
    # the applicator updates the line mapping of every patched file; file id 1 is the
    # single source file used by these tests
    with open(tmp_path / "line_mapping.json", "w") as f:
        json.dump({"1": {"1": 1, "2": 2, "3": 3, "4": 4}}, f)
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def _make_project(tmp_path: Path, *, source: str = ORIGINAL) -> Tuple[Dict[int, Path], str, str]:
    """A minimal patch-applicator environment: one source file, one generated patch."""
    source_path = tmp_path / "main.c"
    with open(source_path, "w", newline="") as f:
        f.write(source)

    modified_path = tmp_path / "main.c.modified"
    with open(modified_path, "w", newline="") as f:
        f.write(PATCHED)

    patch_generator_dir = str(tmp_path / "patch_generator")
    os.makedirs(os.path.join(patch_generator_dir, "1"))
    diff = subprocess.run(
        ["diff", "-Naru", source_path.as_posix(), modified_path.as_posix()],
        stdout=subprocess.PIPE,
    ).stdout
    with open(os.path.join(patch_generator_dir, "1", "1.patch"), "wb") as fb:
        fb.write(diff)
    os.remove(modified_path)

    applied_suggestions_file = str(tmp_path / "applied_suggestions.json")
    with open(applied_suggestions_file, "w") as f:
        json.dump({"applied": []}, f)

    return {1: source_path}, applied_suggestions_file, patch_generator_dir


def test_successful_application_reports_every_requested_suggestion(in_tmp_cwd: Path) -> None:
    tmp_path = in_tmp_cwd
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    result = apply_patches(["1"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.applied == ["1"]
    assert result.unapplied == []
    assert result.complete and not result.failure
    assert result.retval == 0
    assert "int i = 1;" in open(file_mapping[1]).read()


def test_rejected_patch_is_reported_as_failed(tmp_path: Path) -> None:
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    # make the target no longer match the patch's context
    with open(file_mapping[1], "w") as f:
        f.write("int main() { return 42; }\n")

    result = apply_patches(["1"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.failed == ["1"]
    assert result.applied == []
    assert result.failure and result.nothing_in_code
    assert result.retval == 1
    # the failure must be visible in the message, naming the affected suggestion
    assert "1" in result.summary()


def test_unknown_suggestion_is_a_failure_not_a_silent_success(tmp_path: Path) -> None:
    """A requested id without a generated patch used to be reported as success."""
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    result = apply_patches(["99"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.unknown == ["99"]
    assert result.failure
    assert result.retval == 1


def test_partial_application_is_reported_as_partial(in_tmp_cwd: Path) -> None:
    tmp_path = in_tmp_cwd
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    result = apply_patches(["1", "99"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.applied == ["1"]
    assert result.unknown == ["99"]
    assert result.failure and not result.nothing_in_code
    assert result.retval == 2


def test_crlf_source_with_lf_patch_is_reported_as_failed(tmp_path: Path) -> None:
    """The backprop case: a CRLF source and an LF patch cannot be combined by patch."""
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    with open(file_mapping[1], "w", newline="") as f:
        f.write(ORIGINAL.replace("\n", "\r\n"))

    result = apply_patches(["1"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.failed == ["1"]
    assert result.retval == 1


def test_already_applied_suggestions_count_as_in_code(tmp_path: Path) -> None:
    file_mapping, applied_file, generator_dir = _make_project(tmp_path)
    with open(applied_file, "w") as f:
        json.dump({"applied": ["1"]}, f)

    result = apply_patches(["1"], file_mapping, _arguments(), applied_file, generator_dir)
    assert result.already_applied == ["1"]
    assert result.in_code == ["1"]
    assert result.complete


def test_result_round_trips_through_the_result_file(tmp_path: Path) -> None:
    result = PatchApplicationResult(requested=["1", "2"], applied=["1"], failed=["2"])
    write_application_result(str(tmp_path), result)
    loaded = read_application_result(str(tmp_path))
    assert loaded is not None
    assert loaded.requested == ["1", "2"]
    assert loaded.applied == ["1"]
    assert loaded.failed == ["2"]
    assert loaded.failure


def test_missing_result_file_reads_as_no_information(tmp_path: Path) -> None:
    assert read_application_result(str(tmp_path)) is None


def test_no_suggestions_requested_is_not_a_failure() -> None:
    result = PatchApplicationResult()
    assert not result.failure
    assert not result.nothing_in_code
    assert result.retval == 0


def test_applying_an_already_applied_patch_fails_instead_of_reversing_it(tmp_path: Any) -> None:
    """patch(1) must neither ask a question nor guess an answer.

    On a reversed or already-applied patch it prompts ("Assume -R? [n]", "Apply
    anyway? [n]"). The applicator runs under the autotuner, the GUI and the MCP server,
    where no terminal is attached, so the prompt is answered by EOF.

    --batch alone is not the fix: it answers that prompt with "Assuming -R" and
    *reverses* the patch, returning 0. Applying an already-applied suggestion would then
    strip the parallelization back out of the code and report success, and every runtime
    measured afterwards would be of unmodified code presented as parallel. --forward
    makes patch skip it and fail, which is the only honest outcome.
    """
    source = tmp_path / "main.c"
    source.write_text("int main() {\n  int x = 0;\n  return x;\n}\n")
    patch_file = tmp_path / "0.patch"
    # a patch with a removal: an add-only patch simply applies twice
    patch_file.write_text(
        "--- a/main.c\n+++ b/main.c\n@@ -1,4 +1,4 @@\n int main() {\n-  int x = 0;\n+  int x = 42;\n   return x;\n }\n"
    )

    def apply_once() -> int:
        return subprocess.run(
            ["patch", "--batch", "--forward", source.as_posix(), patch_file.as_posix()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=15,
        ).returncode

    assert apply_once() == 0
    assert "int x = 42;" in source.read_text()

    # the second application is the case that used to prompt
    assert apply_once() != 0
    # and, crucially, the parallelization-equivalent change is still in the file
    assert "int x = 42;" in source.read_text()
