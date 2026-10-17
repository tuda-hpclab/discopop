# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import sys
import threading
from pathlib import Path
from typing import Any, List, Tuple, Type, TypeVar
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import autotuning_panel
from discopop_library.ProjectManager.qt_gui.panels.autotuning_panel import AutotuningPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.jobs import CancelPolicy
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)

E = TypeVar("E")


class FakeTabs:
    def __init__(self) -> None:
        self.enabled: List[Tuple[str, bool, str]] = []

    def show_tab(self, name: str) -> None:
        pass

    def current_tab(self) -> str:
        return ""

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        self.enabled.append((name, enabled, tooltip))

    def set_tab_title(self, name: str, title: str) -> None:
        pass


class Fixture:
    def __init__(self, panel: AutotuningPanel, tabs: FakeTabs, status: StatusLine) -> None:
        self.panel = panel
        self.tabs = tabs
        self.status = status
        self.events: List[object] = []

    @property
    def dot_dp(self) -> Path:
        return Path(self.panel.arguments.dot_dp)

    def listen(self, event_type: Type[E]) -> None:
        self.panel.project_state.subscribe(event_type, self.events.append)


def program(code: str) -> List[str]:
    return [sys.executable, "-u", "-c", code]


@pytest.fixture
def fixture(qtbot: QtBot, tmp_path: Path) -> Fixture:
    status = StatusLine()
    qtbot.addWidget(status)
    tabs = FakeTabs()
    state = ProjectState()
    state.current_config = "tiny"
    panel = AutotuningPanel(make_arguments(tmp_path), state, status, tabs)
    qtbot.addWidget(panel)
    return Fixture(panel, tabs, status)


def add_patches(fixture: Fixture, *ids: str) -> None:
    for sid in ids:
        directory = fixture.dot_dp / "patch_generator" / sid
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "a.patch").write_text("x")


def run_with(fixture: Fixture, qtbot: QtBot, code: str, finished: bool = True) -> None:
    with mock.patch.object(autotuning_panel, "autotuner_command", lambda *_a, **_k: program(code)):
        fixture.panel.run()
        if finished:
            qtbot.waitUntil(lambda: not fixture.panel.running, timeout=20000)


def test_defaults(fixture: Fixture) -> None:
    panel = fixture.panel
    assert panel.run_button.isEnabled() and not panel.stop_button.isEnabled()
    assert panel.threads.value() == widgets.THREAD_AUTO and panel.repetitions.value() == 1
    assert [t for t, check in panel.hotspot_type_checks.items() if check.isChecked()] == ["yes"]
    assert panel.algorithm_combo.currentText() == "Hotspot-guided region descent"
    assert panel.log_level.currentText() == "WARNING"
    assert panel.mode() == "search"
    assert panel.config_label.text() == "tiny"
    assert panel.suggestions_label.text() == "Autotuner not yet executed"
    assert panel.suggestions_count_label.text() == "No suggestions available"
    assert not panel.browse_button.isEnabled()


def test_the_tab_is_enabled_by_profiling_data_and_patches(fixture: Fixture) -> None:
    fixture.panel.update_tab_state()
    assert fixture.tabs.enabled[-1] == ("Autotuning", False, autotuning_panel.TAB_DISABLED_TOOLTIP)
    assert "Pattern Detection needs to be executed first" in fixture.tabs.enabled[-1][2]
    (fixture.dot_dp / "profiler").mkdir()
    fixture.panel.project_state.publish(PatternsChanged())
    assert fixture.tabs.enabled[-1][1] is False
    add_patches(fixture, "1")
    fixture.panel.project_state.publish(PatternsChanged())
    assert fixture.tabs.enabled[-1] == ("Autotuning", True, "")
    fixture.panel.project_state.publish(HotspotsChanged())
    assert fixture.tabs.enabled[-1][1] is True


