# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import execute_panel as execute_panel_module
from discopop_library.ProjectManager.qt_gui.panels.execute_panel import ExecutePanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    ConfigurationsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)

ExecuteResult = Optional[Tuple[int, float, str, str]]


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> ExecutePanel:
    arguments = make_arguments(tmp_path)
    configs = Path(arguments.project_config_dir)
    (configs / "tiny").mkdir()
    (configs / "tiny" / "compile.sh").write_text("true\n")
    (configs / "tiny" / "execute.sh").write_text("true\n")
    (configs / "seq_settings.json").write_text("{}")
    (configs / "dp_settings.json").write_text("{}")
    status = StatusLine()
    qtbot.addWidget(status)
    created = ExecutePanel(arguments, ProjectState(), status)
    qtbot.addWidget(created)
    return created


def select(panel: ExecutePanel, config: Optional[str] = "tiny") -> None:
    panel.project_state.current_config = config
    panel.project_state.publish(ConfigChanged(config))


def add_patches(panel: ExecutePanel, *ids: str) -> None:
    for sid in ids:
        directory = Path(panel.arguments.dot_dp, "patch_generator", sid)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "p.patch").write_text("diff")


def write_autotuner_results(panel: ExecutePanel, applied: List[Any]) -> None:
    path = Path(panel.arguments.dot_dp, "auto_tuner", "results.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tiny": {"applied_suggestions": applied}}))


def recording_run(seen: List[Any]) -> Any:
    """A stand-in for ``run_execution`` that records its request and skips nothing."""

    def run(_arguments: Any, request: Any, _ctx: Any) -> List[Any]:
        seen.append(request)
        return []

    return run


def run_and_wait(qtbot: QtBot, panel: ExecutePanel, results: List[ExecuteResult]) -> List[Tuple[Any, ...]]:
    calls: List[Tuple[Any, ...]] = []

    def fake_execute_configuration(*args: Any, **kwargs: Any) -> ExecuteResult:
        calls.append(args)
        assert kwargs.get("process_started_callback") is not None  # the stop button depends on it
        return results.pop(0)

    with mock.patch.object(execution_run, "execute_configuration", fake_execute_configuration):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    return calls


# ── the modes and the buttons ────────────────────────────────────────────────


def test_without_a_configuration_nothing_can_be_run(panel: ExecutePanel) -> None:
    assert not panel.run_button.isEnabled() and not panel.prepare_pattern_detection_button.isEnabled()
    assert not panel.stop_execution_button.isEnabled()
    assert all(not check.isEnabled() for check in panel.mode_checks.values())
    assert panel.mode_checks["seq"].isChecked()
    assert panel.suggestions_count_label.text() == "No suggestions available"
    assert panel.autotuner_suggestions_info_label.text() == "Autotuner not yet executed"


def test_the_modes_of_the_selected_configuration_are_offered(panel: ExecutePanel) -> None:
    panel.console.append_text("old output")
    select(panel)
    assert {mode: check.isEnabled() for mode, check in panel.mode_checks.items()} == {
        "seq": True,
        "dp": True,
        "hd": False,
        "par": False,
    }
    assert panel.run_button.isEnabled() and panel.prepare_pattern_detection_button.isEnabled()
    # a mode that gets unavailable is unchecked; a missing configuration clears the output again
    panel.mode_checks["dp"].setChecked(True)
    os.remove(Path(panel.arguments.project_config_dir, "dp_settings.json"))
    panel.project_state.publish(ConfigurationsChanged())
    assert not panel.mode_checks["dp"].isEnabled() and not panel.mode_checks["dp"].isChecked()
    assert panel.console.text() == "old output"
    select(panel, None)
    assert not panel.run_button.isEnabled() and panel.console.text() == ""
    assert panel.mode_checks["seq"].isChecked() and not panel.mode_checks["seq"].isEnabled()


