# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

from discopop_library.ProjectManager.services.copy_exclude import (
    copy_exclude_path,
    load_copy_exclude,
    save_copy_exclude,
)


def test_missing_or_broken_file_gives_an_empty_list(tmp_path: Path) -> None:
    assert load_copy_exclude(str(tmp_path)) == []
    Path(copy_exclude_path(str(tmp_path))).write_text("{not json")
    assert load_copy_exclude(str(tmp_path)) == []
    Path(copy_exclude_path(str(tmp_path))).write_text('{"copy_exclude": "data"}')
    assert load_copy_exclude(str(tmp_path)) == []


def test_saved_list_is_normalized(tmp_path: Path) -> None:
    stored = save_copy_exclude(
        str(tmp_path), ["data/", "./data/sub", ".git", "../outside", "/abs", ".discopop/profiler", "docs/a.txt"]
    )
    assert stored == [".git", "data", "docs/a.txt"]
    assert load_copy_exclude(str(tmp_path)) == stored
