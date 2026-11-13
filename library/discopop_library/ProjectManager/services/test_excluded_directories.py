# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

import pytest

from discopop_library.ProjectManager.services import excluded_directories as ed


@pytest.mark.parametrize(
    "given, stored",
    [
        ("build/_deps", "build/_deps"),
        ("./build/_deps/", "build/_deps"),
        ("build//x/../_deps", "build/_deps"),
        ("", None),
        (".", None),
        ("/abs/path", None),
        ("..", None),
        ("../outside", None),
        ("build/../..", None),
    ],
)
def test_normalize(given: str, stored: object) -> None:
    assert ed.normalize(given) == stored


def test_minimal_drops_duplicates_invalid_and_nested_entries() -> None:
    assert ed.minimal(["b", "a/x", "a", "./a/", "", "../c", "ab", "a/y/z"]) == ["a", "ab", "b"]


def test_toggle() -> None:
    assert ed.toggle([], "build/_deps") == ["build/_deps"]
    assert ed.toggle(["build/_deps"], "build/_deps") == []
    # excluding a directory makes the ones below it redundant
    assert ed.toggle(["build/_deps", "build/x", "third_party"], "build") == ["build", "third_party"]
    # excluded through the directory above: cannot be included on its own
    assert ed.toggle(["build"], "build/_deps") == ["build"]
    # a namesake prefix is no parent
    assert ed.toggle(["build"], "build2") == ["build", "build2"]
    assert ed.toggle(["a"], "") == ["a"]


def test_excluding_directory() -> None:
    assert ed.excluding_directory(["build/_deps"], "build/_deps/fmt/include") == "build/_deps"
    assert ed.excluding_directory(["build/_deps"], "build/_deps") == "build/_deps"
    assert ed.excluding_directory(["build/_deps"], "build/_deps2") is None
    assert ed.excluding_directory(["build/_deps"], "build") is None


def test_environment_value_keeps_entries_of_the_settings() -> None:
    assert ed.environment_value(["build/_deps", "third_party"]) == "build/_deps:third_party"
    assert ed.environment_value(["build/_deps"], "/opt/x::build/_deps") == "/opt/x:build/_deps"
    assert ed.environment_value([], "") == ""


def test_environment_value_below_a_root() -> None:
    assert ed.environment_value(["build/_deps", "third_party"], root="/run") == "/run/build/_deps:/run/third_party"
    assert ed.environment_value(["build/_deps"], "/opt/x:/run/build/_deps", root="/run") == "/opt/x:/run/build/_deps"


def test_save_and_load(tmp_path: Path) -> None:
    project_dir = tmp_path / ".discopop" / "project"
    assert ed.load_excluded_directories(str(project_dir)) == []
    stored = ed.save_excluded_directories(str(project_dir), ["third_party", "build/_deps", "build/_deps/fmt"])
    assert stored == ["build/_deps", "third_party"]
    assert ed.load_excluded_directories(str(project_dir)) == stored
    content = json.loads((project_dir / ed.EXCLUDED_DIRECTORIES_FILE).read_text())
    assert content == {"excluded_directories": ["build/_deps", "third_party"]}
    assert not list(project_dir.glob("*.tmp"))


@pytest.mark.parametrize(
    "content", ["not json", "[]", '{"excluded_directories": "build"}', '{"excluded_directories": [1, "ok"]}']
)
def test_load_tolerates_broken_files(tmp_path: Path, content: str) -> None:
    (tmp_path / ed.EXCLUDED_DIRECTORIES_FILE).write_text(content)
    assert ed.load_excluded_directories(str(tmp_path)) == (["ok"] if "ok" in content else [])


def test_subdirectories(tmp_path: Path) -> None:
    for name in ("src", "Build", ".discopop", ".git", "build/_deps/fmt", "build/CMakeFiles"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "file.cpp").write_text("")
    (tmp_path / "link").symlink_to(tmp_path / "src")
    assert ed.subdirectories(str(tmp_path)) == ["Build", "build", "link", "src"]
    assert ed.subdirectories(str(tmp_path), "build") == ["build/_deps", "build/CMakeFiles"]
    assert ed.subdirectories(str(tmp_path), "does/not/exist") == []
    assert ed.is_symbolic_link(str(tmp_path), "link") and not ed.is_symbolic_link(str(tmp_path), "src")


def test_relative_entry_and_listed_children(tmp_path: Path) -> None:
    root = str(tmp_path)
    assert ed.relative_entry(root, " build/_deps/ ") == "build/_deps"
    assert ed.relative_entry(root, str(tmp_path / "a" / "b")) == "a/b"
    assert ed.relative_entry(root, "/elsewhere") is None and ed.relative_entry(root, "..") is None
    assert ed.listed_children(["build/_deps", "x"]) == ["build", "x"]
    assert ed.listed_children(["build/_deps/lib"], "build") == ["build/_deps"]
    assert ed.listed_children(["build/_deps"], "src") == []
