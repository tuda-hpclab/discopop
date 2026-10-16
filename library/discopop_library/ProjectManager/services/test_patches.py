# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

from discopop_library.ProjectManager.services.patches import (
    count_patches,
    discover_patches,
    discover_suggestion_ids,
    has_patches,
)


def _make(root: Path, layout: dict) -> str:  # type: ignore[type-arg]
    for suggestion, files in layout.items():
        directory = root / "patch_generator" / suggestion
        directory.mkdir(parents=True)
        for name in files:
            (directory / name).write_text("")
    return str(root)


def test_no_patch_generator_directory(tmp_path: Path) -> None:
    assert discover_patches(str(tmp_path)) == {}
    assert not has_patches(str(tmp_path))
    assert count_patches(str(tmp_path)) == 0


def test_ids_are_ordered_numerically_and_empty_ones_are_skipped(tmp_path: Path) -> None:
    root = _make(tmp_path, {"10": ["b.patch", "a.patch"], "2": ["x.patch", "notes.txt"], "3": ["readme.txt"], "4": []})
    assert discover_patches(root) == {"2": ["x.patch"], "10": ["a.patch", "b.patch"]}
    assert discover_suggestion_ids(root) == ["2", "10"]
    assert count_patches(root) == 3
    assert has_patches(root)


def test_non_numeric_names_do_not_break_the_ordering(tmp_path: Path) -> None:
    root = _make(tmp_path, {"7": ["a.patch"], "backup": ["a.patch"], "1": ["a.patch"]})
    assert discover_suggestion_ids(root) == ["1", "7", "backup"]