def test_the_algorithm_hint_follows_the_hotspot_results(fixture: Fixture) -> None:
    panel = fixture.panel
    assert "run Hotspot Detection first" in panel.algorithm_hint.text()
    assert widgets.STATUS_FAIL in panel.algorithm_hint.styleSheet()
    hotspots = fixture.dot_dp / "hotspot_detection"
    hotspots.mkdir()
    (hotspots / "Hotspots.json").write_text(json.dumps({"loops": [{"hotness": "YES", "file_id": 1, "start_line": 3}]}))
    with mock.patch.object(autotuning_panel, "hotspots_available_for_explorer", lambda _dot_dp: True):
        fixture.panel.project_state.publish(HotspotsChanged())
    assert "Reproducible across runs" in panel.algorithm_hint.text()
    panel.algorithm_combo.setCurrentText("Greedy combination")
    assert panel.algorithm_hint.text() == ""


def test_the_evaluate_mode_swaps_the_selectors_and_disables_the_algorithm(fixture: Fixture, qtbot: QtBot) -> None:
    panel = fixture.panel
    panel.show()
    assert panel.search_space_container.isVisible() and not panel.evaluate_container.isVisible()
    assert panel.algorithm_combo.isEnabled()
    panel.evaluate_mode_radio.click()
    assert panel.mode() == "evaluate"
    assert panel.evaluate_container.isVisible() and not panel.search_space_container.isVisible()
    assert not panel.algorithm_combo.isEnabled()
    panel.search_mode_radio.click()
    assert panel.algorithm_combo.isEnabled() and panel.search_space_container.isVisible()


def test_the_suggestion_overview_counts_the_active_selector(fixture: Fixture) -> None:
    panel = fixture.panel
    add_patches(fixture, "1", "2", "3")
    fixture.panel.project_state.publish(AutotuningChanged())
    assert panel.suggestions_count_label.text() == "3 of 3 selected"
    assert panel.browse_button.isEnabled()
    panel.search_space_selector.entry.setText("1")
    panel.search_space_selector.apply_button.click()
    assert panel.suggestions_count_label.text() == "1 of 3 selected"
    panel.evaluate_mode_radio.click()
    assert panel.suggestions_count_label.text() == "3 of 3 selected"


def test_the_browse_button_opens_the_suggestion_browser(fixture: Fixture) -> None:
    add_patches(fixture, "1")
    fixture.panel.project_state.publish(AutotuningChanged())
    with mock.patch.object(autotuning_panel, "open_suggestion_browser") as opened:
        fixture.panel.browse_button.click()
    opened.assert_called_once_with(fixture.panel, str(fixture.dot_dp))


def test_the_autotuner_results_are_shown_and_follow_the_configuration(fixture: Fixture) -> None:
    panel = fixture.panel
    results = fixture.dot_dp / "auto_tuner" / "results.json"
    results.parent.mkdir()
    results.write_text(json.dumps({"tiny": {"applied_suggestions": [10, 2]}, "other": {"applied_suggestions": []}}))
    fixture.listen(AutotuningChanged)
    panel.project_state.publish(AutotuningFinished())
    assert panel.suggestions_label.text() == "2, 10"
    panel.project_state.current_config = "other"
    panel.project_state.publish(ConfigChanged("other"))
    assert panel.config_label.text() == "other"
    assert panel.suggestions_label.text() == "No suggestions selected"
    panel.project_state.current_config = None
    panel.project_state.publish(ConfigChanged(None))
    assert panel.config_label.text() == "(none selected)"


def test_the_request_is_read_from_the_widgets(fixture: Fixture) -> None:
    panel = fixture.panel
    add_patches(fixture, "1", "2", "3")
    panel.project_state.publish(AutotuningChanged())
    panel.threads.setCurrentText("4")
    panel.repetitions.setValue(3)
    panel.hotspot_type_checks["maybe"].setChecked(True)
    panel.algorithm_combo.setCurrentText("Greedy combination")
    panel.log_level.setCurrentText("INFO")
    panel.search_space_selector.entry.setText("1,3")
    panel.search_space_selector.apply_button.click()
    request = panel._snapshot_request()
    assert (request.configuration, request.hotspot_types, request.threads, request.repetitions) == (
        "tiny",
        "yes,maybe",
        "4",
        3,
    )
    assert (request.algorithm, request.log_level, request.mode) == ("4", "INFO", "search")
    assert request.search_space_ids == ("1", "3") and request.evaluate_ids == ()
    panel.evaluate_mode_radio.click()
    panel.evaluate_selector.entry.setText("2")
    panel.evaluate_selector.apply_button.click()
    request = panel._snapshot_request()
    assert request.mode == "evaluate" and request.evaluate_ids == ("2",) and request.search_space_ids is None
    for check in panel.hotspot_type_checks.values():
        check.setChecked(False)
    assert panel._snapshot_request().hotspot_types == "yes,no,maybe"


