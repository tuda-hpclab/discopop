# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from typing import Dict

from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services.workflow_status import (
    STAGE_AUTOTUNING,
    STAGE_EDITOR,
    STAGE_EXECUTE,
    STAGE_HOTSPOT,
    STAGE_PATCH_REPAIR,
    STAGE_PATTERN_DETECTION,
    STAGE_REPORT,
    StageState,
    StageStatus,
    autotuning_ready,
    count_execution_results,
    stage_statuses,
)


def make_arguments(root: Path) -> ProjectManagerArguments:
    (root / ".discopop" / "project" / "configs").mkdir(parents=True)
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=False,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=True,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        gui_toolkit="qt",
    )


def touch(path: str, content: str = "x", mtime: float = 0.0) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    if mtime:
        os.utime(path, (mtime, mtime))


def profile(dot_dp: str, mtime: float = 0.0) -> None:
    for name in ("Data.xml", "dynamic_dependencies.txt", "loop_counter_output.txt", "reduction.txt"):
        touch(os.path.join(dot_dp, "profiler", name), mtime=mtime)
    touch(os.path.join(dot_dp, "FileMapping.txt"), mtime=mtime)


def add_patches(dot_dp: str, count: int = 2) -> None:
    for i in range(count):
        touch(os.path.join(dot_dp, "patch_generator", str(i), "a.patch"))


def statuses(arguments: ProjectManagerArguments, config: str = "") -> Dict[str, StageStatus]:
    return stage_statuses(arguments, config or None)


def test_empty_project(tmp_path: Path) -> None:
    result = statuses(make_arguments(tmp_path))
    assert result[STAGE_EDITOR].state == StageState.NOT_RUN
    assert result[STAGE_EXECUTE].state == StageState.NOT_RUN
    assert result[STAGE_HOTSPOT].state == StageState.NOT_RUN
    assert result[STAGE_PATTERN_DETECTION] == StageStatus(StageState.LOCKED, "needs profiling data")
    assert result[STAGE_PATCH_REPAIR] == StageStatus(StageState.LOCKED, "needs suggestions")
    assert result[STAGE_AUTOTUNING] == StageStatus(StageState.LOCKED, "needs profiling data")
    assert result[STAGE_REPORT] == StageStatus(StageState.NOT_RUN, "0 execution results")


def test_editor(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    assert statuses(arguments, "A")[STAGE_EDITOR].state == StageState.NOT_RUN
    os.makedirs(os.path.join(arguments.project_config_dir, "A"))
    assert statuses(arguments, "A")[STAGE_EDITOR] == StageStatus(StageState.NOT_RUN, "no execute.sh")
    touch(os.path.join(arguments.project_config_dir, "A", "execute.sh"))
    assert statuses(arguments, "A")[STAGE_EDITOR] == StageStatus(StageState.DONE, "A")


def test_execute_and_report_count_runs(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    results = {"A": {"execute.sh": {"s1": [{"time": 1}, {"time": 2}], "s2": [{"time": 3}]}}, "B": "junk"}
    touch(os.path.join(arguments.project_dir, "execution_results.json"), json.dumps(results))
    assert count_execution_results(arguments.project_dir) == 3
    profile(arguments.dot_dp)
    result = statuses(arguments, "A")
    assert result[STAGE_EXECUTE] == StageStatus(StageState.DONE, "3 measured runs")
    assert result[STAGE_REPORT] == StageStatus(StageState.DONE, "3 execution results")


def test_unreadable_execution_results(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    touch(os.path.join(arguments.project_dir, "execution_results.json"), "{not json")
    assert count_execution_results(arguments.project_dir) == 0
    profile(arguments.dot_dp)
    assert statuses(arguments)[STAGE_EXECUTE] == StageStatus(StageState.DONE, "profiled")


def test_hotspot_done_and_stale(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    touch(hotspot_data.hotspots_json_path(arguments.dot_dp), "{}")
    cs_id = hotspot_data.cs_id_path(arguments.dot_dp)
    source = str(tmp_path / "main.cpp")
    touch(cs_id, mtime=2000.0)
    touch(source, mtime=1000.0)
    assert statuses(arguments)[STAGE_HOTSPOT].state == StageState.DONE
    os.utime(source, (3000.0, 3000.0))
    assert statuses(arguments)[STAGE_HOTSPOT] == StageStatus(StageState.STALE, "sources changed")


def test_pattern_detection_states(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    dot_dp = arguments.dot_dp
    profile(dot_dp, mtime=1000.0)
    assert statuses(arguments)[STAGE_PATTERN_DETECTION].state == StageState.NOT_RUN
    add_patches(dot_dp, 2)
    touch(os.path.join(dot_dp, "explorer", "patterns.json"), "{}", mtime=2000.0)
    assert statuses(arguments)[STAGE_PATTERN_DETECTION] == StageStatus(StageState.DONE, "2 suggestions")
    os.utime(os.path.join(dot_dp, "profiler", "Data.xml"), (3000.0, 3000.0))
    assert statuses(arguments)[STAGE_PATTERN_DETECTION].state == StageState.STALE


def test_pattern_detection_without_patterns_file_is_not_stale(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    profile(arguments.dot_dp, mtime=1000.0)
    os.makedirs(os.path.join(arguments.dot_dp, "explorer"))
    assert statuses(arguments)[STAGE_PATTERN_DETECTION] == StageStatus(StageState.DONE, "0 suggestions")


def test_patch_repair(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    dot_dp = arguments.dot_dp
    assert statuses(arguments)[STAGE_PATCH_REPAIR].state == StageState.LOCKED
    add_patches(dot_dp, 3)
    assert statuses(arguments)[STAGE_PATCH_REPAIR].state == StageState.NOT_RUN
    touch(os.path.join(dot_dp, "patch_repair", "results.json"), json.dumps({"suggestions": {"0": {}, "1": {}}}))
    assert statuses(arguments)[STAGE_PATCH_REPAIR] == StageStatus(StageState.DONE, "2 results")


def test_autotuning(tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    dot_dp = arguments.dot_dp
    assert not autotuning_ready(dot_dp)
    profile(dot_dp)
    assert statuses(arguments)[STAGE_AUTOTUNING] == StageStatus(StageState.LOCKED, "needs suggestions")
    add_patches(dot_dp)
    assert autotuning_ready(dot_dp)
    assert statuses(arguments)[STAGE_AUTOTUNING].state == StageState.NOT_RUN
    touch(os.path.join(dot_dp, "auto_tuner", "results.json"), "{}")
    assert statuses(arguments)[STAGE_AUTOTUNING].state == StageState.DONE
