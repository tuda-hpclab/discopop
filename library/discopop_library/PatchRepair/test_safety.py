# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for what a repair run must never leave behind in patch_generator/.

A repair rewrites files the patch generator and the patch applicator both depend on, so
these pin the cases where getting it wrong would silently break something else: a
candidate that stays on disk although it was rejected, a restore that brings back an
older generation of patches, a repair of a suggestion that is currently applied, and a
compile check that quietly skips a candidate.
"""

import json
import os
from pathlib import Path
from typing import Any, List

import pytest

from discopop_library.PatchRepair import compilation
from discopop_library.PatchRepair import loop as repair_loop
from discopop_library.PatchRepair import repair
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.PatchRepair.backups import backup_patch_set, record_written_patch_set, restore_patch_sets
from discopop_library.PatchRepair.compilation import CompileCheckError, CompileOutcome, CompileReport
from discopop_library.PatchRepair.patching import match_line_terminator
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet

SUGGESTION_ID = 3
ORIGINAL = "--- a/x.cpp\n+++ b/x.cpp\n@@ -1 +1,2 @@\n+#pragma omp parallel for\n int x;\n"
CANDIDATE = "--- a/x.cpp\n+++ b/x.cpp\n@@ -1 +1,2 @@\n+#pragma omp parallel for private(i)\n int x;\n"


def _arguments(tmp_path: Path, dry_run: bool = False) -> PatchRepairArguments:
    """Arguments pointing into ``tmp_path``, without the project __post_init__ checks for."""
    arguments = PatchRepairArguments.__new__(PatchRepairArguments)
    arguments.dot_dp_path = str(tmp_path)
    arguments.configuration = "tiny"
    arguments.hotspot_types = "yes,maybe"
    arguments.thread_count = 1
    arguments.log_level = "WARNING"
    arguments.dry_run = dry_run
    arguments.restore = False
    arguments.patch_generator_path = str(tmp_path / "patch_generator")
    arguments.patch_repair_path = str(tmp_path / "patch_repair")
    return arguments


def _write_generated(arguments: PatchRepairArguments, text: str) -> Path:
    directory = Path(arguments.patch_generator_path) / str(SUGGESTION_ID)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "0.patch"
    path.write_text(text)
    return path


def _patch_set(text: str, target: Path) -> PatchSet:
    patch_set = PatchSet(suggestion_id=SUGGESTION_ID)
    patch_set.entries[0] = PatchEntry(file_id=0, text=text, target=target)
    return patch_set


# -- the verification build ------------------------------------------------------------


def _verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: Any, dry_run: bool = False) -> Path:
    arguments = _arguments(tmp_path, dry_run=dry_run)
    patch_file = _write_generated(arguments, ORIGINAL)
    monkeypatch.setattr(repair_loop, "run_compile_check", check)
    original = _patch_set(ORIGINAL, tmp_path / "x.cpp")
    repair_loop._verify_by_building(arguments, original, _patch_set(CANDIDATE, tmp_path / "x.cpp"))
    return patch_file


def _built(built: bool) -> Any:
    def check(arguments: Any, ids: List[int]) -> CompileReport:
        # the candidate must be what is on disk while the tuner builds
        assert "private(i)" in (Path(arguments.patch_generator_path) / str(SUGGESTION_ID) / "0.patch").read_text()
        report = CompileReport(reference_built=True)
        report.outcomes[SUGGESTION_ID] = CompileOutcome(suggestion_id=SUGGESTION_ID, built=built)
        return report

    return check


def test_a_candidate_that_builds_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _verify(tmp_path, monkeypatch, _built(True)).read_text() == CANDIDATE


def test_a_candidate_that_does_not_build_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _verify(tmp_path, monkeypatch, _built(False)).read_text() == ORIGINAL


def test_a_dry_run_never_keeps_a_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _verify(tmp_path, monkeypatch, _built(True), dry_run=True).read_text() == ORIGINAL


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt(), json.JSONDecodeError("partial", "{", 1), OSError("disk"), CompileCheckError("x")]
)
def test_a_candidate_is_removed_whatever_interrupts_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    def check(arguments: Any, ids: List[int]) -> CompileReport:
        raise error

    arguments = _arguments(tmp_path)
    patch_file = _write_generated(arguments, ORIGINAL)
    monkeypatch.setattr(repair_loop, "run_compile_check", check)
    original = _patch_set(ORIGINAL, tmp_path / "x.cpp")
    with pytest.raises(type(error)):
        repair_loop._verify_by_building(arguments, original, _patch_set(CANDIDATE, tmp_path / "x.cpp"))
    assert patch_file.read_text() == ORIGINAL


def test_undoing_a_candidate_restores_files_a_patch_set_does_not_carry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A patch for a file id the mapping does not know is not in the PatchSet, but stays."""
    arguments = _arguments(tmp_path)
    _write_generated(arguments, ORIGINAL)
    unknown = Path(arguments.patch_generator_path) / str(SUGGESTION_ID) / "99.patch"
    unknown.write_text("kept\r\n")
    monkeypatch.setattr(repair_loop, "run_compile_check", _built(False))
    original = _patch_set(ORIGINAL, tmp_path / "x.cpp")
    repair_loop._verify_by_building(arguments, original, _patch_set(CANDIDATE, tmp_path / "x.cpp"))
    assert unknown.read_bytes() == b"kept\r\n"


# -- backups ---------------------------------------------------------------------------


