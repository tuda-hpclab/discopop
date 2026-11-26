# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``execute_configuration``: which scripts get the thread count of the run as ``OMP_NUM_THREADS``."""

import json
import os
import stat
from pathlib import Path
from typing import Dict, Optional

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.services import build_thread_count

SCRIPT = '#!/bin/bash\necho "OMP=${OMP_NUM_THREADS-unset}"\n'
SCRIPTS = ("compile.sh", "compile_incremental.sh", "compile_validate.sh", "execute.sh", "validate.sh")


def _setup(
    root: Path, settings: Optional[Dict[str, str]] = None, override: Optional[bool] = None
) -> ProjectManagerArguments:
    config_dir = root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    (config_dir / "seq_settings.json").write_text(json.dumps(settings or {"CC": "clang"}))
    for name in SCRIPTS:
        path = config_dir / "tiny" / name
        path.write_text(SCRIPT)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
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
        build_thread_count=override,
    )


def _omp(arguments: ProjectManagerArguments, root: Path, script: str) -> str:
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    result = execute_configuration(
        arguments,
        str(root),
        config_path,
        os.path.join(arguments.project_config_dir, "seq_settings.json"),
        os.path.join(config_path, script),
        6,
        None,
    )
    assert result is not None
    return next(line for line in result[2].splitlines() if line.startswith("OMP=")).removeprefix("OMP=")


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)


@pytest.mark.parametrize("script", ["compile.sh", "compile_incremental.sh", "compile_validate.sh"])
def test_compile_scripts_get_no_thread_count_by_default(tmp_path: Path, script: str) -> None:
    assert _omp(_setup(tmp_path), tmp_path, script) == "unset"


@pytest.mark.parametrize("script", ["execute.sh", "validate.sh"])
def test_run_scripts_always_get_the_thread_count(tmp_path: Path, script: str) -> None:
    arguments = _setup(tmp_path)
    assert _omp(arguments, tmp_path, script) == "6"
    arguments.build_thread_count = False
    assert _omp(arguments, tmp_path, script) == "6"


def test_an_inherited_value_is_kept_for_compile_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    arguments = _setup(tmp_path)
    assert _omp(arguments, tmp_path, "compile.sh") == "3"
    assert _omp(arguments, tmp_path, "execute.sh") == "6"


def test_a_value_of_the_settings_file_is_kept_for_compile_scripts(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, {"CC": "clang", "OMP_NUM_THREADS": "2"})
    assert _omp(arguments, tmp_path, "compile.sh") == "2"
    assert _omp(arguments, tmp_path, "execute.sh") == "6"


@pytest.mark.parametrize("script", ["compile.sh", "compile_incremental.sh", "compile_validate.sh"])
def test_the_stored_setting_gives_compile_scripts_the_thread_count(tmp_path: Path, script: str) -> None:
    arguments = _setup(tmp_path)
    build_thread_count.save_build_thread_count(arguments.project_dir, build_thread_count.BuildThreadCount(True))
    assert _omp(arguments, tmp_path, script) == "6"


def test_the_command_line_option_overrides_the_stored_setting(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, override=True)
    assert _omp(arguments, tmp_path, "compile.sh") == "6"
    build_thread_count.save_build_thread_count(arguments.project_dir, build_thread_count.BuildThreadCount(True))
    arguments.build_thread_count = False
    assert _omp(arguments, tmp_path, "compile.sh") == "unset"
