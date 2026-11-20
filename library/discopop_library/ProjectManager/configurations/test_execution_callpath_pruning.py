# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``execute_configuration``: the call path pruning variables, warnings and notes of an instrumented compilation."""

import json
import os
import stat
from pathlib import Path
from typing import Dict, Tuple

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.services import callpath_pruning

# prints what the script was given and what the pass prints when it pruned
SCRIPT = (
    "#!/bin/bash\n"
    "env | grep -E '^DP_CALLPATH_' | sort\n"
    "echo 'Enumerated 12 call path states with hotspot pruning'\n"
)
SCRIPT_WITHOUT_PASS_OUTPUT = "#!/bin/bash\nenv | grep -E '^DP_CALLPATH_HOTSPOTS='\n"


def _setup(root: Path, script: str, enabled: bool, hotspots: bool) -> ProjectManagerArguments:
    config_dir = root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    for settings in ("seq_settings.json", "dp_settings.json"):
        (config_dir / settings).write_text(json.dumps({"CC": "clang"}))
    for name in ("compile.sh", "execute.sh"):
        path = config_dir / "tiny" / name
        path.write_text(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    if hotspots:
        directory = root / ".discopop" / "hotspot_detection"
        directory.mkdir(parents=True)
        (directory / "Hotspots.json").write_text(json.dumps({"code_regions": [{"hotness": "YES"}]}))
    if enabled:
        callpath_pruning.save_callpath_pruning(
            str(root / ".discopop" / "project"), callpath_pruning.CallpathPruning(enabled=True, hot_depth=3)
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
    return dict(line.split("=", 1) for line in stdout.splitlines() if line.startswith("DP_CALLPATH_"))


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in callpath_pruning.VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_enabled_with_current_hotspots_passes_the_variables_and_notes_the_pruning(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=True, hotspots=True)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    variables = _variables(stdout)
    assert variables[callpath_pruning.HOTSPOTS_VARIABLE] == str(tmp_path / ".discopop/hotspot_detection/Hotspots.json")
    assert variables[callpath_pruning.HOT_DEPTH_VARIABLE] == "3"
    assert "NOTE: Call path states were pruned" in stderr and "12 call path states left" in stderr
    assert "not activated" not in stderr


def test_enabled_but_the_pass_does_not_report_pruning(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT_WITHOUT_PASS_OUTPUT, enabled=True, hotspots=True)
    _stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert "NOTE: Call path pruning was requested" in stderr


def test_disabled_with_current_hotspots_warns_and_sets_nothing(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=False, hotspots=True)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout) == {}
    assert "WARNING: Call path pruning is not activated" in stderr
    assert "NOTE:" not in stderr


def test_enabled_without_hotspots_warns(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=True, hotspots=False)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout) == {}
    assert "WARNING: Call path pruning is activated, but there are no current hotspot" in stderr


def test_nothing_is_said_without_hotspots_and_setting(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=False, hotspots=False)
    _stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert "pruning" not in stderr.lower().replace("hotspot pruning", "")


@pytest.mark.parametrize("script,settings", [("compile.sh", "seq_settings.json"), ("execute.sh", "dp_settings.json")])
def test_only_the_instrumented_compilation_is_concerned(tmp_path: Path, script: str, settings: str) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=True, hotspots=True)
    stdout, stderr = _run(arguments, tmp_path, script, settings)
    assert _variables(stdout) == {}
    assert "NOTE:" not in stderr and "WARNING: Call path" not in stderr


def test_variables_from_the_environment_are_ignored_when_pruning_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(callpath_pruning.HOTSPOTS_VARIABLE, "/somewhere/Hotspots.json")
    arguments = _setup(tmp_path, SCRIPT, enabled=False, hotspots=False)
    stdout, stderr = _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    assert _variables(stdout) == {}
    assert "DP_CALLPATH_HOTSPOTS set in the environment or the settings file is ignored" in stderr


def test_the_state_of_the_pruning_is_recorded_with_the_profiling_data(tmp_path: Path) -> None:
    arguments = _setup(
        tmp_path,
        SCRIPT + 'mkdir -p "$DOT_DISCOPOP" && echo \'1\t\'"$PWD"/a.c > "$DOT_DISCOPOP/FileMapping.txt"\n',
        enabled=True,
        hotspots=True,
    )
    _run(arguments, tmp_path, "compile.sh", "dp_settings.json")
    environment = callpath_pruning.environment(arguments, "tiny")
    assert callpath_pruning.recorded_state(str(tmp_path / ".discopop")) == callpath_pruning.state_of(
        environment, arguments.dot_dp
    )
    assert callpath_pruning.stale_message(arguments, "tiny") is None
    callpath_pruning.save_callpath_pruning(arguments.project_dir, callpath_pruning.CallpathPruning())
    assert callpath_pruning.stale_message(arguments, "tiny") is not None


def test_a_given_environment_is_used_instead_of_a_new_one(tmp_path: Path) -> None:
    arguments = _setup(tmp_path, SCRIPT, enabled=True, hotspots=True)
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    given = {callpath_pruning.HOTSPOTS_VARIABLE: "/given/Hotspots.json", callpath_pruning.HOT_DEPTH_VARIABLE: "9"}
    result = execute_configuration(
        arguments,
        str(tmp_path),
        config_path,
        os.path.join(arguments.project_config_dir, "dp_settings.json"),
        os.path.join(config_path, "compile.sh"),
        1,
        None,
        callpath_pruning_environment=given,
    )
    assert result is not None
    assert _variables(result[2]) == given