def test_running_without_a_configuration_is_refused(fixture: Fixture, dialog_answers: DialogRecorder) -> None:
    fixture.panel.project_state.current_config = None
    fixture.panel.run()
    assert dialog_answers.titles("show_error") == ["No Configuration Selected"]
    assert not fixture.panel.running


def test_a_second_run_is_refused(fixture: Fixture, dialog_answers: DialogRecorder) -> None:
    fixture.panel.running = True
    fixture.panel.run()
    assert dialog_answers.titles("show_error") == ["Already Running"]


def test_success_and_progress(fixture: Fixture, qtbot: QtBot) -> None:
    panel = fixture.panel
    fixture.listen(AutotuningFinished)
    seen_threads: List[Any] = []
    original = panel._on_progress

    def progress(event: Any) -> None:
        seen_threads.append(threading.current_thread() is threading.main_thread())
        original(event)

    panel.repetitions.setValue(2)
    code = (
        "print('working')\n"
        'print(\'@@AT_PROGRESS {"event": "baseline", "thread_count": 2}\')\n'
        'print(\'@@AT_PROGRESS {"event": "measurement", "index": 1, "suggestions": [3], "speedup": 1.5, '
        '"runtime": 2.0, "return_code": 0, "valid": true, "tsan": true}\')\n'
    )
    with mock.patch.object(panel, "_on_progress", progress):
        run_with(fixture, qtbot, code, finished=False)
        assert not panel.run_button.isEnabled() and panel.run_button.text() == "⟳ Running..."
        assert panel.stop_button.isEnabled()
        qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Starting autotuning..." in console and "  Repetitions: 2" in console
    assert "working" in console and "Autotuning completed." in console
    assert "@@AT_PROGRESS" not in console
    assert seen_threads == [True, True]
    assert panel.progress_model.best_speedup() == 1.5
    assert fixture.events == [AutotuningFinished()]
    assert fixture.status.text() == "Autotuning completed successfully" and fixture.status.color == widgets.STATUS_OK
    assert panel.run_button.isEnabled() and panel.run_button.text() == "Run Autotuning"
    assert not panel.stop_button.isEnabled()


def test_failure(fixture: Fixture, qtbot: QtBot) -> None:
    fixture.listen(AutotuningFinished)
    run_with(fixture, qtbot, "import sys; sys.exit(3)")
    assert "Error: Autotuner exited with return code 3" in fixture.panel.console.text()
    assert fixture.status.text() == "Autotuning failed" and fixture.status.color == widgets.STATUS_FAIL
    assert fixture.events == []
    assert fixture.panel.run_button.isEnabled()


def test_a_command_that_cannot_start(fixture: Fixture, qtbot: QtBot) -> None:
    with mock.patch.object(autotuning_panel, "autotuner_command", lambda *_a, **_k: ["/nonexistent/autotuner"]):
        fixture.panel.run()
        qtbot.waitUntil(lambda: not fixture.panel.running, timeout=20000)
    assert "Error:" in fixture.panel.console.text()
    assert fixture.status.text() == "Autotuning failed"


