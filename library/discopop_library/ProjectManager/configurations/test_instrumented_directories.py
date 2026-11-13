# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""An instrumented build records in DOT_DISCOPOP the project directories its data was instrumented with (the functions
themselves are tested in ``test_project_environment.py``)."""

import json
import os
import stat
from pathlib import Path

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.project_environment import (
    INSTRUMENTED_DIRECTORIES_FILE,
    ProjectDirectories,
    record_instrumented_directories,
)
from discopop_library.ProjectManager.services.excluded_directories import save_excluded_directories

# ---- execute_configuration records it


def _write_project(project_root: Path, settings_name: str, script: str) -> None:
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    (config_dir / settings_name).write_text(json.dumps({"CC": "clang"}))
    save_excluded_directories(str(project_root / ".discopop" / "project"), ["third_party"])
    path = config_dir / "tiny" / "compile.sh"
    path.write_text(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def _compile(project_root: Path, settings_name: str) -> int:
    arguments = ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
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
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    result = execute_configuration(
        arguments,
        str(project_root),
        config_path,
        os.path.join(arguments.project_config_dir, settings_name),
        os.path.join(config_path, "compile.sh"),
        1,
        None,
    )
    assert result is not None
    return result[0]


def test_a_successful_dp_compile_records_the_directories(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "dp_settings.json", "#!/bin/bash\ntrue\n")
    assert _compile(root, "dp_settings.json") == 0
    recorded = json.loads((root / ".discopop" / INSTRUMENTED_DIRECTORIES_FILE).read_text())
    assert recorded == {"dp": {"included": [], "excluded": ["third_party"]}}


def test_a_successful_hd_compile_records_the_directories_next_to_dp(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "hd_settings.json", "#!/bin/bash\ntrue\n")
    record_instrumented_directories(str(root / ".discopop"), "dp", ProjectDirectories())
    assert _compile(root, "hd_settings.json") == 0
    recorded = json.loads((root / ".discopop" / INSTRUMENTED_DIRECTORIES_FILE).read_text())
    assert recorded == {
        "dp": {"included": [], "excluded": []},
        "hd": {"included": [], "excluded": ["third_party"]},
    }


def test_a_seq_compile_records_nothing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "seq_settings.json", "#!/bin/bash\ntrue\n")
    assert _compile(root, "seq_settings.json") == 0
    assert not (root / ".discopop" / INSTRUMENTED_DIRECTORIES_FILE).exists()


def test_a_dp_compile_failing_its_checks_records_nothing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        "dp_settings.json",
        "#!/bin/bash\nmkdir -p sub/.discopop\ntouch sub/.discopop/FileMapping.txt\n",
    )
    assert _compile(root, "dp_settings.json") != 0
    assert not (root / ".discopop" / INSTRUMENTED_DIRECTORIES_FILE).exists()
