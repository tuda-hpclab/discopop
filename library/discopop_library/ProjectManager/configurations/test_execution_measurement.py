# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for which runtime ``execute_configuration`` reports and records.

These run an actual script through the real function, because the point of the
feature is what a program's output does to the recorded measurement.
"""

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    TIME_SOURCE_CONSOLE,
    TIME_SOURCE_FALLBACK,
    TIME_SOURCE_WALL_CLOCK,
)

TOTAL_TIME_REGEX = r"Total time:\s*([0-9.]+)"


def _project(tmp_path: Path, script_body: str) -> Tuple[ProjectManagerArguments, str, str, str]:
    """A minimal project the real ``execute_configuration`` can be run against."""
    project_root = tmp_path / "project"
    config_path = project_root / ".discopop" / "project" / "configs" / "tiny"
    os.makedirs(config_path)

    settings_path = project_root / ".discopop" / "project" / "configs" / "seq_settings.json"
    with open(settings_path, "w") as f:
        json.dump({"CC": "clang", "CXX": "clang++"}, f)

    script_path = config_path / "execute.sh"
    with open(script_path, "w") as f:
        f.write("#!/bin/bash\n" + script_body)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)

    arguments = ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="tiny",
        execute_inplace=True,
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
    return arguments, str(config_path), str(settings_path), str(script_path)


def _recorded(arguments: ProjectManagerArguments) -> Dict[str, Any]:
    with open(os.path.join(arguments.project_dir, "execution_results.json"), "r") as f:
        results = json.load(f)
    entries = results["tiny"]["execute.sh"]["seq_settings.json"]
    assert len(entries) == 1
    return cast(Dict[str, Any], entries[0])


def _run(tmp_path: Path, script_body: str, regex: Optional[str]) -> Tuple[float, Dict[str, Any]]:
    arguments, config_path, settings_path, script_path = _project(tmp_path, script_body)
    result = execute_configuration(
        arguments,
        arguments.project_root,
        config_path,
        settings_path,
        script_path,
        1,
        None,
        execution_time_regex=regex,
    )
    assert result is not None
    assert result[0] == 0
    return result[1], _recorded(arguments)


def test_without_a_pattern_the_wall_clock_time_is_reported(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo '<DP_EXEC_TIME>0.001</DP_EXEC_TIME>'\n", None)
    # the program printed a time, but nothing asked for it to be read
    assert entry["time_source"] == TIME_SOURCE_WALL_CLOCK
    assert entry["time"] == entry["wall_clock_time"] == reported
    assert reported != 0.001


def test_the_time_the_program_reports_replaces_the_wall_clock_time(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo 'Total time: 42.5 seconds'\n", TOTAL_TIME_REGEX)
    assert reported == 42.5
    assert entry["time"] == 42.5
    assert entry["time_source"] == TIME_SOURCE_CONSOLE
    # the measured time is kept alongside rather than replaced
    assert entry["wall_clock_time"] != 42.5


def test_the_default_pattern_needs_no_value(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo '<DP_EXEC_TIME>7.25</DP_EXEC_TIME>'\n", DEFAULT_EXECUTION_TIME_REGEX)
    assert reported == 7.25
    assert entry["time_source"] == TIME_SOURCE_CONSOLE


def test_a_pattern_that_finds_nothing_falls_back_visibly(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo 'no timing here'\n", TOTAL_TIME_REGEX)
    assert reported == entry["wall_clock_time"]
    assert entry["time"] == entry["wall_clock_time"]
    # the run must be distinguishable from one that genuinely reported its time
    assert entry["time_source"] == TIME_SOURCE_FALLBACK


def test_a_time_printed_to_stderr_is_found(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo 'Total time: 3.5' >&2\n", TOTAL_TIME_REGEX)
    assert reported == 3.5
    assert entry["time_source"] == TIME_SOURCE_CONSOLE


def test_the_measurement_out_parameter_exposes_the_wall_clock_time(tmp_path: Path) -> None:
    """The wall clock time must be reachable by a caller, not only by the JSON.

    The autotuner derives its per-candidate timeout from it: a timeout scaled to
    the *reported* time would kill every candidate before the part the program
    does not time (setup, teardown, file I/O) is done.
    """
    arguments, config_path, settings_path, script_path = _project(tmp_path, "echo 'Total time: 42.5 seconds'\n")
    measurement: Dict[str, Any] = {}
    result = execute_configuration(
        arguments,
        arguments.project_root,
        config_path,
        settings_path,
        script_path,
        1,
        None,
        execution_time_regex=TOTAL_TIME_REGEX,
        measurement=measurement,
    )
    assert result is not None
    assert result[1] == 42.5
    assert measurement["time"] == 42.5
    assert measurement["time_source"] == TIME_SOURCE_CONSOLE
    # the value the timeout has to be derived from: the real duration of the run
    assert measurement["wall_clock_time"] < 42.5


def test_the_measurement_out_parameter_is_optional(tmp_path: Path) -> None:
    reported, entry = _run(tmp_path, "echo 'Total time: 1.0'\n", TOTAL_TIME_REGEX)
    assert reported == 1.0
