# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for handling a suggestion's patches as one unit.

The applicator rolls back a partial application, so a half-repaired suggestion is a
state the rest of DiscoPoP never has to reason about -- and this module is where that
stays true.
"""

from pathlib import Path
from typing import Dict, List

import pytest

from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet, load_patch_set, write_patch_set


def _make_patch_dir(tmp_path: Path, suggestion_id: int, patches: Dict[int, str]) -> str:
    root = tmp_path / "patch_generator"
    directory = root / str(suggestion_id)
    directory.mkdir(parents=True)
    for file_id, text in patches.items():
        (directory / (str(file_id) + ".patch")).write_text(text)
    return str(root)


def _mapping(tmp_path: Path, file_ids: List[int]) -> Dict[int, Path]:
    mapping = {}
    for file_id in file_ids:
        target = tmp_path / ("f" + str(file_id) + ".cpp")
        target.write_text("int x;\n")
        mapping[file_id] = target
    return mapping


def test_a_patch_set_is_loaded_from_its_directory(tmp_path: Path) -> None:
    root = _make_patch_dir(tmp_path, 7, {1: "patch one\n", 3: "patch three\n"})
    patch_set = load_patch_set(root, 7, _mapping(tmp_path, [1, 3]))
    assert patch_set.file_ids == [1, 3]
    assert patch_set.entries[3].text == "patch three\n"


def test_a_patch_whose_file_is_unknown_is_skipped(tmp_path: Path) -> None:
    """It cannot be applied by the applicator either, so it is already broken."""
    root = _make_patch_dir(tmp_path, 7, {1: "a\n", 99: "b\n"})
    patch_set = load_patch_set(root, 7, _mapping(tmp_path, [1]))
    assert patch_set.file_ids == [1]


def test_non_patch_files_are_ignored(tmp_path: Path) -> None:
    root = _make_patch_dir(tmp_path, 7, {1: "a\n"})
    (Path(root) / "7" / "notes.txt").write_text("ignore me")
    (Path(root) / "7" / "x.patch").write_text("ignore me too")
    assert load_patch_set(root, 7, _mapping(tmp_path, [1])).file_ids == [1]


def test_replacing_a_subset_keeps_the_other_patches(tmp_path: Path) -> None:
    """The agent answers only for the files it changes; the rest must survive intact."""
    mapping = _mapping(tmp_path, [1, 2])
    patch_set = PatchSet(7)
    patch_set.entries[1] = PatchEntry(1, "original one\n", mapping[1])
    patch_set.entries[2] = PatchEntry(2, "original two\n", mapping[2])

    merged = patch_set.with_replacements({2: "repaired two\n"})

    assert merged.entries[1].text == "original one\n"
    assert merged.entries[2].text == "repaired two\n"
    # and the original is not mutated
    assert patch_set.entries[2].text == "original two\n"


def test_replacing_an_unknown_file_is_refused(tmp_path: Path) -> None:
    mapping = _mapping(tmp_path, [1])
    patch_set = PatchSet(7)
    patch_set.entries[1] = PatchEntry(1, "a\n", mapping[1])
    with pytest.raises(KeyError):
        patch_set.with_replacements({9: "b\n"})


def test_changed_files_are_reported(tmp_path: Path) -> None:
    mapping = _mapping(tmp_path, [1, 2])
    original = PatchSet(7)
    original.entries[1] = PatchEntry(1, "a\n", mapping[1])
    original.entries[2] = PatchEntry(2, "b\n", mapping[2])
    candidate = original.with_replacements({2: "b repaired\n"})
    assert candidate.changed_against(original) == [2]


def test_empty_patches_are_dropped(tmp_path: Path) -> None:
    mapping = _mapping(tmp_path, [1, 2])
    patch_set = PatchSet(7)
    patch_set.entries[1] = PatchEntry(1, "a\n", mapping[1])
    patch_set.entries[2] = PatchEntry(2, "   \n", mapping[2])
    assert patch_set.without_empty().file_ids == [1]


def test_writing_a_set_replaces_the_whole_directory(tmp_path: Path) -> None:
    """A patch that is no longer part of the suggestion must not stay behind."""
    root = _make_patch_dir(tmp_path, 7, {1: "old one\n", 2: "old two\n"})
    mapping = _mapping(tmp_path, [1, 2])
    repaired = PatchSet(7)
    repaired.entries[1] = PatchEntry(1, "new one\n", mapping[1])

    write_patch_set(root, repaired)

    directory = Path(root) / "7"
    assert sorted(p.name for p in directory.iterdir()) == ["1.patch"]
    assert (directory / "1.patch").read_text() == "new one\n"


def test_writing_leaves_no_staging_directory_behind(tmp_path: Path) -> None:
    root = _make_patch_dir(tmp_path, 7, {1: "old\n"})
    mapping = _mapping(tmp_path, [1])
    repaired = PatchSet(7)
    repaired.entries[1] = PatchEntry(1, "new\n", mapping[1])

    write_patch_set(root, repaired)

    assert [p.name for p in Path(root).iterdir()] == ["7"]


def test_a_missing_patch_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_patch_set(str(tmp_path / "patch_generator"), 7, {})
