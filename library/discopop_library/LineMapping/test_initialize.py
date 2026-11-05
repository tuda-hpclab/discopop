# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from pathlib import Path

import pytest

from discopop_library.LineMapping.diff_modifications import apply_line_mapping_modifications_from_files
from discopop_library.LineMapping.initialize import initialize_line_mapping
from discopop_library.LineMapping.load import load_line_mapping


def test_non_utf8_source(tmp_path: Path) -> None:
    """a Latin-1 byte in a comment (rodinia's avilib.c) must not abort the line mapping"""
    source = tmp_path / "avilib.c"
    source.write_bytes(b"/*\n * Copyright (C) Thomas \xd6streich\n */\nint x;\n")
    initialize_line_mapping({1: str(source)}, str(tmp_path))
    assert load_line_mapping(str(tmp_path))["1"] == {"1": 1, "2": 2, "3": 3, "4": 4}
    assert source.read_bytes().count(b"\xd6") == 1  # the source is left untouched


def test_non_utf8_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # the line mapping is read from and written to the working directory
    original = tmp_path / "a.c"
    modified = tmp_path / "b.c"
    original.write_bytes(b"/* \xd6 */\nint x;\n")
    modified.write_bytes(b"/* \xd7 */\nint x;\n")  # the diff quotes the non-UTF-8 line
    initialize_line_mapping({1: str(original)}, str(tmp_path))
    apply_line_mapping_modifications_from_files(1, str(original), str(modified))
    assert load_line_mapping(str(tmp_path))["1"] == {"1": 1, "2": 2}
