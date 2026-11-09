# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Every build of the project manager gets the excluded directories of the project as ``DP_PROJECT_EXCLUDE_DIRS``."""

import json
import os
import shutil
from pathlib import Path

import pytest

from discopop_library.ProjectManager.configurations.test_execution_paths import (
    _arguments,
    _run_in_copy,
    _write_project,
)
from discopop_library.ProjectManager.services.excluded_directories import save_excluded_directories


def _project_printing_the_variable(tmp_path: Path, settings_value: str = "") -> Path:
    project_root = tmp_path / "project"
    _write_project(project_root, "unused")
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "tiny" / "execute.sh").write_text('#!/bin/bash\necho "[$DP_PROJECT_EXCLUDE_DIRS]"\n')
    if settings_value:
        settings = json.loads((config_dir / "seq_settings.json").read_text())
        settings["DP_PROJECT_EXCLUDE_DIRS"] = settings_value
        (config_dir / "seq_settings.json").write_text(json.dumps(settings))
    return project_root


@pytest.mark.parametrize(
    "stored, settings_value, expected",
    [
        ([], "", "[]"),
        (["build/_deps", "third_party"], "", "[{copy}/build/_deps:{copy}/third_party]"),
        (["build/_deps"], "/opt/vendor", "[/opt/vendor:{copy}/build/_deps]"),
        ([], "/opt/vendor", "[/opt/vendor]"),
    ],
)
def test_build_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored: list[str], settings_value: str, expected: str
) -> None:
    monkeypatch.delenv("DP_PROJECT_EXCLUDE_DIRS", raising=False)
    project_root = _project_printing_the_variable(tmp_path, settings_value)
    arguments = _arguments(str(project_root))
    if stored:
        save_excluded_directories(arguments.project_dir, stored)
    copy_root = tmp_path / "copy"
    shutil.copytree(project_root, copy_root)
    # absolute paths in the copy: relative entries would be taken relative to DP_PROJECT_ROOT_DIR, the
    # instrumentation scope, which can be a subdirectory of the project
    assert _run_in_copy(arguments, copy_root) == expected.format(copy=os.path.abspath(copy_root))
