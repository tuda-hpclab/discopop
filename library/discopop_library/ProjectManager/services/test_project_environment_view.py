# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path
from typing import Tuple

from discopop_library.ProjectManager.services.project_environment_view import (
    build_view,
    project_scripts,
    save_scope,
    stored_scope,
    use_run_root_variable,
)


def make_project(tmp_path: Path) -> Tuple[Path, Path]:
    root = tmp_path / "proj"
    config_dir = root / ".discopop" / "project"
    (config_dir / "cfg").mkdir(parents=True)
    (root / "src").mkdir()
    return root, config_dir


def test_default_scope_view(tmp_path: Path) -> None:
    root, config_dir = make_project(tmp_path)
    (config_dir / "compile.sh").write_text("cmake -S $DP_PROJECT_ROOT_DIR\n")
    view = build_view(str(root), str(config_dir), "")
    assert view.scope == "."
    assert view.project_root_dir == str(root) + os.sep
    assert view.dot_discopop == str(root / ".discopop")
    assert view.warnings == []
    assert view.scripts_using_scope_variable == []  # only listed for a narrowed scope


def test_narrowed_scope_lists_scripts(tmp_path: Path) -> None:
    root, config_dir = make_project(tmp_path)
    (config_dir / "compile.sh").write_text("cmake -S $DP_PROJECT_ROOT_DIR\n")
    (config_dir / "cfg" / "execute.sh").write_text("./a.out\n")
    (config_dir / "cfg" / "validate.sh").write_text("cd ${DP_PROJECT_ROOT_DIR}\n")
    view = build_view(str(root), str(config_dir), "src/")
    assert view.scope == "src"
    assert view.project_root_dir == str(root / "src") + os.sep
    assert view.scripts_using_scope_variable == [
        str(config_dir / "compile.sh"),
        str(config_dir / "cfg" / "validate.sh"),
    ]
    assert project_scripts(str(config_dir)) == [
        str(config_dir / "compile.sh"),
        str(config_dir / "cfg" / "execute.sh"),
        str(config_dir / "cfg" / "validate.sh"),
    ]


def test_missing_and_outside_scope_warn(tmp_path: Path) -> None:
    root, config_dir = make_project(tmp_path)
    assert len(build_view(str(root), str(config_dir), "nope").warnings) == 1
    assert "outside" in build_view(str(root), str(config_dir), str(tmp_path)).warnings[0]


def test_save_and_load(tmp_path: Path) -> None:
    root, config_dir = make_project(tmp_path)
    assert stored_scope(str(config_dir)) == "."
    assert save_scope(str(config_dir), str(root), "./src/") == "src"
    assert stored_scope(str(config_dir)) == "src"


def test_rewrite_only_whole_words(tmp_path: Path) -> None:
    script = tmp_path / "a.sh"
    script.write_text(
        "a=$DP_PROJECT_ROOT_DIR b=${DP_PROJECT_ROOT_DIR}/x c=$DP_PROJECT_ROOT_DIR_X d=MY_DP_PROJECT_ROOT_DIR\n"
    )
    untouched = tmp_path / "b.sh"
    untouched.write_text("echo hi\n")
    assert use_run_root_variable([str(script), str(untouched)]) == [str(script)]
    assert script.read_text() == (
        "a=$DP_RUN_ROOT_DIR b=${DP_RUN_ROOT_DIR}/x c=$DP_PROJECT_ROOT_DIR_X d=MY_DP_PROJECT_ROOT_DIR\n"
    )
