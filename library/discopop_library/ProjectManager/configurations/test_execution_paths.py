# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which files ``execute_configuration`` runs when the project is executed in a copy of itself.

The paths of the configuration, the settings and the script are given below the project root and have to be
moved into the copy; a run of the original's script instead would measure the unmodified code.
"""

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration


def _write_project(project_root: Path, marker: str) -> None:
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    with open(config_dir / "seq_settings.json", "w") as f:
        json.dump({"CC": "clang", "CXX": "clang++"}, f)
    script = config_dir / "tiny" / "execute.sh"
    script.write_text("#!/bin/bash\necho " + marker + "\n")
    os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)


def _arguments(project_root: str) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=project_root,
        full_execute=False,
        list=False,
        execute_configurations="tiny",
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


def _run_in_copy(arguments: ProjectManagerArguments, copy_root: Path) -> str:
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    result = execute_configuration(
        arguments,
        str(copy_root),
        config_path,
        os.path.join(arguments.project_config_dir, "seq_settings.json"),
        os.path.join(config_path, "execute.sh"),
        1,
        None,
    )
    assert result is not None
    assert result[0] == 0, result[3]
    return result[2].strip()


@pytest.mark.parametrize("project_name", ["project", "pro.ject", "v1.2.3"])
@pytest.mark.parametrize("relative", [False, True], ids=["absolute_root", "relative_root"])
def test_the_script_of_the_copy_is_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_name: str, relative: bool
) -> None:
    project_root = tmp_path / project_name
    _write_project(project_root, "original")
    copy_root = tmp_path / "copies" / project_name
    shutil.copytree(project_root, copy_root)
    (copy_root / ".discopop" / "project" / "configs" / "tiny" / "execute.sh").write_text("#!/bin/bash\necho copy\n")

    if relative:
        # as "discopop_project_manager --project ." does
        monkeypatch.chdir(project_root)
        arguments = _arguments(".")
    else:
        arguments = _arguments(str(project_root))

    assert _run_in_copy(arguments, copy_root) == "copy"
    # the result is recorded in the project, not in the copy
    assert os.path.isfile(project_root / ".discopop" / "project" / "execution_results.json")


def test_a_relative_project_root_is_made_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_project(tmp_path / "project", "original")
    monkeypatch.chdir(tmp_path)

    arguments = _arguments("project")

    assert arguments.project_root == str(tmp_path / "project")
    assert arguments.dot_dp == str(tmp_path / "project" / ".discopop")
    assert arguments.project_config_dir == str(tmp_path / "project" / ".discopop" / "project" / "configs")
