# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A reset of the project removes the analysis record together with the data it describes."""

from pathlib import Path

from discopop_library.AnalysisRecord import RECORD_FILENAME, record_step
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.utilities.reset import reset_project


def _arguments(project_root: Path, reset: bool, reset_execution_results: bool) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=False,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions=None,
        reset=reset,
        reset_execution_results=reset_execution_results,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


def _project_with_record(tmp_path: Path) -> Path:
    dot = tmp_path / ".discopop"
    (dot / "project").mkdir(parents=True)
    (dot / "profiler").mkdir()
    (dot / "profiler" / "Data.xml").write_text("<x/>")
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    record_step(str(dot), "dependence_profiling", {"config": "tiny", "compile_script": "c.sh"})
    assert (dot / RECORD_FILENAME).exists()
    return dot


def test_reset_clears_the_record(tmp_path: Path) -> None:
    dot = _project_with_record(tmp_path)
    reset_project(_arguments(tmp_path, reset=True, reset_execution_results=True))
    assert not (dot / RECORD_FILENAME).exists()
    assert not (dot / "profiler").exists()
    assert (dot / "project").exists()


def test_resetting_only_the_execution_results_keeps_the_record(tmp_path: Path) -> None:
    dot = _project_with_record(tmp_path)
    reset_project(_arguments(tmp_path, reset=False, reset_execution_results=True))
    assert (dot / RECORD_FILENAME).exists()
