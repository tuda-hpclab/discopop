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

from PySide6.QtCore import Qt

from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.main_window import (
    TAB_AUTOTUNING,
    TAB_ORDER,
    TAB_PATTERN_DETECTION,
    MainWindow,
)
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.panels.editor_panel import EditorPanel
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.project_state import ResultsChanged


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


def test_the_panels_are_wired(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    # nothing was profiled: the tabs that need profiling data are disabled, with a reason
    for name in (TAB_PATTERN_DETECTION, TAB_AUTOTUNING):
        index = window.tabs.indexOf(window.tab(name))
        assert not window.tabs.isTabEnabled(index) and window.tabs.tabToolTip(index)
    # the hotspot panel reads the timeouts of the Execute tab, the report writes into its console
    assert window.hotspot_panel._timeouts == window.execute_panel.timeouts  # type: ignore[attr-defined]
    window.report_panel._report_progress("from the report")
    assert "from the report" in window.execute_panel.console.text()
    # every panel's jobs are cancelled on close
    assert {type(panel).__name__ for panel in window.panels} >= {
        "ConfigListPanel",
        "EditorPanel",
        "ExecutePanel",
        "ReportPanel",
        "HotspotPanel",
        "PatternDetectionPanel",
        "PatchRepairPanel",
        "AutotuningPanel",
    }


def test_profiling_data_enables_the_pattern_detection_tab(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    (tmp_path / ".discopop" / "profiler").mkdir()
    window.project_state.publish(ResultsChanged())
    assert window.tabs.isTabEnabled(window.tabs.indexOf(window.tab(TAB_PATTERN_DETECTION)))


def test_ctrl_s_saves_through_the_editor(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: List[bool] = []
    monkeypatch.setattr(EditorPanel, "save_shortcut", lambda _self: saved.append(True))
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window.tabs, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert saved == [True]


def test_a_fresh_project_opens_the_wizard_after_showing(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    window = MainWindow(make_arguments(tmp_path), was_initialized=True)
    qtbot.addWidget(window)
    window.show()
    window.after_show()
    assert dialog_answers.titles("show_message") == ["Project Initialized"]
    wizard = window.config_list._wizard  # type: ignore[attr-defined]
    assert wizard is not None and wizard.isVisible()
    wizard.done(0)