def test_not_applied_measurements_are_announced_and_flagged(fixture: Fixture, qtbot: QtBot) -> None:
    panel = fixture.panel
    code = (
        'print(\'@@AT_PROGRESS {"event": "measurement", "index": 1, "suggestions": [4], '
        '"failed_suggestions": [4], "application_failed": true}\')\n'
    )
    panel.show()
    run_with(fixture, qtbot, code)
    assert "Suggestion application failed for 4 - configuration skipped, not measured." in panel.console.text()
    assert panel.warning_label.isVisible() and "could not be patched" in panel.warning_label.text()
    assert fixture.status.text() == "⚠ Autotuning completed - 1 configuration(s) could not be patched"
    panel.run_button.click()  # a new run starts with a fresh plot and no banner
    assert not panel.warning_label.isVisible()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)


def test_the_last_run_is_shown_on_open(qtbot: QtBot, tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    progress = Path(arguments.dot_dp, "auto_tuner", "progress.jsonl")
    progress.parent.mkdir(parents=True)
    progress.write_text(
        json.dumps(
            {"event": "measurement", "index": 1, "suggestions": [1], "speedup": 2.0, "valid": True, "tsan": True}
        )
        + "\n"
    )
    panel = AutotuningPanel(arguments, ProjectState(), StatusLine(), FakeTabs())
    qtbot.addWidget(panel)
    assert panel.progress_model.best_speedup() == 2.0
    assert any(label.text() != "—" for label in panel.tile_values)


def test_stop(fixture: Fixture, qtbot: QtBot) -> None:
    panel = fixture.panel
    fixture.listen(AutotuningFinished)
    fixture.listen(ResultsChanged)
    ready = threading.Event()
    original = panel._on_job_event

    def watching(event: Any) -> None:
        if getattr(event, "line", None) == "ready":
            ready.set()
        original(event)

    # finishes gracefully on SIGINT, as the autotuner does
    code = "import time\nprint('ready', flush=True)\ntry:\n    time.sleep(60)\nexcept KeyboardInterrupt:\n    pass\n"
    with mock.patch.object(panel, "_on_job_event", watching):
        run_with(fixture, qtbot, code, finished=False)
        qtbot.waitUntil(ready.is_set, timeout=20000)
        panel.stop_button.click()
        assert fixture.status.text() == "Stopping autotuning..." and fixture.status.color == widgets.STATUS_STOP
        assert not panel.stop_button.isEnabled()
        qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Autotuning stopped." in console and "Error" not in console
    assert fixture.status.text() == "Autotuning stopped" and fixture.status.color == widgets.STATUS_IDLE
    assert fixture.events == [ResultsChanged(), AutotuningFinished()]
    assert panel.run_button.isEnabled()


def test_the_autotuner_is_stopped_with_its_process_group(fixture: Fixture) -> None:
    started: List[Any] = []

    def recording_runner(spec: Any, _events: Any) -> Any:
        started.append(spec)
        return mock.MagicMock()

    with mock.patch.object(autotuning_panel, "JobRunner", recording_runner):
        fixture.panel.run()
    assert [(spec.cancel_policy, spec.new_session) for spec in started] == [(CancelPolicy.SIGINT_GROUP, True)]
    fixture.panel.running = False


def test_a_run_keeps_the_run_button_disabled_when_the_project_changes(fixture: Fixture, qtbot: QtBot) -> None:
    panel = fixture.panel
    ready = threading.Event()
    original = panel._on_job_event

    def watching(event: Any) -> None:
        if getattr(event, "line", None) == "ready":
            ready.set()
        original(event)

    code = "import time\nprint('ready', flush=True)\ntry:\n    time.sleep(60)\nexcept KeyboardInterrupt:\n    pass\n"
    with mock.patch.object(panel, "_on_job_event", watching):
        run_with(fixture, qtbot, code, finished=False)
        qtbot.waitUntil(ready.is_set, timeout=20000)
        panel.project_state.publish(PatternsChanged())
        assert not panel.run_button.isEnabled()
        panel.cancel_jobs()
        qtbot.waitUntil(lambda: not panel.running, timeout=20000)


def test_cancel_jobs_without_a_job_does_nothing(fixture: Fixture) -> None:
    fixture.panel.cancel_jobs()
    assert not fixture.panel.running