def test_a_new_script_enables_a_mode_on_configurations_changed(panel: ExecutePanel) -> None:
    select(panel)
    assert not panel.mode_checks["par"].isEnabled()
    Path(panel.arguments.project_config_dir, "par_settings.json").write_text("{}")
    panel.project_state.publish(ConfigurationsChanged())
    assert panel.mode_checks["par"].isEnabled()


def test_the_execution_time_summary_follows_the_stored_setting(panel: ExecutePanel) -> None:
    select(panel)
    assert panel.execution_time_summary_label.text() == "wall clock of execute.sh"
    Path(panel.arguments.project_config_dir, "tiny", "execution_time.json").write_text(
        json.dumps({"enabled": True, "regex": "t=(.*)"})
    )
    panel.project_state.publish(ResultsChanged())
    assert panel.execution_time_summary_label.text() == "from the console output (see Editor -> execute.sh)"
    panel.arguments.execution_time_regex = ""
    panel.project_state.publish(ConfigurationsChanged())
    assert panel.execution_time_summary_label.text() == "wall clock of execute.sh (forced by --execution-time-regex)"
    panel.arguments.execution_time_regex = "x=(.*)"
    select(panel)
    assert panel.execution_time_summary_label.text() == "from the console output (forced by --execution-time-regex)"


def test_the_timeouts_are_passed_on_and_zero_disables_them(panel: ExecutePanel) -> None:
    assert panel.timeouts() == (3600.0, 3600.0, 3600.0)
    panel.timeout_execution_spin.setValue(0)
    panel.timeout_validation_spin.setValue(5)
    assert panel.timeouts() == (0.0, 3600.0, 5.0)


