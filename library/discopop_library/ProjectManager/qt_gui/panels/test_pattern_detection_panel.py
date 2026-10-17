# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.qt_gui import main_window, suggestion_browser, widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import pattern_detection_panel
from discopop_library.ProjectManager.qt_gui.panels.pattern_detection_panel import PatternDetectionPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.explorer_state import required_explorer_files
from discopop_library.ProjectManager.services.project_state import (
    HotspotsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import ExplorerRequest


class FakeTabs:
    def __init__(self) -> None:
        self.enabled: Dict[str, Tuple[bool, str]] = {}
        self.shown: List[str] = []

    def show_tab(self, name: str) -> None:
        self.shown.append(name)

    def current_tab(self) -> str:
        return ""

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        self.enabled[name] = (enabled, tooltip)

    def set_tab_title(self, name: str, title: str) -> None:
        pass


def program(code: str) -> List[str]:
    return [sys.executable, "-u", "-c", code]


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> PatternDetectionPanel:
    status = StatusLine()
    qtbot.addWidget(status)
    created = PatternDetectionPanel(make_arguments(tmp_path), ProjectState(), status, FakeTabs())
    qtbot.addWidget(created)
    return created


def profile(panel: PatternDetectionPanel, complete: bool = True) -> None:
    """Create the profiling files (all of them, or only the profiler directory)."""
    dot_dp = Path(panel.arguments.dot_dp)
    (dot_dp / "profiler").mkdir(parents=True, exist_ok=True)
    if complete:
        for path in required_explorer_files(str(dot_dp)):
            Path(path).write_text("")
    panel.refresh()


def tab_state(panel: PatternDetectionPanel) -> Tuple[bool, str]:
    assert isinstance(panel.tabs, FakeTabs)
    return panel.tabs.enabled[main_window.TAB_PATTERN_DETECTION]


def run_with(panel: PatternDetectionPanel, qtbot: QtBot, code: str) -> List[ExplorerRequest]:
    """Run the detection with a small Python program as the explorer; returns the requests it was built from."""
    requests: List[ExplorerRequest] = []

    def command(request: ExplorerRequest, *_a: Any, **_k: Any) -> List[str]:
        requests.append(request)
        return program(code)

    with mock.patch.object(pattern_detection_panel, "explorer_command", command):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
    return requests


def test_without_profiling_data_the_tab_is_disabled_and_says_why(panel: PatternDetectionPanel) -> None:
    enabled, tooltip = tab_state(panel)
    assert not enabled and not panel.run_button.isEnabled()
    assert "Prerequisites not met:" in tooltip and "Data.xml" in tooltip and "FileMapping.txt" in tooltip
    assert not panel.stop_button.isEnabled() and not panel.browse_button.isEnabled()
    assert not panel.vscode_button.isEnabled() and panel.no_suggestions_label.isHidden()


def test_profiling_data_enables_run_and_tab(panel: PatternDetectionPanel) -> None:
    profile(panel)
    panel.project_state.publish(ResultsChanged())
    assert panel.run_button.isEnabled() and tab_state(panel) == (True, "")


def test_the_hotspot_hint_follows_the_hotspot_results(panel: PatternDetectionPanel) -> None:
    assert not panel.hotspot_hint.isHidden()
    with mock.patch.object(hotspot_data, "hotspots_available_for_explorer", lambda _d: True):
        panel.project_state.publish(HotspotsChanged())
    assert panel.hotspot_hint.isHidden()


def test_the_hotspot_hint_leads_to_the_hotspot_tab(panel: PatternDetectionPanel) -> None:
    panel.goto_hotspot_button.click()
    assert isinstance(panel.tabs, FakeTabs)
    assert panel.tabs.shown == [main_window.TAB_HOTSPOT]


def test_the_request_reads_the_widgets(panel: PatternDetectionPanel) -> None:
    assert panel.snapshot_request() == ExplorerRequest("reduction,doall", "auto", False, False)
    for check in panel.pattern_checks.values():
        check.setChecked(False)
    assert panel.snapshot_request().enable_patterns == "reduction,doall"
    panel.pattern_checks["task"].setChecked(True)
    panel.mode_buttons["no_states"].setChecked(True)
    panel.jobs_selector.setCurrentText("4")
    panel.visualize_check.setChecked(True)
    assert panel.snapshot_request() == ExplorerRequest("task", "4", True, True)
    panel.mode_buttons["default"].setChecked(True)
    assert not panel.snapshot_request().ignore_dependency_states


def test_the_visualization_option_says_where_the_graphs_open(panel: PatternDetectionPanel) -> None:
    assert "window of its own" in panel.visualize_check.toolTip()


def test_run_without_profiling_data_is_refused(panel: PatternDetectionPanel, dialog_answers: DialogRecorder) -> None:
    panel.run_pattern_detection()
    assert dialog_answers.titles("show_error") == ["Prerequisites Not Met"]
    assert not panel.explorer_running


def test_missing_profiling_files_are_listed_in_the_output(panel: PatternDetectionPanel) -> None:
    profile(panel, complete=False)
    panel.project_state.publish(ResultsChanged())
    published: List[PatternsChanged] = []
    panel.project_state.subscribe(PatternsChanged, published.append)
    panel.run_button.click()
    text = panel.console.text()
    assert "Data.xml" in text and "Missing required profiling data files" in text
    assert not panel.explorer_running and panel.run_button.text() == "Run Pattern Detection"
    assert panel.status.text() == "Pattern detection failed" and panel.status.color == widgets.STATUS_FAIL
    assert len(published) == 1


def test_a_run_shows_the_output_and_publishes_patterns_changed(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    panel.project_state.publish(ResultsChanged())
    published: List[PatternsChanged] = []
    panel.project_state.subscribe(PatternsChanged, published.append)
    with mock.patch.object(pattern_detection_panel, "explorer_command", lambda *_a, **_k: program("print('found')")):
        panel.run_button.click()
        assert panel.explorer_running and not panel.run_button.isEnabled()
        assert panel.run_button.text() == "⟳ Running..." and panel.stop_button.isEnabled()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
    text = panel.console.text()
    assert "  Patterns: reduction,doall\n" in text and "  Dependency data: default\n" in text
    assert "found" in text and "Pattern detection completed." in text
    assert panel.run_button.isEnabled() and panel.run_button.text() == "Run Pattern Detection"
    assert not panel.stop_button.isEnabled()
    assert panel.status.text() == "Pattern detection completed successfully"
    assert len(published) == 1


def test_a_second_start_while_running_is_refused(
    qtbot: QtBot, panel: PatternDetectionPanel, dialog_answers: DialogRecorder
) -> None:
    profile(panel)
    with mock.patch.object(
        pattern_detection_panel, "explorer_command", lambda *_a, **_k: program("import time; time.sleep(60)")
    ):
        panel.run_button.click()
        panel.run_pattern_detection()
        assert dialog_answers.titles("show_error") == ["Already Running"]
        panel.stop_button.click()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)


def test_stop_ends_the_run(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    with mock.patch.object(
        pattern_detection_panel, "explorer_command", lambda *_a, **_k: program("import time; time.sleep(60)")
    ):
        panel.run_button.click()
        qtbot.waitUntil(lambda: panel._explorer_job is not None)
        panel.stop_button.click()
        assert not panel.stop_button.isEnabled() and panel.status.text() == "Stopping pattern detection..."
        assert panel.status.color == widgets.STATUS_STOP
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
    # a stop is not a failure
    assert "Pattern detection completed." not in panel.console.text() and "Error:" not in panel.console.text()
    assert "Pattern detection stopped." in panel.console.text() and panel.status.text() == "Pattern detection stopped"


def test_a_failing_explorer_is_reported(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    run_with(panel, qtbot, "import sys; print('boom'); sys.exit(3)")
    assert "Error: Explorer exited with return code 3" in panel.console.text()
    assert panel.status.color == widgets.STATUS_FAIL and panel.run_button.isEnabled()


def test_an_explorer_that_cannot_start_is_reported(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    with mock.patch.object(pattern_detection_panel, "explorer_command", lambda *_a, **_k: ["/nonexistent/explorer"]):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
    assert "Error:" in panel.console.text() and panel.status.text() == "Pattern detection failed"


def test_a_visualized_run_is_a_job_with_a_working_stop_button(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    panel.visualize_check.setChecked(True)
    requests: List[ExplorerRequest] = []

    def command(request: ExplorerRequest, *_a: Any, **_k: Any) -> List[str]:
        requests.append(request)
        return program("import time; time.sleep(60)")

    with (
        mock.patch.object(pattern_detection_panel, "visualizer_available", lambda: True),
        mock.patch.object(pattern_detection_panel, "explorer_command", command),
    ):
        panel.run_button.click()
        assert panel.stop_button.isEnabled()
        qtbot.waitUntil(lambda: panel._explorer_job is not None)
        panel.stop_button.click()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
    assert requests[0].visualize and "Graph visualization: enabled" in panel.console.text()


def test_a_visualized_run_without_the_gui_package_does_not_start(
    panel: PatternDetectionPanel, dialog_answers: DialogRecorder
) -> None:
    profile(panel)
    panel.visualize_check.setChecked(True)
    with mock.patch.object(pattern_detection_panel, "visualizer_available", lambda: False):
        panel.run_button.click()
    assert dialog_answers.titles("show_warning") == ["Graph Visualization Not Available"]
    assert "discopop_gui" in panel.console.text()
    assert not panel.explorer_running and panel.run_button.isEnabled()


def test_the_no_suggestions_label_follows_the_result(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    explorer_dir = Path(panel.arguments.dot_dp, "explorer")
    explorer_dir.mkdir()
    panel.refresh()
    assert not panel.no_suggestions_label.isHidden()
    (explorer_dir / "patterns.json").write_text(json.dumps({"patterns": {"do_all": [{"id": 1}]}}))
    panel.refresh()
    assert panel.no_suggestions_label.isHidden()


def test_suggestions_enable_browse_and_vscode(panel: PatternDetectionPanel) -> None:
    patch_dir = Path(panel.arguments.dot_dp, "patch_generator", "1")
    patch_dir.mkdir(parents=True)
    (patch_dir / "a.patch").write_text("")
    panel.project_state.publish(PatternsChanged())
    assert panel.browse_button.isEnabled() and panel.vscode_button.isEnabled()
    with mock.patch.object(suggestion_browser, "open_suggestion_browser") as opened:
        panel.browse_button.click()
    assert opened.call_args.args == (panel, panel.arguments.dot_dp)


def test_vscode_opens_the_project(panel: PatternDetectionPanel) -> None:
    with (
        mock.patch.object(pattern_detection_panel, "find_code_executable", lambda: "code"),
        mock.patch.object(pattern_detection_panel, "open_project") as opened,
    ):
        panel.open_in_vscode()
    opened.assert_called_once_with("code", panel.arguments.dot_dp)
    assert panel.status.text() == "Opening project in VSCode..."


def test_vscode_problems_are_reported(panel: PatternDetectionPanel, dialog_answers: DialogRecorder) -> None:
    with mock.patch.object(pattern_detection_panel, "find_code_executable", lambda: None):
        panel.open_in_vscode()
    with (
        mock.patch.object(pattern_detection_panel, "find_code_executable", lambda: "code"),
        mock.patch.object(pattern_detection_panel, "open_project", side_effect=OSError("denied")),
    ):
        panel.open_in_vscode()
    assert dialog_answers.titles("show_error") == ["VSCode Not Found", "Failed to open VSCode"]
    assert "denied" in dialog_answers.messages("show_error")[1]


def test_cancel_jobs_stops_a_running_detection(qtbot: QtBot, panel: PatternDetectionPanel) -> None:
    profile(panel)
    panel.cancel_jobs()  # nothing running: no error
    with mock.patch.object(
        pattern_detection_panel, "explorer_command", lambda *_a, **_k: program("import time; time.sleep(60)")
    ):
        panel.run_button.click()
        qtbot.waitUntil(lambda: panel._explorer_job is not None)
        panel.cancel_jobs()
        qtbot.waitUntil(lambda: not panel.explorer_running, timeout=20000)
