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
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.PatchRepair import llm_backends
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import patch_repair_panel
from discopop_library.ProjectManager.qt_gui.panels.patch_repair_panel import PatchRepairPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.jobs import CancelPolicy
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    ConfigChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)


def _program(code: str) -> List[str]:
    return [sys.executable, "-u", "-c", code]


def _backend(available: bool = True, models: Optional[List[str]] = None, gate: Optional[threading.Event] = None) -> Any:
    def list_models() -> List[str]:
        if gate is not None:
            gate.wait(10)
        return models if models is not None else ["m1", "m2"]

    return SimpleNamespace(
        available=lambda: available,
        version=lambda: "v1.0",
        list_models=list_models,
        DESCRIPTION="A fake agent.\nSecond line.",
        INSTALL_HINT="install the fake agent",
    )


@pytest.fixture(autouse=True)
def fake_backends(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Two fake backends: no test runs the real agents' commands."""
    backends = {"alpha": _backend(), "beta": _backend()}
    monkeypatch.setattr(llm_backends, "available_backends", lambda: list(backends))
    monkeypatch.setattr(llm_backends, "first_installed_backend", lambda: "alpha")
    monkeypatch.setattr(llm_backends, "get", lambda name: backends[name])
    return backends


def make_panel(qtbot: QtBot, tmp_path: Path, state: Optional[ProjectState] = None) -> PatchRepairPanel:
    status = StatusLine()
    qtbot.addWidget(status)
    panel = PatchRepairPanel(make_arguments(tmp_path), state or ProjectState(), status)
    qtbot.addWidget(panel)
    panel.test_status = status  # type: ignore[attr-defined]
    return panel


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> PatchRepairPanel:
    return make_panel(qtbot, tmp_path)


def add_patches(panel: PatchRepairPanel, *ids: str) -> None:
    for suggestion_id in ids:
        directory = Path(panel.arguments.dot_dp, "patch_generator", suggestion_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "0.patch").write_text("+current " + suggestion_id + "\n")


def write_results(panel: PatchRepairPanel, suggestions: Dict[str, Any]) -> None:
    directory = Path(panel.arguments.dot_dp, "patch_repair")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(json.dumps({"suggestions": suggestions}))


def ready(panel: PatchRepairPanel) -> None:
    """Patches and a configuration: the run button is enabled."""
    add_patches(panel, "1")
    panel.project_state.current_config = "tiny"
    panel.project_state.publish(ConfigChanged("tiny"))
    assert panel.run_button.isEnabled()


def run_with(panel: PatchRepairPanel, code: str) -> None:
    ready(panel)
    with mock.patch.object(patch_repair_panel, "patch_repair_command", lambda *_a, **_k: _program(code)):
        panel.run_button.click()


def status_text(panel: PatchRepairPanel) -> str:
    return panel.test_status.text()  # type: ignore[attr-defined,no-any-return]


# ── construction ────────────────────────────────────────────────────────────


def test_defaults(panel: PatchRepairPanel) -> None:
    assert {name: check.isChecked() for name, check in panel.hotspot_checks.items()} == {
        "yes": True,
        "maybe": True,
        "no": False,
    }
    assert (panel.timeout_spin.value(), panel.prompts_spin.value(), panel.retries_spin.value()) == (300, 2, 2)
    assert panel.log_level_combo.currentText() == "INFO"
    assert not panel.dry_run_check.isChecked()
    assert panel.config_label.text() == "(none selected)"
    assert panel.summary_label.text() == "(not run yet)"
    assert not panel.run_button.isEnabled() and not panel.stop_button.isEnabled()
    assert panel.budget_label.text() == "At most 2 x (1 + 2) = 6 agent calls per suggestion."
    assert [panel.backend_combo.itemText(i) for i in range(panel.backend_combo.count())] == ["alpha", "beta"]
    assert panel.backend_combo.currentText() == "alpha"
    # no results yet: the diff panes say why they are empty
    assert panel.diff_original.toPlainText() == "(no results yet: run patch repair)"


def test_the_budget_follows_the_dials(panel: PatchRepairPanel) -> None:
    panel.prompts_spin.setValue(3)
    panel.retries_spin.setValue(0)
    assert panel.budget_label.text() == "At most 3 x (1 + 0) = 3 agent calls per suggestion."


# ── the backend and its models ───────────────────────────────────────────────


def test_the_models_are_queried_in_the_background(qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]) -> None:
    gate = threading.Event()
    fake_backends["alpha"] = _backend(models=["fast", "big"], gate=gate)
    panel = make_panel(qtbot, tmp_path)
    # the panel is built and shown while the query is still running
    assert panel.backend_hint.text() == "Querying alpha..."
    assert panel.model_combo.count() == 0
    gate.set()
    qtbot.waitUntil(lambda: panel.model_combo.count() == 2, timeout=20000)
    assert panel.backend_hint.text() == "v1.0 -- A fake agent."
    assert [panel.model_combo.itemText(i) for i in range(2)] == ["fast", "big"]


