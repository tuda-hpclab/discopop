# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Helpers for the widget tests of the Qt GUI (imported by the tests only)."""

from pathlib import Path

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments


def make_arguments(project_root: Path) -> ProjectManagerArguments:
    """The arguments of ``discopop_project_manager --gui --gui-toolkit qt`` for a project in ``project_root``."""
    (project_root / ".discopop" / "project" / "configs").mkdir(parents=True, exist_ok=True)
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
        reset=False,
        reset_execution_results=False,
        gui=True,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        gui_toolkit="qt",
    )
