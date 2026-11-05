# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for line-ending preservation in the generated patches.

The code generator emits LF-only text. Diffing that against a CRLF source used to
report the whole file as rewritten, and ``patch`` then rejected every such patch with
"different line endings" -- so no suggestion for a CRLF file was ever applicable.
"""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.diffs import (
    CRLF,
    LF,
    apply_line_terminator,
    detect_line_terminator,
    get_diffs_from_modified_code,
)

ORIGINAL_LINES = ["int main() {", "  int i = 0;", "  return i;", "}", ""]
MODIFIED_LINES = ["int main() {", "  int i = 0;", "  // added", "  return i;", "}", ""]


def _arguments() -> PatchGeneratorArguments:
    """A stand-in for the real arguments, which validate compiler paths on creation.

    ``get_diffs_from_modified_code`` only reads ``verbose``.
    """
    return cast(PatchGeneratorArguments, SimpleNamespace(verbose=False))


def test_detect_crlf_and_lf(tmp_path: Path) -> None:
    crlf_file = tmp_path / "crlf.c"
    with open(crlf_file, "w", newline="") as f:
        f.write(CRLF.join(ORIGINAL_LINES))
    lf_file = tmp_path / "lf.c"
    with open(lf_file, "w", newline="") as f:
        f.write(LF.join(ORIGINAL_LINES))

    assert detect_line_terminator(crlf_file) == CRLF
    assert detect_line_terminator(lf_file) == LF


def test_detect_returns_none_without_any_line_break(tmp_path: Path) -> None:
    single = tmp_path / "single.c"
    with open(single, "w", newline="") as f:
        f.write("int main() { return 0; }")
    assert detect_line_terminator(single) is None


def test_apply_line_terminator_is_idempotent() -> None:
    text = "a\nb\n"
    once = apply_line_terminator(text, CRLF)
    assert once == "a\r\nb\r\n"
    assert apply_line_terminator(once, CRLF) == once
    assert apply_line_terminator(once, LF) == text


def _generate_patch(tmp_path: Path, terminator: str) -> str:
    source = tmp_path / "main.c"
    with open(source, "w", newline="") as f:
        f.write(terminator.join(ORIGINAL_LINES))
    patches = get_diffs_from_modified_code(
        {1: source},
        {1: LF.join(MODIFIED_LINES)},  # the code generator always emits LF
        _arguments(),
    )
    return patches[1]


def test_patch_for_a_crlf_source_is_minimal_and_applies(tmp_path: Path) -> None:
    patch_text = _generate_patch(tmp_path, CRLF)

    # minimal: one added line, not a whole-file rewrite
    added = [ln for ln in patch_text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in patch_text.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    assert len(added) == 1 and removed == []

    patch_file = tmp_path / "1.patch"
    with open(patch_file, "w", newline="") as f:
        f.write(patch_text)
    applied = subprocess.run(
        ["patch", (tmp_path / "main.c").as_posix(), patch_file.as_posix()],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert applied.returncode == 0, applied.stdout.decode() + applied.stderr.decode()

    # the CRLF line endings survive the round trip
    with open(tmp_path / "main.c", "rb") as fb:
        patched = fb.read()
    assert b"\r\n" in patched
    assert patched.count(b"\n") == patched.count(b"\r\n")
    assert b"// added" in patched


def test_patch_for_an_lf_source_still_applies(tmp_path: Path) -> None:
    patch_text = _generate_patch(tmp_path, LF)
    assert "\r" not in patch_text

    patch_file = tmp_path / "1.patch"
    with open(patch_file, "w", newline="") as f:
        f.write(patch_text)
    applied = subprocess.run(
        ["patch", (tmp_path / "main.c").as_posix(), patch_file.as_posix()],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert applied.returncode == 0, applied.stdout.decode() + applied.stderr.decode()
    with open(tmp_path / "main.c", "rb") as fb:
        assert b"\r\n" not in fb.read()


def test_non_utf8_source_yields_applicable_patch(tmp_path: Path) -> None:
    """a Latin-1 byte in a context line (rodinia's avilib.c) must survive the patch round trip.

    The sources are not necessarily UTF-8. The patch has to quote such a line byte for byte,
    or ``patch`` cannot find its context and the suggestion is unapplicable.
    """
    original_bytes = b"/* Thomas \xd6streich */\nint main() {\n  return 0;\n}\n"
    source = tmp_path / "avilib.c"
    source.write_bytes(original_bytes)

    # what ContentBuffer produces: the source read back with undecodable bytes preserved
    with open(source, "r", encoding="utf-8", errors="surrogateescape") as f:
        code = f.read().replace("  return 0;", "  // added\n  return 0;")

    patches = get_diffs_from_modified_code({1: source}, {1: code}, _arguments())
    patch_bytes = patches[1].encode("utf-8", errors="surrogateescape")
    assert b"\xd6streich" in patch_bytes  # context line quoted verbatim, no U+FFFD

    patch_file = tmp_path / "1.patch"
    patch_file.write_bytes(patch_bytes)
    subprocess.run(["patch", "-p0", source.as_posix(), patch_file.as_posix()], check=True, capture_output=True)
    assert source.read_bytes() == original_bytes.replace(b"  return 0;", b"  // added\n  return 0;")
