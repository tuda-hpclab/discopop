# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``execute_configuration``: the OpenMP handling of an instrumented compilation (variables, warnings, notes).

The script plays the compiler wrapper: it records an OpenMP flag in ``$DOT_DISCOPOP/openmp_flags_seen.json`` the way
``profiler/scripts/dp_openmp.sh`` does (the wrapper itself is tested in ``test/scripts/test_dp_openmp.py``)."""

import json
import os
import stat
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.services import openmp_handling

SCRIPT = (
    "#!/bin/bash\n"
    "env | grep -E '^DP_(STRIP_OPENMP|OPENMP_QUIET)=' | sort\n"
    'mkdir -p "$DOT_DISCOPOP"\n'
    'if [ "$DP_STRIP_OPENMP" = 1 ]; then s=true; else s=false; fi\n'
    'echo "{\\"flags\\": \\"-fopenmp\\", \\"stripped\\": $s}" > "$DOT_DISCOPOP/openmp_flags_seen.json"\n'
)


def _setup(root: Path, script: str, strip: Optional[bool] = None, stored: bool = False) -> ProjectManagerArguments:
    config_dir = root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    for settings in ("seq_settings.json", "dp_settings.json"):
        (config_dir / settings).write_text(json.dumps({"CC": "clang"}))
    for name in ("compile.sh", "execute.sh"):
        path = config_dir / "tiny" / name
        path.write_text(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    if stored:
        openmp_handling.save_openmp_handling(
            str(root / ".discopop" / "project"), openmp_handling.OpenMPHandling(strip=True)
        )
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
        strip_openmp=strip,
    )


def _run(arguments: ProjectManagerArguments, root: Path, script: str, settings: str) -> Tuple[str, str]:
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    result = execute_configuration(
        arguments,
        str(root),
        config_path,
        os.path.join(arguments.project_config_dir, settings),
        os.path.join(config_path, script),
        1,
        None,
    )
    assert result is not None
    return result[2], result[3]


def _variables(stdout: str) -> Dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if line.startswith("DP_"))


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in openmp_handling.VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_by_default_the_flags_are_kept_and_the_warning_names_the_settings(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout) == {"DP_OPENMP_QUIET": "1"}
    assert "WARNING: The instrumented compilation kept the OpenMP flags (-fopenmp)" in stderr
    assert "--strip-openmp" in stderr
    assert "Project Setup stage" in stderr and "Remove OpenMP flags" in stderr
    assert "DP_STRIP_OPENMP=1" in stderr


def test_the_stored_setting_removes_the_flags(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, stored=True)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout) == {"DP_OPENMP_QUIET": "1", "DP_STRIP_OPENMP": "1"}
    assert "NOTE: The OpenMP flags (-fopenmp) were removed" in stderr
    assert "kept the OpenMP flags" not in stderr


def test_the_command_line_option_overrides_the_stored_setting(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, strip=False, stored=True)
    stdout, _stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert "DP_STRIP_OPENMP" not in _variables(stdout)
    arguments.strip_openmp = True
    stdout, _stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout)["DP_STRIP_OPENMP"] == "1"


def test_variables_of_the_environment_are_ignored_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DP_STRIP_OPENMP", "1")
    arguments = _setup(tmp_path, SCRIPT)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert "DP_STRIP_OPENMP" not in _variables(stdout)
    assert "DP_STRIP_OPENMP set in the environment or the settings file is ignored" in stderr


def test_a_stale_sighting_of_an_earlier_compilation_is_forgotten(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, "#!/bin/bash\ntrue\n")
    dot_discopop = tmp_path / ".discopop"
    (dot_discopop).mkdir(exist_ok=True)
    (dot_discopop / "openmp_flags_seen.json").write_text('{"flags": "-fopenmp", "stripped": false}')
    _stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert "OpenMP" not in stderr


def test_other_modes_are_not_touched(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, stored=True)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "seq_settings.json")
    assert _variables(stdout) == {}
    assert "OpenMP" not in stderr


def test_the_state_of_the_data_is_recorded_and_compared(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, stored=True)
    _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert openmp_handling.recorded_state(arguments.dot_dp, "dp") is True
    assert openmp_handling.stale_message(arguments) is None
    openmp_handling.save_openmp_handling(arguments.project_dir, openmp_handling.OpenMPHandling(strip=False))
    message = openmp_handling.stale_message(arguments)
    assert message is not None and "removed" in message and "keep" in message