def test_a_typed_model_survives_the_arrival_of_the_list(
    qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]
) -> None:
    gate = threading.Event()
    fake_backends["alpha"] = _backend(gate=gate)
    panel = make_panel(qtbot, tmp_path)
    panel.model_combo.setCurrentText("custom-model")
    gate.set()
    qtbot.waitUntil(lambda: panel.model_combo.count() == 2, timeout=20000)
    assert panel.model_combo.currentText() == "custom-model"


def test_a_failing_query_leaves_the_field_typeable(qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]) -> None:
    def broken() -> List[str]:
        raise RuntimeError("no network")

    fake_backends["alpha"].list_models = broken
    panel = make_panel(qtbot, tmp_path)
    qtbot.waitUntil(lambda: panel.backend_hint.text() == "A fake agent.", timeout=20000)
    assert panel.model_combo.count() == 0 and panel.model_combo.isEditable()


def test_a_backend_that_is_not_installed_shows_its_hint(
    qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]
) -> None:
    fake_backends["beta"] = _backend(available=False)
    panel = make_panel(qtbot, tmp_path)
    qtbot.waitUntil(lambda: panel.model_combo.count() == 2, timeout=20000)
    panel.backend_combo.setCurrentText("beta")
    assert panel.backend_hint.text() == "install the fake agent"
    assert "c62828" in panel.backend_hint.styleSheet()
    assert panel.model_combo.count() == 0


def test_the_answer_of_a_backend_that_is_no_longer_selected_is_ignored(
    qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]
) -> None:
    gate = threading.Event()
    fake_backends["alpha"] = _backend(models=["stale"], gate=gate)
    fake_backends["beta"] = _backend(models=["fresh"])
    panel = make_panel(qtbot, tmp_path)
    panel.backend_combo.setCurrentText("beta")
    qtbot.waitUntil(lambda: panel.model_combo.count() == 1, timeout=20000)
    gate.set()
    qtbot.wait(300)
    assert panel.model_combo.itemText(0) == "fresh"


def test_an_unknown_backend_is_reported(panel: PatchRepairPanel, fake_backends: Dict[str, Any]) -> None:
    panel.backend_combo.addItem("gone")
    panel.backend_combo.setCurrentText("gone")
    assert panel.backend_hint.text() == "Unknown backend: gone"


# ── enabling the run button ──────────────────────────────────────────────────


def test_the_run_button_needs_patches_and_a_configuration(panel: PatchRepairPanel) -> None:
    state = panel.project_state
    state.current_config = "tiny"
    state.publish(ConfigChanged("tiny"))
    assert panel.config_label.text() == "tiny"
    assert not panel.run_button.isEnabled()  # no patches
    add_patches(panel, "1", "2")
    state.publish(PatternsChanged())
    assert panel.run_button.isEnabled()
    assert panel.selector.get_available_ids() == ["1", "2"]
    state.current_config = None
    state.publish(ConfigChanged(None))
    assert panel.config_label.text() == "(none selected)"
    assert not panel.run_button.isEnabled()


def test_running_without_a_configuration_is_refused(panel: PatchRepairPanel, dialog_answers: DialogRecorder) -> None:
    panel.run_button.setEnabled(True)
    panel.run_button.click()
    assert dialog_answers.titles("show_error") == ["No Configuration Selected"]
    assert not panel.running


def test_running_twice_is_refused(panel: PatchRepairPanel, dialog_answers: DialogRecorder) -> None:
    panel.running = True
    panel._run()
    assert dialog_answers.titles("show_error") == ["Already Running"]


# ── the request ──────────────────────────────────────────────────────────────


