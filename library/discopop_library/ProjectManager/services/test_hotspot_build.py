# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path

from discopop_library.ProjectManager.services.hotspot_build import (
    BUILD_CURRENT,
    BUILD_MISMATCH,
    BUILD_NONE,
    BUILD_STALE,
    hotspot_build_state,
    newest_source_mtime,
)


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    os.utime(path, (mtime, mtime))


def test_newest_source_mtime_ignores_other_files_and_pruned_directories(tmp_path: Path) -> None:
    assert newest_source_mtime(str(tmp_path)) is None
    _touch(tmp_path / "a.cpp", 100)
    _touch(tmp_path / "sub" / "b.h", 200)
    _touch(tmp_path / "notes.txt", 900)
    _touch(tmp_path / "build" / "gen.cpp", 900)
    _touch(tmp_path / ".hidden" / "c.cpp", 900)
    assert newest_source_mtime(str(tmp_path)) == 200


def test_build_states(tmp_path: Path) -> None:
    cs_id = tmp_path / "cs_id.txt"
    project = tmp_path / "project"
    _touch(project / "main.cpp", 100)
    assert hotspot_build_state(str(cs_id), str(project), lambda: False)[0] == BUILD_NONE
    _touch(cs_id, 200)
    assert hotspot_build_state(str(cs_id), str(project), lambda: False) == (BUILD_CURRENT, "")
    assert hotspot_build_state(str(cs_id), str(project), lambda: True)[0] == BUILD_STALE
    _touch(project / "main.cpp", 300)
    # a changed source wins over a differing compile script
    assert hotspot_build_state(str(cs_id), str(project), lambda: True)[0] == BUILD_MISMATCH
