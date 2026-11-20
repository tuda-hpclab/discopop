# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""The setting of the OpenMP flags of instrumented compilations: storage, precedence, fingerprint, messages."""

import json
from pathlib import Path

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services import openmp_handling


def _arguments(root: Path, strip: bool | None = None) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
        full_execute=False,
        list=False,
        execute_configurations="",
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


def test_default_keeps_the_flags(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    assert openmp_handling.strips_openmp(arguments) is False
    assert openmp_handling.fingerprint_part(arguments) is None
    assert openmp_handling.environment(arguments) == {"DP_OPENMP_QUIET": "1"}


def test_stored_setting_and_command_line_precedence(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    openmp_handling.save_openmp_handling(arguments.project_dir, openmp_handling.OpenMPHandling(strip=True))
    assert openmp_handling.strips_openmp(arguments) is True
    assert openmp_handling.fingerprint_part(arguments) == "strip"
    assert openmp_handling.environment(arguments)["DP_STRIP_OPENMP"] == "1"
    assert openmp_handling.strips_openmp(_arguments(tmp_path, strip=False)) is False
    openmp_handling.save_openmp_handling(arguments.project_dir, openmp_handling.OpenMPHandling(strip=False))
    assert openmp_handling.strips_openmp(_arguments(tmp_path, strip=True)) is True


def test_unreadable_file_falls_back_to_the_default(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    Path(arguments.project_dir).mkdir(parents=True)
    Path(openmp_handling.openmp_handling_path(arguments.project_dir)).write_text("not json")
    assert openmp_handling.load_openmp_handling(arguments.project_dir) == openmp_handling.OpenMPHandling()


def test_save_only_writes_a_changed_setting(tmp_path: Path) -> None:
    project_dir = str(tmp_path / "project")
    openmp_handling.save_openmp_handling(project_dir, openmp_handling.OpenMPHandling(strip=False))
    assert not Path(openmp_handling.openmp_handling_path(project_dir)).exists()
    openmp_handling.save_openmp_handling(project_dir, openmp_handling.OpenMPHandling(strip=True))
    assert json.loads(Path(openmp_handling.openmp_handling_path(project_dir)).read_text()) == {"strip": True}


def test_outcome_messages(tmp_path: Path) -> None:
    assert openmp_handling.outcome_message(str(tmp_path)) == (None, None)
    (tmp_path / "openmp_flags_seen.json").write_text('{"flags": "-fopenmp", "stripped": false}')
    warning, note = openmp_handling.outcome_message(str(tmp_path))
    assert note is None and warning is not None
    assert "--strip-openmp" in warning and "Project Setup" in warning and "DP_STRIP_OPENMP=1" in warning
    (tmp_path / "openmp_flags_seen.json").write_text('{"flags": "-fopenmp", "stripped": true}')
    warning, note = openmp_handling.outcome_message(str(tmp_path))
    assert warning is None and note is not None and "removed" in note
    openmp_handling.clear_flags_seen(str(tmp_path))
    assert openmp_handling.outcome_message(str(tmp_path)) == (None, None)
