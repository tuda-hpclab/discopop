# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import sys
from pathlib import Path
from typing import List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui.main_window import TAB_ORDER, MainWindow
from discopop_library.ProjectManager.qt_gui.panel import Panel


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


def test_all_tabs_exist_in_order(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == list(TAB_ORDER)
    assert window.dot_dp_label.toolTip() == str(tmp_path / ".discopop")


def test_closing_the_window_cancels_the_jobs_of_the_panels(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    cancelled: List[str] = []

    class Busy(Panel):
        def cancel_jobs(self) -> None:
            cancelled.append("busy")

    window.add_tab(TAB_ORDER[1], Busy(window.arguments, window.project_state, window.status))
    assert window.tabs.tabText(1) == TAB_ORDER[1] and isinstance(window.tab(TAB_ORDER[1]), Busy)
    window.show()
    window.close()
    assert cancelled == ["busy"]


def test_the_toolkit_is_chosen_on_the_command_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr(sys, "argv", ["discopop_project_manager", "--gui", "-p", str(tmp_path)])
    assert parse_args().gui_toolkit == "tk"
    monkeypatch.setattr(sys, "argv", ["discopop_project_manager", "--gui", "--gui-toolkit", "qt", "-p", str(tmp_path)])
    assert parse_args().gui_toolkit == "qt"