def test_the_defaults(panel: ExecutePanel) -> None:
    assert panel.thread_spin.value() == max(1, (os.cpu_count() or 4) // 2)
    assert panel.repetitions_spin.value() == 3
    assert panel.log_level_combo.currentText() == "WARNING"
    assert not panel.inplace_check.isChecked() and not panel.skip_cleanup_check.isChecked()
    assert panel.suggestions_mode() == "none" and panel.label_prefix_edit.text() == ""


# ── the suggestions ──────────────────────────────────────────────────────────


def test_manual_suggestions_need_patches(panel: ExecutePanel) -> None:
    select(panel)
    assert not panel.apply_suggestions_rb.isEnabled() and not panel.browse_edit_suggestions_button.isEnabled()
    add_patches(panel, "1", "2", "10")
    panel.project_state.publish(PatternsChanged())
    assert panel.apply_suggestions_rb.isEnabled() and panel.browse_edit_suggestions_button.isEnabled()
    assert panel.suggestions_count_label.text() == "3 of 3 selected"
    assert not panel.execute_suggestion_selector.isEnabled()
    panel.set_suggestions_mode("manual")
    assert panel.execute_suggestion_selector.isEnabled()
    panel.execute_suggestion_selector.set_selected_ids(["2"])
    assert panel.suggestions_count_label.text() == "1 of 3 selected"
    # the patches vanish: the manual mode falls back to none
    for patch in Path(panel.arguments.dot_dp, "patch_generator").glob("*/p.patch"):
        patch.unlink()
    panel.project_state.publish(PatternsChanged())
    assert panel.suggestions_mode() == "none" and not panel.apply_suggestions_rb.isEnabled()


def test_the_autotuner_selection_is_shown_and_selectable(panel: ExecutePanel) -> None:
    select(panel)
    assert not panel.apply_autotuner_suggestions_rb.isEnabled()
    write_autotuner_results(panel, [])
    panel.project_state.publish(AutotuningFinished())
    assert panel.autotuner_suggestions_info_label.text() == "No suggestions selected"
    assert panel.apply_autotuner_suggestions_rb.isEnabled()
    write_autotuner_results(panel, ["10", "2"])
    panel.project_state.publish(AutotuningFinished())
    assert panel.autotuner_suggestions_info_label.text() == "Suggestion IDs: 2, 10"
    panel.set_suggestions_mode("autotuner")
    assert panel.label_prefix_edit.text() == "auto"
    # leaving the autotuner mode removes the prefix it set, but not one the user typed
    panel.set_suggestions_mode("none")
    assert panel.label_prefix_edit.text() == ""
    panel.set_suggestions_mode("autotuner")
    panel.label_prefix_edit.setText("mine")
    panel.set_suggestions_mode("none")
    assert panel.label_prefix_edit.text() == "mine"
    # without a selected configuration the autotuner mode is not available
    panel.set_suggestions_mode("autotuner")
    select(panel, None)
    assert panel.suggestions_mode() == "none" and not panel.apply_autotuner_suggestions_rb.isEnabled()


def test_refreshing_the_suggestions_tells_the_autotuning_tab_without_an_echo(panel: ExecutePanel) -> None:
    seen: List[object] = []
    panel.project_state.subscribe(AutotuningChanged, seen.append)
    select(panel)
    assert len(seen) == 1
    panel.project_state.publish(AutotuningChanged())  # another panel's change: refresh, but do not answer
    assert len(seen) == 2


def test_browse_edit_opens_the_suggestion_browser(panel: ExecutePanel) -> None:
    add_patches(panel, "1")
    select(panel)
    with mock.patch.object(execute_panel_module, "open_suggestion_browser") as open_browser:
        panel.browse_edit_suggestions_button.click()
    open_browser.assert_called_once_with(panel, panel.arguments.dot_dp)


# ── running ──────────────────────────────────────────────────────────────────


def test_a_successful_run_is_reported_on_the_main_thread(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    events: List[str] = []
    panel.project_state.subscribe(ConfigurationsChanged, lambda _e: events.append("configurations"))
    panel.project_state.subscribe(ResultsChanged, lambda _e: events.append("results"))
    handler_threads: List[int] = []
    panel.console.textChanged.connect(lambda: handler_threads.append(threading.get_ident()))
    calls = run_and_wait(qtbot, panel, [(0, 0.5, "compiled", ""), (0, 1.25, "result", "")])
    assert len(calls) == 2  # compile, then execute
    output = panel.console.text()
    assert "=== SEQ mode ===" in output
    assert "Compilation succeeded (0.50s)" in output
    assert "stdout: compiled" in output
    assert "Execution succeeded (1.25s)" in output
    assert "stdout: result" in output
    assert output.rstrip().endswith("=== Execution complete ===")
    assert set(handler_threads) == {threading.get_ident()}
    assert panel.status.text() == "Ready" and panel.status.color == widgets.STATUS_IDLE
    assert events == ["configurations", "results"]
    assert panel.run_button.isEnabled() and panel.run_button.text() == "Run"
    assert panel.prepare_pattern_detection_button.isEnabled() and not panel.stop_execution_button.isEnabled()
    assert not panel.inplace_check.isChecked()  # in-place has to be asked for again


def test_the_buttons_during_a_run(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    release = threading.Event()
    started = threading.Event()

    def blocking(*_args: Any, **_kwargs: Any) -> ExecuteResult:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", blocking):
        panel.run_button.click()
        assert started.wait(20)
        assert not panel.run_button.isEnabled() and panel.run_button.text() == "⟳ Running..."
        assert panel.stop_execution_button.isEnabled() and not panel.prepare_pattern_detection_button.isEnabled()
        qtbot.waitUntil(lambda: panel.status.text() == "⏳ Compiling...", timeout=5000)
        select(panel)  # a change of the selection must not re-enable the buttons of a running job
        assert not panel.run_button.isEnabled()
        release.set()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert panel.run_button.isEnabled()


def test_the_options_reach_the_work(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    add_patches(panel, "1", "2")
    panel.project_state.publish(PatternsChanged())
    panel.set_suggestions_mode("manual")
    panel.execute_suggestion_selector.set_selected_ids(["2"])
    panel.thread_spin.setValue(1)
    panel.repetitions_spin.setValue(5)
    panel.label_prefix_edit.setText("lbl")
    panel.timeout_execution_spin.setValue(11)
    panel.timeout_compilation_spin.setValue(12)
    panel.timeout_validation_spin.setValue(13)
    panel.skip_cleanup_check.setChecked(True)
    panel.log_level_combo.setCurrentText("ERROR")
    seen: List[Any] = []

    def fake_run(arguments: Any, request: Any, ctx: Any) -> List[Any]:
        seen.append(request)
        return []

    with mock.patch.object(execute_panel_module, "run_execution", fake_run):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert seen[0] == execution_run.ExecutionRequest(
        configuration="tiny",
        modes=("seq",),
        inplace=False,
        skip_cleanup=True,
        thread_count=1,
        label_prefix="lbl",
        timeout_execution=11,
        timeout_compilation=12,
        timeout_validation=13,
        repetitions=5,
        log_level="ERROR",
        suggestion_ids=("2",),
    )


def test_the_autotuner_selection_is_applied(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    write_autotuner_results(panel, ["3", "1"])
    panel.project_state.publish(AutotuningFinished())
    panel.set_suggestions_mode("autotuner")
    seen: List[Any] = []
    with mock.patch.object(execute_panel_module, "run_execution", recording_run(seen)):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert seen[0].suggestion_ids == ("3", "1") and seen[0].label_prefix == "auto"


def test_without_a_mode_nothing_starts(panel: ExecutePanel, dialog_answers: DialogRecorder) -> None:
    select(panel)
    panel.mode_checks["seq"].setChecked(False)
    panel.run_button.click()
    assert dialog_answers.titles("show_warning") == ["No mode selected"]
    assert not panel.is_running()


def test_inplace_with_suggestions_asks_first(qtbot: QtBot, panel: ExecutePanel, dialog_answers: DialogRecorder) -> None:
    select(panel)
    add_patches(panel, "1")
    panel.project_state.publish(PatternsChanged())
    panel.set_suggestions_mode("manual")
    panel.inplace_check.setChecked(True)
    dialog_answers.answer("ask_yes_no", False, True)
    panel.run_button.click()
    assert not panel.is_running() and dialog_answers.titles("ask_yes_no") == ["Dangerous Configuration"]
    calls = run_and_wait(qtbot, panel, [(0, 0.1, "", ""), (0, 0.1, "", "")])
    assert len(calls) == 2
    assert "Note: Apply suggestions is ignored in inplace mode." in panel.console.text()


def test_a_thread_count_above_the_cpu_count_only_warns(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    panel.thread_spin.setValue((os.cpu_count() or 4) + 1)
    seen: List[Any] = []
    with mock.patch.object(execute_panel_module, "run_execution", recording_run(seen)):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert seen[0].thread_count == (os.cpu_count() or 4) + 1


def test_a_failing_compilation_skips_the_execution(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    calls = run_and_wait(qtbot, panel, [(2, 0.1, "", "error")])
    assert len(calls) == 1
    assert "Compilation failed (return code: 2)" in panel.console.text()
    assert "Execution succeeded" not in panel.console.text()


def test_a_crash_of_the_worker_does_not_leave_the_buttons_disabled(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)

    def crashing(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("boom")

    with mock.patch.object(execution_run, "execute_configuration", crashing):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert "Error: boom" in panel.console.text()
    assert panel.run_button.isEnabled() and panel.run_button.text() == "Run"
    assert not panel.stop_execution_button.isEnabled()


def test_the_stop_button_cancels_the_run(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    panel.mode_checks["dp"].setChecked(True)  # two modes: the second one must not start after the stop
    started = threading.Event()
    release = threading.Event()

    def blocking(*_args: Any, **_kwargs: Any) -> ExecuteResult:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", blocking):
        panel.run_button.click()
        assert started.wait(20)
        panel.stop_execution_button.click()
        assert panel.status.text() == "Stopping execution..." and panel.status.color == widgets.STATUS_STOP
        assert not panel.stop_execution_button.isEnabled()
        release.set()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    output = panel.console.text()
    assert "=== SEQ mode ===" in output and "=== DP mode ===" not in output
    assert "Execution stopped by user." in output


def test_cancel_jobs_cancels_a_running_execution(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    started = threading.Event()
    release = threading.Event()

    def blocking(*_args: Any, **_kwargs: Any) -> ExecuteResult:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", blocking):
        panel.run_button.click()
        assert started.wait(20)
        job = panel._job
        assert job is not None
        panel.cancel_jobs()
        assert job.cancel_requested
        release.set()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    panel.cancel_jobs()  # nothing running: no error


def test_the_log_is_shown_in_the_console_during_the_run_and_restored_after(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    panel.inplace_check.setChecked(True)
    root_handlers = logging.getLogger().handlers[:]
    panel.log_level_combo.setCurrentText("INFO")
    run_and_wait(qtbot, panel, [(0, 0.1, "", ""), (0, 0.1, "", "")])
    assert "[Execute] INFO: Starting execution of configuration: tiny" in panel.console.text()
    assert logging.getLogger().handlers == root_handlers


def test_skipped_runs_are_reported(qtbot: QtBot, panel: ExecutePanel, dialog_answers: DialogRecorder) -> None:
    select(panel)
    failure = SimpleNamespace(summary=lambda: "patch 1 failed")
    with mock.patch.object(execute_panel_module, "run_execution", lambda a, r, c: [("seq", failure)]):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert dialog_answers.titles("show_warning") == ["Suggestion Application Failed"]
    assert "seq: patch 1 failed" in dialog_answers.messages("show_warning")[0]
    assert "1 run(s) were SKIPPED" in panel.console.text()
    assert panel.status.text() == "⚠ Suggestion application failed" and panel.status.color == widgets.STATUS_FAIL


# ── preparing the pattern detection ──────────────────────────────────────────


def test_prepare_pattern_detection_runs_dp_in_place(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    results: List[ExecuteResult] = [(0, 0.5, "", ""), (0, 1.0, "", "")]
    published: List[str] = []
    panel.project_state.subscribe(ResultsChanged, lambda _e: published.append("results"))
    calls: List[Tuple[Any, ...]] = []

    def fake(*args: Any, **_kwargs: Any) -> ExecuteResult:
        calls.append(args)
        return results.pop(0)

    with mock.patch.object(execution_run, "execute_configuration", fake):
        panel.prepare_pattern_detection_button.click()
        assert panel.prepare_pattern_detection_button.text() == "⟳ Preparing..."
        assert not panel.run_button.isEnabled() and panel.stop_execution_button.isEnabled()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    output = panel.console.text()
    assert "Compiling in 'dp' mode with inplace execution..." in output
    assert output.rstrip().endswith("=== Pattern detection preparation complete ===")
    assert calls[0][1] == panel.arguments.project_root and calls[0][3].endswith("dp_settings.json")
    assert calls[0][0].execute_inplace is True and calls[0][0].log_level == "INFO"
    assert panel.prepare_pattern_detection_button.text() == "Prepare Pattern Detection"
    assert panel.run_button.isEnabled() and panel.status.text() == "Ready"
    assert published == ["results"]


def test_a_failing_preparation_is_reported(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    with mock.patch.object(execution_run, "execute_configuration", lambda *a, **k: (1, 0.1, "", "")):
        panel.prepare_pattern_detection_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert "Compilation failed (return code: 1)" in panel.console.text()
    assert "=== Pattern detection preparation failed ===" in panel.console.text()
    assert panel.status.text() == "Pattern detection preparation failed"
    assert panel.status.color == widgets.STATUS_FAIL
    assert panel.run_button.isEnabled()


def test_the_preparation_can_be_stopped(qtbot: QtBot, panel: ExecutePanel) -> None:
    select(panel)
    started = threading.Event()
    release = threading.Event()

    def blocking(*_args: Any, **_kwargs: Any) -> ExecuteResult:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", blocking):
        panel.prepare_pattern_detection_button.click()
        assert started.wait(20)
        panel.stop_execution_button.click()
        release.set()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert "preparation stopped by user" in panel.console.text()
    assert panel.status.text() == "Ready"
