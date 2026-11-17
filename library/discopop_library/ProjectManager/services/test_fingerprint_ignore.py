# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the patterns that leave files out of the fingerprint of the builds."""

from pathlib import Path

import pytest

from discopop_library.ProjectManager.services.fingerprint_ignore import (
    add_patterns,
    clean,
    is_ignored,
    load_fingerprint_ignore,
    normalize,
    save_fingerprint_ignore,
    suggest_patterns,
)


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("dp_build/", "dp_build/"),
        (" ./dp_build// ", "dp_build/"),
        ("a/../b", "b"),
        ("*.log", "*.log"),
        ("", None),
        ("/abs", None),
        ("../outside", None),
        (".", None),
    ],
)
def test_normalize(pattern: str, expected: object) -> None:
    assert normalize(pattern) == expected


@pytest.mark.parametrize(
    "path, pattern, ignored",
    [
        ("dp_build/CMakeCache.txt", "dp_build/", True),
        ("dp_build/_deps/fmt/a.h", "dp_build", True),
        ("dp_build", "dp_build/", True),
        ("dp_builder/a", "dp_build/", False),
        ("src/dp_build/a", "dp_build/", False),
        ("a.log", "*.log", True),
        ("deep/dir/a.log", "*.log", True),
        ("deep/dir/a.c", "*.log", False),
        ("docs/a.md", "docs/*.md", True),
        ("src/docs/a.md", "docs/*.md", False),
        ("build-x/a/b.o", "build-*/", True),
        ("x/build-1/b.o", "build-*", True),
    ],
)
def test_matches(path: str, pattern: str, ignored: bool) -> None:
    normalized = normalize(pattern)
    assert normalized is not None
    assert is_ignored(path, [normalized]) == ignored


def test_store_and_add(tmp_path: Path) -> None:
    assert load_fingerprint_ignore(str(tmp_path)) == []
    assert save_fingerprint_ignore(str(tmp_path), ["dp_build", "/bad", "dp_build", "*.log"]) == ["dp_build", "*.log"]
    assert add_patterns(str(tmp_path), ["out/", "*.log"]) == ["dp_build", "*.log", "out/"]
    assert load_fingerprint_ignore(str(tmp_path)) == ["dp_build", "*.log", "out/"]


def test_an_unreadable_file_ignores_nothing(tmp_path: Path) -> None:
    (tmp_path / "fingerprint_ignore.json").write_text("{not json")
    assert load_fingerprint_ignore(str(tmp_path)) == []


def test_suggestions_are_the_top_level_entries() -> None:
    assert suggest_patterns(["dp_build/a", "dp_build/b/c", "notes.txt"]) == ["dp_build/", "notes.txt"]
    assert clean(["a/", "a/"]) == ["a/"]
