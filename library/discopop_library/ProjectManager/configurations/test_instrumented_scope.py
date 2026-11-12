# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The record of the scope the data in DOT_DISCOPOP was instrumented with, and the stale data message."""

import json
import os
import stat
from pathlib import Path
from typing import Optional

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.project_environment import (
    INSTRUMENTED_SCOPE_FILE,
    instrumented_scope,
    record_instrumented_scope,
    stale_scope_message,
)


@pytest.fixture
def dot_discopop(tmp_path: Path) -> Path:
    path = tmp_path / ".discopop"
    path.mkdir()
    return path


@pytest.mark.parametrize("mode", ["dp", "hd"])
def test_round_trip(dot_discopop: Path, mode: str) -> None:
    record_instrumented_scope(str(dot_discopop), mode, "src")
    assert instrumented_scope(str(dot_discopop), mode) == "src"


def test_modes_are_kept_side_by_side(dot_discopop: Path) -> None:
    record_instrumented_scope(str(dot_discopop), "dp", "src")
    record_instrumented_scope(str(dot_discopop), "hd", "lib")
    assert instrumented_scope(str(dot_discopop), "dp") == "src"
    assert instrumented_scope(str(dot_discopop), "hd") == "lib"
    record_instrumented_scope(str(dot_discopop), "dp", "other")
    assert instrumented_scope(str(dot_discopop), "dp") == "other"
    assert instrumented_scope(str(dot_discopop), "hd") == "lib"


def test_unknown_without_a_record(dot_discopop: Path) -> None:
    assert instrumented_scope(str(dot_discopop), "dp") is None
    record_instrumented_scope(str(dot_discopop), "hd", "src")
    assert instrumented_scope(str(dot_discopop), "dp") is None


def test_missing_directory_is_unknown_and_recording_does_not_raise(tmp_path: Path) -> None:
    missing = str(tmp_path / "nowhere")
    record_instrumented_scope(missing, "dp", "src")
    assert instrumented_scope(missing, "dp") is None


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '"dp"', '{"dp": 3}', '{"dp": null}'])
def test_broken_file_is_unknown(dot_discopop: Path, content: str) -> None:
    (dot_discopop / INSTRUMENTED_SCOPE_FILE).write_text(content)
    assert instrumented_scope(str(dot_discopop), "dp") is None


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_recording_replaces_a_broken_file(dot_discopop: Path, content: str) -> None:
    (dot_discopop / INSTRUMENTED_SCOPE_FILE).write_text(content)
    record_instrumented_scope(str(dot_discopop), "dp", "src")
    assert json.loads((dot_discopop / INSTRUMENTED_SCOPE_FILE).read_text()) == {"dp": "src"}


# ---- stale_scope_message


def _configure(project_root: Path, scope: object) -> str:
    config_dir = project_root / ".discopop" / "project" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project_environment.json").write_text(json.dumps({"DP_PROJECT_ROOT_DIR": scope}))
    return str(config_dir)


def _message(project_root: Path, mode: str = "dp") -> Optional[str]:
    config_dir = str(project_root / ".discopop" / "project" / "configs")
    return stale_scope_message(str(project_root / ".discopop"), mode, str(project_root), config_dir)


def test_no_message_when_unknown(tmp_path: Path) -> None:
    _configure(tmp_path, "src")
    assert _message(tmp_path) is None


def test_no_message_when_equal(tmp_path: Path) -> None:
    _configure(tmp_path, "src")
    record_instrumented_scope(str(tmp_path / ".discopop"), "dp", "src")
    assert _message(tmp_path) is None


def test_no_message_when_equal_after_normalization(tmp_path: Path) -> None:
    _configure(tmp_path, "./src/")
    record_instrumented_scope(str(tmp_path / ".discopop"), "dp", "src")
    assert _message(tmp_path) is None


def test_no_message_when_the_default_scope_is_recorded_and_configured_implicitly(tmp_path: Path) -> None:
    (tmp_path / ".discopop" / "project" / "configs").mkdir(parents=True)
    record_instrumented_scope(str(tmp_path / ".discopop"), "dp", ".")
    assert _message(tmp_path) is None


def test_no_message_when_the_project_environment_is_broken(tmp_path: Path) -> None:
    _configure(tmp_path, 3)
    record_instrumented_scope(str(tmp_path / ".discopop"), "dp", "src")
    assert _message(tmp_path) is None


@pytest.mark.parametrize("mode, kind", [("dp", "profiling"), ("hd", "hotspot detection")])
def test_message_names_both_scopes_and_the_mode(tmp_path: Path, mode: str, kind: str) -> None:
    _configure(tmp_path, "lib")
    record_instrumented_scope(str(tmp_path / ".discopop"), mode, "src")
    message = _message(tmp_path, mode)
    assert message is not None
    assert "'src'" in message and "'lib'" in message
    assert kind in message and "Run the " + mode + " mode again" in message


def test_message_only_concerns_the_asked_mode(tmp_path: Path) -> None:
    _configure(tmp_path, "lib")
    record_instrumented_scope(str(tmp_path / ".discopop"), "dp", "src")
    assert _message(tmp_path, "hd") is None


# ---- execute_configuration records it


def _write_project(project_root: Path, settings_name: str, script: str, scope: str = "src") -> None:
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    (config_dir / settings_name).write_text(json.dumps({"CC": "clang"}))
    (config_dir / "project_environment.json").write_text(json.dumps({"DP_PROJECT_ROOT_DIR": scope}))
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


def test_a_successful_dp_compile_records_the_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "dp_settings.json", "#!/bin/bash\ntrue\n")
    assert _compile(root, "dp_settings.json") == 0
    recorded = json.loads((root / ".discopop" / INSTRUMENTED_SCOPE_FILE).read_text())
    assert recorded == {"dp": "src"}


def test_a_successful_hd_compile_records_the_scope_next_to_dp(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "hd_settings.json", "#!/bin/bash\ntrue\n")
    record_instrumented_scope(str(root / ".discopop"), "dp", "lib")
    assert _compile(root, "hd_settings.json") == 0
    recorded = json.loads((root / ".discopop" / INSTRUMENTED_SCOPE_FILE).read_text())
    assert recorded == {"dp": "lib", "hd": "src"}


def test_a_seq_compile_records_nothing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "seq_settings.json", "#!/bin/bash\ntrue\n")
    assert _compile(root, "seq_settings.json") == 0
    assert not (root / ".discopop" / INSTRUMENTED_SCOPE_FILE).exists()


def test_a_dp_compile_failing_its_checks_records_nothing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        "dp_settings.json",
        "#!/bin/bash\nmkdir -p sub/.discopop\ntouch sub/.discopop/FileMapping.txt\n",
    )
    assert _compile(root, "dp_settings.json") != 0
    assert not (root / ".discopop" / INSTRUMENTED_SCOPE_FILE).exists()
