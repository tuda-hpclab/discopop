# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A successful hotspot detection (hd) or dependence profiling (dp) run is recorded in the analysis record."""

import json
import os
import stat
from pathlib import Path
from typing import Optional

from discopop_library.AnalysisRecord import RECORD_FILENAME, step_status
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration

EXECUTE_HD = (
    "#!/bin/bash\nmkdir -p $DOT_DISCOPOP/hotspot_detection/private\n"
    "echo '1 0.5' > $DOT_DISCOPOP/hotspot_detection/private/hotspot_result_0.txt\n"
)
EXECUTE_DP = (
    "#!/bin/bash\nmkdir -p $DOT_DISCOPOP/profiler\n"
    "echo '<x/>' > $DOT_DISCOPOP/profiler/Data.xml\n"
    "echo 'x' > $DOT_DISCOPOP/profiler/dynamic_dependencies.txt\n"
)


def _write_project(project_root: Path, execute_body: str) -> None:
    configs = project_root / ".discopop" / "project" / "configs"
    (configs / "tiny").mkdir(parents=True)
    (project_root / "main.cpp").write_text("int main() { return 0; }\n")
    for name in ("seq", "hd", "dp"):
        (configs / (name + "_settings.json")).write_text(json.dumps({"CC": "clang"}))
    (configs / "compile.sh").write_text("#!/bin/bash\nexit 0\n")
    script = configs / "tiny" / "execute.sh"
    script.write_text(execute_body)
    os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)


def _arguments(project_root: Path) -> ProjectManagerArguments:
    return ProjectManagerArguments(
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


def _run(project_root: Path, mode: str, script: str) -> Optional[int]:
    arguments = _arguments(project_root)
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    script_path = (
        os.path.join(arguments.project_config_dir, "compile.sh")
        if script == "compile.sh"
        else os.path.join(config_path, script)
    )
    result = execute_configuration(
        arguments,
        str(project_root),
        config_path,
        os.path.join(arguments.project_config_dir, mode + "_settings.json"),
        script_path,
        1,
        None,
    )
    return None if result is None else result[0]


def _record(project_root: Path) -> dict:  # type: ignore[type-arg]
    with open(project_root / ".discopop" / RECORD_FILENAME) as f:
        data: dict = json.load(f)  # type: ignore[type-arg]
    return data


def test_hd_run_records_hotspot_detection(tmp_path: Path) -> None:
    _write_project(tmp_path, EXECUTE_HD)
    assert _run(tmp_path, "hd", "compile.sh") == 0
    assert not (tmp_path / ".discopop" / RECORD_FILENAME).exists()  # the instrumenting compilation records nothing
    assert _run(tmp_path, "hd", "execute.sh") == 0

    step = _record(tmp_path)["steps"]["hotspot_detection"]
    assert step["params"]["configs"] == {"tiny": os.path.join(".discopop", "project", "configs", "compile.sh")}
    assert step_status(str(tmp_path / ".discopop"), "hotspot_detection").state == "current"


def test_dp_run_records_dependence_profiling(tmp_path: Path) -> None:
    _write_project(tmp_path, EXECUTE_DP)
    assert _run(tmp_path, "dp", "compile.sh") == 0
    assert not (tmp_path / ".discopop" / RECORD_FILENAME).exists()
    assert _run(tmp_path, "dp", "execute.sh") == 0

    params = _record(tmp_path)["steps"]["dependence_profiling"]["params"]
    assert params["config"] == "tiny"
    assert params["compile_script"].endswith("compile.sh")
    assert step_status(str(tmp_path / ".discopop"), "dependence_profiling").state == "current"


def test_failed_run_records_nothing(tmp_path: Path) -> None:
    _write_project(tmp_path, EXECUTE_DP + "exit 3\n")
    assert _run(tmp_path, "dp", "execute.sh") == 3
    assert not (tmp_path / ".discopop" / RECORD_FILENAME).exists()


def test_run_without_profiling_output_records_nothing(tmp_path: Path) -> None:
    _write_project(tmp_path, "#!/bin/bash\nexit 0\n")
    assert _run(tmp_path, "hd", "execute.sh") == 0
    assert _run(tmp_path, "dp", "execute.sh") == 0
    assert not (tmp_path / ".discopop" / RECORD_FILENAME).exists()


def test_seq_run_records_nothing(tmp_path: Path) -> None:
    _write_project(tmp_path, EXECUTE_HD + EXECUTE_DP)
    assert _run(tmp_path, "seq", "execute.sh") == 0
    assert not (tmp_path / ".discopop" / RECORD_FILENAME).exists()


def test_two_hd_configurations_accumulate(tmp_path: Path) -> None:
    _write_project(tmp_path, EXECUTE_HD)
    other = tmp_path / ".discopop" / "project" / "configs" / "small"
    other.mkdir()
    (other / "execute.sh").write_text(EXECUTE_HD)
    assert _run(tmp_path, "hd", "execute.sh") == 0

    arguments = _arguments(tmp_path)
    assert (
        execute_configuration(
            arguments,
            str(tmp_path),
            str(other),
            os.path.join(arguments.project_config_dir, "hd_settings.json"),
            str(other / "execute.sh"),
            1,
            None,
        )
        is not None
    )
    assert sorted(_record(tmp_path)["steps"]["hotspot_detection"]["params"]["configs"]) == ["small", "tiny"]