def test_the_request_is_read_from_the_widgets(panel: PatchRepairPanel) -> None:
    add_patches(panel, "7", "8")
    panel.selector.refresh()
    panel.project_state.current_config = "cfg"
    panel.hotspot_checks["yes"].setChecked(False)
    panel.hotspot_checks["maybe"].setChecked(False)
    panel.prompts_spin.setValue(3)
    panel.retries_spin.setValue(1)
    panel.timeout_spin.setValue(60)
    panel.model_combo.setCurrentText("  m  ")
    panel.dry_run_check.setChecked(True)
    panel.selector.set_selected_ids(["7"])
    request = panel._snapshot_request()
    assert (request.prompts, request.retries, request.agent_timeout) == (3, 1, 60)
    assert request.model == "m"
    assert request.log_level == "INFO"
    assert request.configuration == "cfg"
    assert request.backend == "alpha"
    assert request.dry_run is True
    assert request.suggestion_ids == ("7",)
    # nothing selected: the default types, not an empty filter
    assert request.hotspot_types == "yes,maybe"


def test_all_suggestions_selected_means_no_restriction(panel: PatchRepairPanel) -> None:
    add_patches(panel, "7")
    panel.selector.refresh()
    assert panel._snapshot_request().suggestion_ids is None


def test_the_request_is_announced_in_the_console(panel: PatchRepairPanel) -> None:
    add_patches(panel, "1", "2")
    panel.selector.refresh()
    panel.project_state.current_config = "tiny"
    panel.selector.set_selected_ids(["2"])
    panel._announce_request(panel._snapshot_request())
    text = panel.console.text()
    assert "Restricting to suggestion IDs: 2" in text
    assert "  Configuration: tiny" in text and "  Backend: alpha" in text and "  Model: (default)" in text


# ── running ──────────────────────────────────────────────────────────────────


def test_a_successful_run(qtbot: QtBot, panel: PatchRepairPanel, dialog_answers: DialogRecorder) -> None:
    published: List[Any] = []
    panel.project_state.subscribe(AutotuningChanged, published.append)
    panel.project_state.subscribe(ResultsChanged, published.append)
    code = (
        "print('hello'); "
        'print(\'@@PR_PROGRESS {"event": "suggestion", "suggestion_id": "1", "status": "repaired", '
        '"files": ["0"], "changed_files": ["0"], "attempts": 2}\'); '
        'print(\'@@PR_PROGRESS {"event": "done", "repaired": 1, "failed": 0, "considered": 1}\')'
    )
    run_with(panel, code)
    assert panel.running and panel.run_button.text() == "⟳ Running..." and panel.stop_button.isEnabled()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Starting patch repair..." in console and "hello" in console and "Patch repair completed." in console
    assert "@@PR_PROGRESS" not in console
    assert panel.summary_label.text() == "1 repaired, 0 not repaired, 1 considered."
    assert panel.table.rowCount() == 1
    assert [panel.table.item(0, c).text() for c in range(6)] == ["1", "", "Repaired", "1 / 1", "2", ""]  # type: ignore[union-attr]
    assert status_text(panel) == "Patch repair completed - 1 patch set(s) repaired"
    assert panel.run_button.text() == "Run Patch Repair" and panel.run_button.isEnabled()
    assert not panel.stop_button.isEnabled()
    assert [type(event) for event in published] == [AutotuningChanged, ResultsChanged]
    assert panel._job is None


