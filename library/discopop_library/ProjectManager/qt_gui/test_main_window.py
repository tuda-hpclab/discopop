# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import sys
from pathlib import Path
from typing import Callable, List

import pytest
from pytestqt.qtbot import QtBot

from PySide6.QtCore import Qt

from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.main_window import (
    TAB_AUTOTUNING,
    TAB_EDITOR,
    TAB_EXECUTE,
    TAB_HOTSPOT,
    TAB_ORDER,
    TAB_PATCH_REPAIR,
    TAB_PATTERN_DETECTION,
    TAB_PROFILING,
    TAB_REPORT,
    TAB_SETUP,
    MainWindow,
)
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.panels.editor_panel import EditorPanel
from discopop_library.ProjectManager.qt_gui.panels.setup_panel import SetupPanel
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.project_state import AutotuningFinished, ResultsChanged
from discopop_library.ProjectManager.services.workflow_status import StageState


def test_all_tabs_exist_in_order(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    # the sidebar: the setup, the pipeline, the results
    assert window.tab_names() == [
        TAB_SETUP,
        TAB_EDITOR,
        TAB_PROFILING,
        TAB_HOTSPOT,
        TAB_PATTERN_DETECTION,
        TAB_PATCH_REPAIR,
        TAB_AUTOTUNING,
        TAB_EXECUTE,
        TAB_REPORT,
    ]
    assert window.tab_names() == list(TAB_ORDER)
    assert [window.stack.indexOf(window.tab(name)) for name in TAB_ORDER] == list(range(len(TAB_ORDER)))
    assert window.tab_title(TAB_SETUP) == "Project Setup" and window.tab_title(TAB_PROFILING) == "Profiling"
    assert window.tab_title(TAB_EDITOR) == "Configuration Setup" and window.current_tab() == TAB_EDITOR
    assert window.dot_dp_label.toolTip() == str(tmp_path / ".discopop")


def test_closing_the_window_cancels_the_jobs_of_the_panels(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    cancelled: List[str] = []

    class Busy(Panel):
        def cancel_jobs(self) -> None:
            cancelled.append("busy")

    window.add_tab(TAB_ORDER[1], Busy(window.arguments, window.project_state, window.status))
    assert isinstance(window.tab(TAB_ORDER[1]), Busy) and window.stack.indexOf(window.tab(TAB_ORDER[1])) == 1
    window.show()
    window.close()
    assert cancelled == ["busy"]


def test_the_toolkit_is_chosen_on_the_command_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr(sys, "argv", ["discopop_project_manager", "--gui", "-p", str(tmp_path)])
    assert parse_args().gui_toolkit == "qt"
    monkeypatch.setattr(sys, "argv", ["discopop_project_manager", "--gui", "--gui-toolkit", "tk", "-p", str(tmp_path)])
    assert parse_args().gui_toolkit == "tk"


def test_tab_host(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show_tab(TAB_ORDER[2])
    assert window.current_tab() == TAB_ORDER[2]
    assert window.nav.current_stage() == TAB_ORDER[2]
    window.set_tab_title(TAB_EDITOR, "Editor *")
    assert window.tab_title(TAB_EDITOR) == "Configuration Setup *" and window.current_tab() == TAB_ORDER[2]
    window.set_tab_title(TAB_EDITOR, "Editor")
    assert window.tab_title(TAB_EDITOR) == "Configuration Setup"
    window.set_tab_enabled(TAB_ORDER[4], False, "no profiling data")
    assert not window.is_tab_enabled(TAB_ORDER[4]) and window.tab_tooltip(TAB_ORDER[4]) == "no profiling data"
    assert window.nav.detail(TAB_ORDER[4]) == "no profiling data"
    # a stage that becomes disabled while it is shown gives way to the Configuration Setup stage
    window.show_tab(TAB_ORDER[4])
    window.set_tab_enabled(TAB_ORDER[4], False, "gone")
    assert window.current_tab() == TAB_EDITOR


def test_selecting_a_stage_in_the_sidebar_shows_its_panel(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.nav.select_stage(TAB_REPORT)
    assert window.current_tab() == TAB_REPORT and window.stack.currentWidget() is window.report_panel


def test_the_sidebar_shows_what_the_stages_have_done(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    assert window.nav.stage_state(TAB_PROFILING) == StageState.NOT_RUN
    for name in ("Data.xml", "dynamic_dependencies.txt", "loop_counter_output.txt", "reduction.txt"):
        (tmp_path / ".discopop" / "profiler").mkdir(exist_ok=True)
        (tmp_path / ".discopop" / "profiler" / name).write_text("")
    (tmp_path / ".discopop" / "FileMapping.txt").write_text("")
    window.project_state.publish(ResultsChanged())
    qtbot.waitUntil(lambda: window.nav.stage_state(TAB_PROFILING) == StageState.DONE, timeout=2000)


def test_the_panels_are_wired(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    # nothing was profiled: the Autotuning stage is disabled, with a reason; the Pattern Detection stage stays
    # reachable and explains what is missing, the sidebar marks it locked
    assert not window.is_tab_enabled(TAB_AUTOTUNING) and window.tab_tooltip(TAB_AUTOTUNING)
    assert window.nav.stage_state(TAB_AUTOTUNING) == StageState.LOCKED
    assert window.is_tab_enabled(TAB_PATTERN_DETECTION)
    assert window.nav.stage_state(TAB_PATTERN_DETECTION) == StageState.LOCKED
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


def test_profiling_data_unlocks_the_pattern_detection_stage(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    assert window.nav.stage_state(TAB_PATTERN_DETECTION) == StageState.LOCKED
    (tmp_path / ".discopop" / "profiler").mkdir()
    for name in ("Data.xml", "dynamic_dependencies.txt", "loop_counter_output.txt", "reduction.txt"):
        (tmp_path / ".discopop" / "profiler" / name).write_text("")
    (tmp_path / ".discopop" / "FileMapping.txt").write_text("")
    window.project_state.publish(ResultsChanged())
    qtbot.waitUntil(lambda: window.nav.stage_state(TAB_PATTERN_DETECTION) == StageState.NOT_RUN, timeout=2000)
    assert window.is_tab_enabled(TAB_PATTERN_DETECTION)


def test_ctrl_s_saves_the_stage_in_front(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: List[str] = []

    def recorder(name: str) -> Callable[[object], bool]:
        def save(_self: object) -> bool:
            saved.append(name)
            return True

        return save

    monkeypatch.setattr(EditorPanel, "save", recorder("editor"))
    monkeypatch.setattr(SetupPanel, "save", recorder("setup"))
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window.stack, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    window.show_tab(TAB_SETUP)
    qtbot.keyClick(window.stack, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    window.show_tab(TAB_REPORT)
    qtbot.keyClick(window.stack, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert saved == ["editor", "setup"]


def test_execute_and_profiling_block_each_other(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window._run_state_changed(window.profiling_panel, True)
    assert window.profiling_panel._blocked and window.report_panel is not None
    window._run_state_changed(window.profiling_panel, False)
    assert not window.profiling_panel._blocked
    window._run_state_changed(window.execute_panel, True)
    assert window.execute_panel._blocked and not window.execute_panel.run_button.isEnabled()
    window._run_state_changed(window.execute_panel, False)
    assert not window.execute_panel._blocked


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


def test_the_report_follows_the_autotuner_and_waits_for_executions(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    refreshed: List[bool] = []
    window.report_panel.update_display = lambda: refreshed.append(True)  # type: ignore[method-assign]
    window.project_state.publish(AutotuningFinished())
    assert refreshed == [True]

    window.report_panel.generate_report_button.setEnabled(True)
    window.execute_panel._begin_run("running", "running")
    assert not window.report_panel.generate_report_button.isEnabled()