def test_a_second_repair_keeps_the_pristine_backup(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    patch_file = _write_generated(arguments, ORIGINAL)
    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)
    patch_file.write_text(CANDIDATE)  # the repair's accepted result
    record_written_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)

    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)

    assert restore_patch_sets(arguments.patch_repair_path, arguments.patch_generator_path) == [SUGGESTION_ID]
    assert patch_file.read_text() == ORIGINAL


def test_regenerated_patches_replace_the_old_backup(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    patch_file = _write_generated(arguments, ORIGINAL)
    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)
    regenerated = ORIGINAL.replace("int x;", "int y;")
    patch_file.write_text(regenerated)  # gather_data / the patch generator ran again

    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)
    patch_file.write_text(CANDIDATE)
    record_written_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)

    restore_patch_sets(arguments.patch_repair_path, arguments.patch_generator_path)
    assert patch_file.read_text() == regenerated


def test_restore_leaves_regenerated_patches_alone(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    patch_file = _write_generated(arguments, ORIGINAL)
    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)
    patch_file.write_text(CANDIDATE)
    record_written_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, SUGGESTION_ID)
    regenerated = ORIGINAL.replace("int x;", "int y;")
    patch_file.write_text(regenerated)

    assert restore_patch_sets(arguments.patch_repair_path, arguments.patch_generator_path) == []
    assert patch_file.read_text() == regenerated
    # and the stale backup is gone, so a later restore cannot bring it back either
    assert restore_patch_sets(arguments.patch_repair_path, arguments.patch_generator_path) == []


# -- applied suggestions ---------------------------------------------------------------


@pytest.mark.parametrize("restore", [False, True])
def test_nothing_is_touched_while_a_suggestion_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore: bool
) -> None:
    arguments = _arguments(tmp_path)
    arguments.restore = restore
    applicator = tmp_path / "patch_applicator"
    applicator.mkdir()
    (applicator / "applied_suggestions.json").write_text(json.dumps({"applied": [SUGGESTION_ID]}))
    monkeypatch.setattr(repair, "setup_patch_repair", lambda path: None)

    def must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the repair must stop before touching any patch")

    monkeypatch.setattr(repair, "restore_patch_sets", must_not_run)
    monkeypatch.setattr(repair, "_run", must_not_run)

    assert repair.run(arguments) == repair.EXIT_ERROR


# -- the compile check -----------------------------------------------------------------


def test_a_restricted_compile_check_does_not_filter_by_hotspot_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit ids (e.g. a 'no' suggestion named via --suggestions) must all be built."""
    arguments = _arguments(tmp_path)
    commands: List[List[str]] = []

    def fake_run(command: List[str], **kwargs: Any) -> Any:
        commands.append(command)
        os.makedirs(tmp_path / "auto_tuner", exist_ok=True)
        with open(tmp_path / "auto_tuner" / compilation.COMPILE_RESULTS_FILE, "w") as f:
            json.dump({"reference_built": True, "built": [[SUGGESTION_ID]], "failed": [], "not_applied": []}, f)

        class Completed:
            returncode = 0
            stdout = ""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    report = compilation.run_compile_check(arguments, [SUGGESTION_ID])

    command = commands[0]
    assert command[command.index("-ht") + 1] == compilation.ALL_HOTSPOT_TYPES
    assert command[command.index("--search-space") + 1] == str(SUGGESTION_ID)
    assert report.building() == [SUGGESTION_ID]


def test_a_partially_written_compile_result_is_a_failed_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments = _arguments(tmp_path)

    def fake_run(command: List[str], **kwargs: Any) -> Any:
        os.makedirs(tmp_path / "auto_tuner", exist_ok=True)
        (tmp_path / "auto_tuner" / compilation.COMPILE_RESULTS_FILE).write_text('{"built": [[')

        class Completed:
            returncode = 1
            stdout = ""

        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(CompileCheckError):
        compilation.run_compile_check(arguments, [SUGGESTION_ID])


# -- line terminators ------------------------------------------------------------------


def test_content_lines_that_look_like_diff_headers_keep_crlf(tmp_path: Path) -> None:
    target = tmp_path / "crlf.cpp"
    target.write_bytes(b"int main() {\r\n  --i;\r\n  return 0;\r\n}\r\n")
    diff = (
        "--- a/crlf.cpp\n"
        "+++ b/crlf.cpp\n"
        "@@ -1,4 +1,4 @@\n"
        " int main() {\n"
        "---i;\n"
        "+++count;\n"
        "   return 0;\n"
        " }\n"
    )

    lines = match_line_terminator(diff, target).splitlines(keepends=True)

    assert lines[0] == "--- a/crlf.cpp\n"
    assert lines[1] == "+++ b/crlf.cpp\n"
    assert lines[2] == "@@ -1,4 +1,4 @@\n"
    assert lines[4] == "---i;\r\n"
    assert lines[5] == "+++count;\r\n"


def test_a_second_file_header_stays_framing(tmp_path: Path) -> None:
    target = tmp_path / "crlf.cpp"
    target.write_bytes(b"a\r\n")
    diff = (
        "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n--- a/g\n+++ b/g\n@@ -1 +1 @@\n-c\n+d\n\\ No newline at end of file\n"
    )

    lines = match_line_terminator(diff, target).splitlines(keepends=True)

    assert [line.endswith("\r\n") for line in lines] == [
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        True,
        True,
        False,
    ]