def test_a_failing_run(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    published: List[Any] = []
    panel.project_state.subscribe(ResultsChanged, published.append)
    run_with(panel, "raise SystemExit(4)")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Error: Patch repair exited with return code 4" in panel.console.text()
    assert status_text(panel) == "Patch repair failed"
    assert panel.test_status.color == widgets.STATUS_FAIL  # type: ignore[attr-defined]
    assert published == []
    assert panel.run_button.isEnabled()


def test_a_run_that_cannot_start(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    ready(panel)
    with mock.patch.object(patch_repair_panel, "patch_repair_command", lambda *_a, **_k: ["/nonexistent/program"]):
        panel.run_button.click()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Error: " in panel.console.text()
    assert status_text(panel) == "Patch repair failed"


def test_stopping_a_run_is_no_failure(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    published: List[Any] = []
    panel.project_state.subscribe(ResultsChanged, published.append)
    run_with(panel, "import time; print('ready', flush=True); time.sleep(60)")
    qtbot.waitUntil(lambda: "ready" in panel.console.text(), timeout=20000)
    panel.stop_button.click()
    assert status_text(panel) == "Stopping patch repair..." and not panel.stop_button.isEnabled()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Patch repair stopped." in console and "Error" not in console
    assert status_text(panel) == "Patch repair stopped"
    assert published == []
    assert panel._job is None and panel.run_button.isEnabled()


def test_the_job_is_stopped_with_its_process_group(panel: PatchRepairPanel) -> None:
    started: List[Any] = []

    def recording_runner(spec: Any, _events: Any) -> Any:
        started.append(spec)
        return mock.MagicMock()

    ready(panel)
    with mock.patch.object(patch_repair_panel, "JobRunner", recording_runner):
        panel.run_button.click()
    assert [(spec.cancel_policy, spec.new_session) for spec in started] == [(CancelPolicy.SIGINT_GROUP, True)]
    assert started[0].cwd == panel.arguments.dot_dp


def test_a_new_run_clears_the_old_console_and_table(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    write_results(panel, {"1": {"status": "failed"}})
    panel._load_results_from_file()
    panel.console.append_text("old output\n")
    assert panel.table.rowCount() == 1
    run_with(panel, "print('x')")
    assert "old output" not in panel.console.text()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)


def test_the_events_are_handled_on_the_main_thread(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    threads: List[threading.Thread] = []
    original = panel._on_job_event

    def recording(event: Any) -> None:
        threads.append(threading.current_thread())
        original(event)

    panel._on_job_event = recording  # type: ignore[method-assign]
    run_with(panel, "print('x')")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert threads and all(thread is threading.main_thread() for thread in threads)


def test_closing_the_window_stops_the_run(qtbot: QtBot, panel: PatchRepairPanel) -> None:
    run_with(panel, "import time; print('ready', flush=True); time.sleep(60)")
    qtbot.waitUntil(lambda: "ready" in panel.console.text(), timeout=20000)
    panel.cancel_jobs()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Patch repair stopped." in panel.console.text()


def test_closing_the_window_stops_the_backend_query(
    qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]
) -> None:
    gate = threading.Event()
    fake_backends["alpha"] = _backend(gate=gate)
    panel = make_panel(qtbot, tmp_path)
    assert panel._backend_query is not None
    with mock.patch.object(panel._backend_query, "cancel") as cancel:
        panel.cancel_jobs()
    cancel.assert_called_once_with()
    gate.set()


def test_cancel_jobs_without_a_job_is_harmless(panel: PatchRepairPanel) -> None:
    panel.cancel_jobs()


def test_the_selection_is_not_refreshed_while_running(panel: PatchRepairPanel) -> None:
    panel.running = True
    add_patches(panel, "1")
    panel.run_button.setEnabled(False)
    panel.project_state.publish(PatternsChanged())
    assert not panel.run_button.isEnabled()


# ── the progress summary ─────────────────────────────────────────────────────


def test_the_discovery_event_sets_the_summary(panel: PatchRepairPanel) -> None:
    panel._on_progress({"event": "discovery", "built": ["1"], "failing": ["2", "3"]})
    assert panel.summary_label.text() == "1 compile, 2 do not — repairing 2..."
    assert widgets.STATUS_BUSY in panel.summary_label.styleSheet()
    panel._on_progress({"event": "discovery", "built": [], "failing": [], "reference_built": False})
    assert panel.summary_label.text().startswith("The project does not build")
    assert widgets.STATUS_FAIL in panel.summary_label.styleSheet()


def test_the_done_event_colors_the_summary(panel: PatchRepairPanel) -> None:
    panel._on_progress({"event": "done", "repaired": 0, "failed": 2, "considered": 2})
    assert panel.summary_label.text() == "0 repaired, 2 not repaired, 2 considered."
    assert widgets.STATUS_FAIL in panel.summary_label.styleSheet()
    panel._on_progress({"event": "done", "repaired": 2, "failed": 0, "considered": 2})
    assert widgets.STATUS_OK in panel.summary_label.styleSheet()
    panel._on_progress({"event": "done", "repaired": 1, "failed": 1, "considered": 2})
    assert widgets.STATUS_IDLE in panel.summary_label.styleSheet()


# ── the results ──────────────────────────────────────────────────────────────


def row_texts(panel: PatchRepairPanel) -> List[List[str]]:
    return [
        [panel.table.item(row, column).text() for column in range(6)]  # type: ignore[union-attr]
        for row in range(panel.table.rowCount())
    ]


def test_the_table_is_filled_from_results_json_in_numeric_order(panel: PatchRepairPanel) -> None:
    write_results(
        panel,
        {
            "10": {"status": "failed", "hotspot_type": "yes", "attempts": 3, "first_error": "boom", "files": ["0"]},
            "2": {"status": "ok"},
            "x": {"status": "agent_unreachable"},
            "3": {"status": "something_new"},
        },
    )
    panel._load_results_from_file()
    assert row_texts(panel) == [
        ["2", "", "Compiles", "-", "0", ""],
        ["3", "", "something_new", "-", "0", ""],
        ["10", "yes", "Not repaired", "0 / 1", "3", "boom"],
        ["x", "", "Agent unreachable", "-", "0", ""],
    ]


def test_an_unreadable_results_file_leaves_the_table(panel: PatchRepairPanel) -> None:
    write_results(panel, {"1": {"status": "ok"}})
    panel._load_results_from_file()
    Path(panel.arguments.dot_dp, "patch_repair", "results.json").write_text("{not json")
    panel._load_results_from_file()
    assert panel.table.rowCount() == 1


def test_a_repaired_row_is_selected_by_default_and_the_selection_survives_a_refresh(panel: PatchRepairPanel) -> None:
    add_patches(panel, "1", "2", "3")
    write_results(panel, {"1": {"status": "failed"}, "2": {"status": "repaired"}, "3": {"status": "ok"}})
    panel._load_results_from_file()
    assert panel._selected_id() == "2"
    panel.table.selectRow(2)
    assert panel._selected_id() == "3"
    panel._on_progress({"event": "suggestion", "suggestion_id": "1", "status": "repaired"})
    assert panel._selected_id() == "3"
    assert panel.diff_source_label.text() == "Suggestion 3"


def test_the_patch_tab_shows_the_backup_and_the_patch_in_use(panel: PatchRepairPanel) -> None:
    add_patches(panel, "5")
    Path(panel.arguments.dot_dp, "patch_generator", "5", "1.patch").write_text("+second\n")
    backup = Path(panel.arguments.dot_dp, "patch_repair", "backups", "5")
    backup.mkdir(parents=True)
    (backup / "0.patch").write_text("+original\n")
    write_results(panel, {"5": {"status": "repaired", "files": ["0", "1"], "changed_files": ["1", "0"]}})
    panel._load_results_from_file()
    labels = [panel.file_combo.itemText(i) for i in range(panel.file_combo.count())]
    assert labels == ["file 0 (changed)", "file 1 (changed)"]
    assert panel.file_combo.currentText() == "file 0 (changed)"
    assert panel.diff_original.toPlainText() == "+original\n"
    assert panel.diff_repaired.toPlainText() == "+current 5\n"
    # file 1 has no backup
    panel.file_combo.setCurrentIndex(1)
    panel.file_combo.activated.emit(1)
    assert panel.diff_original.toPlainText() == "(no backup: this patch was never modified)"
    assert panel.diff_repaired.toPlainText() == "+second\n"
    assert panel.diff_source_label.text() == "Suggestion 5"


def test_a_suggestion_without_a_file_list_shows_the_patches_on_disk(panel: PatchRepairPanel) -> None:
    add_patches(panel, "4")
    write_results(panel, {"4": {"status": "ok"}})
    panel._load_results_from_file()
    assert [panel.file_combo.itemText(i) for i in range(panel.file_combo.count())] == ["file 0"]
    assert panel.diff_repaired.toPlainText() == "+current 4\n"


def test_a_suggestion_without_patches_says_so(panel: PatchRepairPanel) -> None:
    write_results(panel, {"9": {"status": "failed"}})
    panel._load_results_from_file()
    assert panel.diff_original.toPlainText() == "(no patch files found for suggestion 9)"
    assert panel.file_combo.count() == 0


def test_an_empty_table_clears_the_patch_tab(panel: PatchRepairPanel) -> None:
    write_results(panel, {"1": {"status": "ok"}})
    panel._load_results_from_file()
    panel._records = {}
    panel._refresh_table()
    assert panel.table.rowCount() == 0
    assert panel.diff_source_label.text() == ""
    assert panel.diff_original.toPlainText() == "(no results yet: run patch repair)"


def test_results_of_an_earlier_session_are_shown_when_the_panel_opens(qtbot: QtBot, tmp_path: Path) -> None:
    first = make_panel(qtbot, tmp_path)
    write_results(first, {"1": {"status": "failed", "first_error": "bad"}})
    second = make_panel(qtbot, tmp_path)
    assert row_texts(second) == [["1", "", "Not repaired", "-", "0", "bad"]]
