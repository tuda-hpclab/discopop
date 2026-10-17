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

from discopop_library.ProjectManager.qt_gui.main_window import TAB_ORDER, MainWindow
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.testing import make_arguments


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


def test_tab_host(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show_tab(TAB_ORDER[2])
    assert window.current_tab() == TAB_ORDER[2]
    window.set_tab_title(TAB_ORDER[0], "Editor *")
    assert window.tabs.tabText(0) == "Editor *" and window.current_tab() == TAB_ORDER[2]
    window.set_tab_enabled(TAB_ORDER[4], False, "no profiling data")
    assert not window.tabs.isTabEnabled(4) and window.tabs.tabToolTip(4) == "no profiling data"
