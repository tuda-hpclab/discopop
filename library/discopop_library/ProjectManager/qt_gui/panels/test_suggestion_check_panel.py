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
from PySide6.QtCore import QItemSelectionModel
from pytestqt.qtbot import QtBot

from discopop_library.PatchRepair import llm_backends
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import suggestion_check_panel
from discopop_library.ProjectManager.qt_gui.panels.suggestion_check_panel import SuggestionCheckPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import suggestion_check_view as view
from discopop_library.ProjectManager.services.jobs import CancelPolicy
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.SuggestionCheck.publish import MARKER_FILE
from discopop_library.SuggestionCheck.unsure import Fingerprint


def _program(code: str) -> List[str]:
    return [sys.executable, "-u", "-c", code]


def _backend(available: bool = True, models: Optional[List[str]] = None, gate: Optional[threading.Event] = None) -> Any:
    # the install sections (Settings > LLM backends) the backend was probed with
    configs: List[Any] = []

    def probe(config: Any = None) -> bool:
        configs.append(config)
        return available

    def list_models(config: Any = None) -> List[str]:
        configs.append(config)
        if gate is not None:
            gate.wait(10)
        return models if models is not None else ["m1", "m2"]

    return SimpleNamespace(
        available=probe,
        version=lambda config=None: "v1.0",
        list_models=list_models,
        DESCRIPTION="A fake agent.\nSecond line.",
        INSTALL_HINT="install the fake agent",
        FIELDS=[],
        configs=configs,
    )


@pytest.fixture(autouse=True)
def fake_backends(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Two fake backends: no test runs the real agents' commands."""
    backends = {"alpha": _backend(), "beta": _backend()}
    monkeypatch.setattr(llm_backends, "available_backends", lambda: list(backends))
    monkeypatch.setattr(llm_backends, "first_installed_backend", lambda: "alpha")
    monkeypatch.setattr(llm_backends, "get", lambda name: backends[name])
    monkeypatch.setattr(llm_backends, "unknown_backends", lambda names: [n for n in names if n not in backends])
    monkeypatch.delenv("DISCOPOP_PATCH_REPAIR_LLM_CONFIG", raising=False)
    return backends


def dot_dp_of(tmp_path: Path) -> Path:
    return Path(make_arguments(tmp_path).dot_dp)


def write_unsure(dot_dp: Path, ids: List[int]) -> None:
    (dot_dp / "explorer").mkdir(parents=True, exist_ok=True)
    suggestions = [
        {
            "pattern_id": i,
            "type": "do_all",
            "start_line": "1:" + str(10 + i),
            "end_line": "1:" + str(10 + i),
            "pragma": "#pragma omp parallel for",
            "blockers": [{"type": "RAW", "source_line": "1:5", "sink_line": "1:6", "accesses": [{"variable": "s"}]}],
        }
        for i in ids
    ]
    (dot_dp / "explorer" / "unsure_suggestions.json").write_text(
        json.dumps({"format_version": 1, "suggestions": suggestions})
    )
    (dot_dp / "FileMapping.txt").write_text("1\t/p/main.cpp\n")


APPROVAL = {
    "state": "approved",
    "verdict": "approved",
    "assumption": "the order does not matter",
    "result_differences": "none",
    "justifications": [{"index": 1, "justification": "independent", "evidence": ["main.cpp:5"]}],
    "review": True,
    "tool_calls": 4,
    "backend": "alpha",
    "model": "m1",
    "start_line": "1:13",
}


def write_results(dot_dp: Path, entries: Dict[int, Dict[str, Any]], current: bool = True) -> None:
    directory = dot_dp / "suggestion_check"
    directory.mkdir(parents=True, exist_ok=True)
    fingerprint = (
        Fingerprint.of(str(dot_dp / "explorer" / "unsure_suggestions.json")).to_dict()
        if current
        else {"mtime_ns": 1, "size": 1}
    )
    suggestions = [dict(entry, pattern_id=i) for i, entry in sorted(entries.items())]
    (directory / "results.json").write_text(json.dumps({"explorer_output": fingerprint, "suggestions": suggestions}))
    approved = [
        {"pattern_id": i, "assumption": e.get("assumption"), "result_differences": e.get("result_differences")}
        for i, e in sorted(entries.items())
        if e.get("state") == "approved"
    ]
    (directory / "approved.json").write_text(json.dumps({"explorer_output": fingerprint, "suggestions": approved}))
    for i, entry in entries.items():
        if entry.get("state") == "approved":
            patch_dir = directory / "approved" / str(i)
            patch_dir.mkdir(parents=True, exist_ok=True)
            (patch_dir / "1.patch").write_text("+#pragma omp parallel for " + str(i) + "\n")


def make_panel(qtbot: QtBot, tmp_path: Path, state: Optional[ProjectState] = None) -> SuggestionCheckPanel:
    status = StatusLine()
    qtbot.addWidget(status)
    panel = SuggestionCheckPanel(make_arguments(tmp_path), state or ProjectState(), status)
    qtbot.addWidget(panel)
    panel.test_status = status  # type: ignore[attr-defined]
    return panel


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> SuggestionCheckPanel:
    return make_panel(qtbot, tmp_path)


@pytest.fixture
def checked(qtbot: QtBot, tmp_path: Path) -> SuggestionCheckPanel:
    """Unsure suggestions 3, 4, 5, 12 and a check of them: 3 and 12 approved, 4 unsure, 5 failed."""
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3, 4, 5, 12])
    write_results(
        dot,
        {
            3: APPROVAL,
            4: {"state": "rejected", "verdict": "unsure", "reason": "cannot tell", "start_line": "1:14"},
            5: {"state": "failed", "reason": "the agent did not answer: timeout", "start_line": "1:15"},
            12: dict(APPROVAL, assumption="the sum is commutative", result_differences="rounding"),
        },
    )
    return make_panel(qtbot, tmp_path)


def ready(panel: SuggestionCheckPanel) -> None:
    """Unsure suggestions: the run button is enabled."""
    write_unsure(Path(panel.arguments.dot_dp), [3, 4])
    panel.project_state.publish(PatternsChanged())
    assert panel.run_button.isEnabled()


def run_with(panel: SuggestionCheckPanel, code: str) -> None:
    ready(panel)
    with mock.patch.object(suggestion_check_panel, "suggestion_check_command", lambda *_a, **_k: _program(code)):
        panel.run_button.click()


def status_text(panel: SuggestionCheckPanel) -> str:
    return panel.test_status.text()  # type: ignore[attr-defined,no-any-return]


def row_texts(panel: SuggestionCheckPanel) -> List[List[str]]:
    return [
        [panel.table.item(row, column).text() for column in range(7)]  # type: ignore[union-attr]
        for row in range(panel.table.rowCount())
    ]


def select_rows(panel: SuggestionCheckPanel, *rows: int) -> None:
    """Select exactly ``rows``, the first of them current, as a ctrl-click would."""
    panel.table.clearSelection()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in rows:
        panel.table.selectionModel().select(panel.table.model().index(row, 0), flags)
    if rows:
        panel.table.setCurrentCell(rows[0], 0, QItemSelectionModel.SelectionFlag.NoUpdate)


# ── construction ────────────────────────────────────────────────────────────


def test_defaults(panel: SuggestionCheckPanel) -> None:
    assert (panel.timeout_spin.value(), panel.prompts_spin.value(), panel.retries_spin.value()) == (600, 2, 2)
    assert panel.max_spin.value() == 0 and panel.max_spin.text() == "no limit"
    assert panel.log_level_combo.currentText() == "WARNING"
    assert panel.review_check.isChecked() and panel.rounding_check.isChecked() and panel.tools_check.isChecked()
    assert panel.rounding_check.text() == "Accept rounding differences"
    assert panel.tools_check.text() == "Give the agent DiscoPoP's data (MCP)"
    assert panel.header.chip.text() == "No unsure suggestions" and panel.header.chip.level == widgets.CHIP_IDLE
    assert not panel.run_button.isEnabled() and not panel.run_button.is_running()
    assert panel.output_console() is panel.console and panel.output_title == "Suggestion Check"
    assert not panel._advanced.is_expanded()
    assert panel.results_stack.currentWidget() is panel.empty_label
    assert panel.empty_label.text() == suggestion_check_panel.NO_UNSURE_TEXT
    assert panel.budget_label.text() == (
        "At most 2 x (1 + 2) = 6 agent calls per suggestion, plus up to 3 for the review."
    )
    assert [panel.backend_combo.itemText(i) for i in range(panel.backend_combo.count())] == ["alpha", "beta"]
    assert panel.backend_combo.currentText() == "alpha"
    assert [panel.connection_combo.itemText(i) for i in range(panel.connection_combo.count())] == [view.NO_CONNECTION]
    assert panel.backend_combo.isEnabled() and panel.model_combo.isEnabled()
    assert panel.scope_caption.text().startswith("No unsure suggestions")
    assert not panel.publish_button.isEnabled() and not panel.withdraw_button.isEnabled()
    # the panel says what an approval is
    assert "rests on the agent's assumption, not on DiscoPoP's analysis" in panel.header.description_label.text()
    assert panel.patch_view.toPlainText() == "(no results yet: run the suggestion check)"


def test_the_budget_follows_the_dials(panel: SuggestionCheckPanel) -> None:
    panel.prompts_spin.setValue(3)
    panel.retries_spin.setValue(0)
    panel.review_check.setChecked(False)
    assert panel.budget_label.text() == "At most 3 x (1 + 0) = 3 agent calls per suggestion."


# ── the backend, its models and the stored connections ──────────────────────


def test_the_models_are_queried_in_the_background(qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]) -> None:
    gate = threading.Event()
    fake_backends["alpha"] = _backend(models=["fast", "big"], gate=gate)
    panel = make_panel(qtbot, tmp_path)
    assert panel.backend_hint.text() == "Querying alpha..."
    assert panel.model_combo.count() == 0
    gate.set()
    qtbot.waitUntil(lambda: panel.model_combo.count() == 2, timeout=20000)
    assert panel.backend_hint.text() == "v1.0 -- A fake agent."
    # only the backend's list: no model names are made up
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
    def broken(_config: Any = None) -> List[str]:
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


def test_an_unknown_backend_is_reported(panel: SuggestionCheckPanel) -> None:
    panel.backend_combo.addItem("gone")
    panel.backend_combo.setCurrentText("gone")
    assert panel.backend_hint.text() == "Unknown backend: gone"


def write_llm_config(tmp_path: Path, connections: Dict[str, Any], backends: Optional[Dict[str, Any]] = None) -> None:
    directory = dot_dp_of(tmp_path) / "patch_repair"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "llm_config.json").write_text(json.dumps({"connections": connections, "backends": backends or {}}))


def test_the_backend_is_queried_with_its_configured_executable(
    qtbot: QtBot, tmp_path: Path, fake_backends: Dict[str, Any]
) -> None:
    write_llm_config(tmp_path, {}, {"alpha": {"binary": "/opt/alpha"}})
    panel = make_panel(qtbot, tmp_path)
    qtbot.waitUntil(lambda: panel.model_combo.count() == 2, timeout=20000)
    # the probe and the model list use the section of Settings > LLM backends, not the name on PATH
    assert fake_backends["alpha"].configs == [{"binary": "/opt/alpha"}, {"binary": "/opt/alpha"}]


def test_a_stored_connection_shows_its_backend_and_model_read_only(qtbot: QtBot, tmp_path: Path) -> None:
    write_llm_config(tmp_path, {"fast": {"backend": "beta", "model": "m2"}, "plain": {"backend": "alpha"}})
    panel = make_panel(qtbot, tmp_path)
    assert [panel.connection_combo.itemText(i) for i in range(panel.connection_combo.count())] == [
        view.NO_CONNECTION,
        "fast",
        "plain",
    ]
    panel.model_combo.setCurrentText("typed")
    panel.connection_combo.setCurrentText("fast")
    assert panel.backend_combo.currentText() == "beta" and panel.model_combo.currentText() == "m2"
    assert not panel.backend_combo.isEnabled() and not panel.model_combo.isEnabled()
    assert panel.connection_hint.text() == "fast: beta / m2"
    request = panel._snapshot_request()
    assert request.connection == "fast"
    panel.connection_combo.setCurrentText("plain")
    assert panel.connection_hint.text() == "plain: alpha / (backend default)"
    assert panel.model_combo.currentText() == ""
    # back to choosing by hand: what was chosen before comes back
    panel.connection_combo.setCurrentText(view.NO_CONNECTION)
    assert panel.backend_combo.isEnabled() and panel.model_combo.isEnabled()
    assert panel.backend_combo.currentText() == "alpha" and panel.model_combo.currentText() == "typed"
    assert panel._snapshot_request().connection == ""


def test_reloading_the_connections_keeps_the_selection(qtbot: QtBot, tmp_path: Path) -> None:
    write_llm_config(tmp_path, {"a": {"backend": "alpha"}, "b": {"backend": "beta"}})
    panel = make_panel(qtbot, tmp_path)
    panel.connection_combo.setCurrentText("b")
    write_llm_config(tmp_path, {"b": {"backend": "beta", "model": "new"}, "c": {"backend": "alpha"}})
    panel.reload_connections()
    assert [panel.connection_combo.itemText(i) for i in range(panel.connection_combo.count())] == [
        view.NO_CONNECTION,
        "b",
        "c",
    ]
    assert panel.connection_combo.currentText() == "b" and panel.model_combo.currentText() == "new"
    # a connection that was deleted: back to choosing by hand
    write_llm_config(tmp_path, {"c": {"backend": "alpha"}})
    panel.reload_connections()
    assert panel.connection_combo.currentText() == view.NO_CONNECTION and panel.backend_combo.isEnabled()


def test_an_unreadable_configuration_is_reported(qtbot: QtBot, tmp_path: Path) -> None:
    directory = dot_dp_of(tmp_path) / "patch_repair"
    directory.mkdir(parents=True)
    (directory / "llm_config.json").write_text("{broken")
    panel = make_panel(qtbot, tmp_path)
    assert panel.connection_hint.text().startswith("Could not read the LLM configuration")
    assert panel.connection_combo.count() == 1


def test_a_connection_that_cannot_be_resolved_is_reported(qtbot: QtBot, tmp_path: Path) -> None:
    write_llm_config(tmp_path, {"odd": {"backend": "nonexistent"}})
    panel = make_panel(qtbot, tmp_path)
    panel.connection_combo.setCurrentText("odd")
    assert panel.connection_hint.text().startswith("Unknown backend: nonexistent")
    assert not panel.backend_combo.isEnabled()


# ── enabling the run button and the scope ────────────────────────────────────


def test_the_run_button_needs_unsure_suggestions(panel: SuggestionCheckPanel) -> None:
    assert not panel.run_button.isEnabled()
    write_unsure(Path(panel.arguments.dot_dp), [3, 12])
    panel.project_state.publish(PatternsChanged())
    assert panel.run_button.isEnabled()
    assert panel.scope_caption.text() == "All 2 unsure suggestion(s): 3, 12"
    assert panel.header.chip.text() == "Not run yet"
    assert panel.empty_label.text() == "No suggestion check run yet."


def test_the_scope_caption_follows_the_field(panel: SuggestionCheckPanel) -> None:
    write_unsure(Path(panel.arguments.dot_dp), [3, 4, 12])
    panel.project_state.publish(PatternsChanged())
    panel.scope_edit.setText("3-5, 99")
    assert panel.scope_caption.text() == "2 of 3 selected: 3, 4"
    panel.scope_edit.setText("99")
    assert panel.scope_caption.text().startswith("None of the available unsure suggestions matches")


def test_running_with_an_empty_scope_is_refused(panel: SuggestionCheckPanel, dialog_answers: DialogRecorder) -> None:
    ready(panel)
    panel.scope_edit.setText("99")
    panel.run_button.click()
    assert dialog_answers.titles("show_error") == ["No Suggestion Selected"]
    assert not panel.running


def test_running_without_unsure_suggestions_is_refused(
    panel: SuggestionCheckPanel, dialog_answers: DialogRecorder
) -> None:
    panel.run_button.setEnabled(True)
    panel.run_button.click()
    assert dialog_answers.titles("show_error") == ["No Unsure Suggestions"]
    assert not panel.running


def test_running_twice_is_refused(panel: SuggestionCheckPanel, dialog_answers: DialogRecorder) -> None:
    panel.running = True
    panel._run()
    assert dialog_answers.titles("show_error") == ["Already Running"]


# ── the request ──────────────────────────────────────────────────────────────


def test_the_request_is_read_from_the_widgets(panel: SuggestionCheckPanel) -> None:
    write_unsure(Path(panel.arguments.dot_dp), [3, 4, 12])
    panel.project_state.publish(PatternsChanged())
    panel.prompts_spin.setValue(3)
    panel.retries_spin.setValue(1)
    panel.timeout_spin.setValue(60)
    panel.max_spin.setValue(2)
    panel.model_combo.setCurrentText("  m  ")
    panel.review_check.setChecked(False)
    panel.rounding_check.setChecked(False)
    panel.tools_check.setChecked(False)
    panel.scope_edit.setText("12, 3-4")
    request = panel._snapshot_request()
    assert (request.prompts, request.retries, request.agent_timeout, request.max_suggestions) == (3, 1, 60, 2)
    assert request.model == "m" and request.backend == "alpha" and request.connection == ""
    assert request.log_level == "WARNING"
    assert (request.review, request.accept_rounding, request.discopop_tools) == (False, False, False)
    assert request.suggestion_ids == ("3", "4", "12")


def test_an_empty_scope_means_all(panel: SuggestionCheckPanel) -> None:
    ready(panel)
    assert panel._snapshot_request().suggestion_ids is None


def test_the_request_is_announced_in_the_console(panel: SuggestionCheckPanel) -> None:
    ready(panel)
    panel.scope_edit.setText("4")
    panel._announce_request(panel._snapshot_request())
    text = panel.console.text()
    assert "Restricting to unsure suggestions: 4" in text
    assert "  Backend: alpha" in text and "  Model: (default)" in text and "  Review: on" in text
    assert "  Rounding differences: accepted" in text and "  DiscoPoP's data (MCP): on" in text


# ── running ──────────────────────────────────────────────────────────────────


def _progress(event: Dict[str, Any]) -> str:
    return "print('@@SC_PROGRESS ' + " + repr(json.dumps(event)) + ")"


def test_a_successful_run(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    published: List[Any] = []
    for event_type in (AutotuningChanged, ResultsChanged, PatternsChanged):
        panel.project_state.subscribe(event_type, published.append)
    ready(panel)
    published.clear()
    dot = Path(panel.arguments.dot_dp)
    # the check writes results.json before every "done" event
    write_results(dot, {3: APPROVAL})
    code = "; ".join(
        [
            "print('hello')",
            _progress({"event": "start", "suggestions": [3]}),
            _progress({"event": "check", "pattern_id": 3}),
            _progress({"event": "done", "pattern_id": 3, "state": "approved", "reason": ""}),
            _progress({"event": "end", "counts": {"approved": 1}}),
        ]
    )
    with mock.patch.object(suggestion_check_panel, "suggestion_check_command", lambda *_a, **_k: _program(code)):
        panel.run_button.click()
    assert panel.running and panel.run_button.is_running() and panel.run_button.isEnabled()
    assert not panel.publish_button.isEnabled()  # a running check rewrites the approvals
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Starting the suggestion check..." in console and "hello" in console
    assert "Suggestion check completed." in console and "@@SC_PROGRESS" not in console
    assert panel.header.chip.text() == "1 approved, 0 rejected, 0 without an answer"
    assert panel.header.chip.level == widgets.CHIP_OK
    assert [row[:4] for row in row_texts(panel)] == [
        ["3", "main.cpp:13", "1", "Approved"],
        ["4", "main.cpp:14", "1", "Not checked"],
    ]
    assert status_text(panel) == "Suggestion check completed - 1 approved (not in use yet)"
    assert panel.run_button.text() == "Run Suggestion Check" and panel.run_button.isEnabled()
    # the sidebar state; nothing was put into use
    assert [type(event) for event in published] == [ResultsChanged]
    assert panel._job is None
    assert panel.publish_button.isEnabled()


def test_the_progress_of_a_run(panel: SuggestionCheckPanel) -> None:
    panel._on_progress({"event": "start", "suggestions": [1, 2]})
    assert panel.header.chip.text() == "Checking 2 unsure suggestion(s)..."
    panel._on_progress({"event": "check", "pattern_id": 2})
    assert panel.header.chip.text() == "Checking suggestion 2 (of 2)..."
    assert panel.header.chip.level == widgets.CHIP_BUSY


def test_a_done_event_reloads_the_results(panel: SuggestionCheckPanel) -> None:
    dot = Path(panel.arguments.dot_dp)
    write_unsure(dot, [3])
    write_results(dot, {3: APPROVAL})
    panel._reload_unsure()
    panel._on_progress({"event": "done", "pattern_id": 3, "state": "approved"})
    assert row_texts(panel)[0][:4] == ["3", "main.cpp:13", "1", "Approved"]


def test_a_failing_run(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    run_with(panel, "raise SystemExit(1)")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Error: The suggestion check exited with return code 1" in panel.console.text()
    assert status_text(panel) == "Suggestion check failed"
    assert panel.header.chip.level == widgets.CHIP_ERROR and panel.header.chip.text() == "Failed"
    assert panel.run_button.isEnabled()


def test_an_aborted_run_says_why(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    code = _progress({"event": "aborted", "reason": "main.cpp changed"}) + "; raise SystemExit(2)"
    run_with(panel, code)
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "aborted: the project changed while it ran" in panel.console.text()
    assert panel.header.chip.text() == "Aborted: the project changed during the check"
    assert panel.header.chip.detail() == "main.cpp changed"
    assert panel.header.chip.level == widgets.CHIP_ERROR
    assert status_text(panel) == "Suggestion check aborted"


def test_an_aborted_run_without_an_event(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    run_with(panel, "raise SystemExit(2)")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert panel.header.chip.text() == "Aborted"


def test_a_run_that_cannot_start(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    published: List[Any] = []
    panel.project_state.subscribe(ResultsChanged, published.append)
    ready(panel)
    with mock.patch.object(
        suggestion_check_panel, "suggestion_check_command", lambda *_a, **_k: ["/nonexistent/program"]
    ):
        panel.run_button.click()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Error: " in panel.console.text()
    assert status_text(panel) == "Suggestion check failed"
    assert published == []


def test_stopping_a_run_is_no_failure(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    run_with(panel, "import time; print('ready', flush=True); time.sleep(60)")
    qtbot.waitUntil(lambda: "ready" in panel.console.text(), timeout=20000)
    panel.run_button.click()
    assert status_text(panel) == "Stopping the suggestion check..." and not panel.run_button.isEnabled()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    console = panel.console.text()
    assert "Suggestion check stopped." in console and "Error" not in console
    assert status_text(panel) == "Suggestion check stopped"
    assert panel.header.chip.text() == "Stopped"
    assert panel._job is None and panel.run_button.isEnabled()


def test_the_job_is_stopped_with_its_process_group(panel: SuggestionCheckPanel) -> None:
    started: List[Any] = []

    def recording_runner(spec: Any, _events: Any) -> Any:
        started.append(spec)
        return mock.MagicMock()

    ready(panel)
    with mock.patch.object(suggestion_check_panel, "JobRunner", recording_runner):
        panel.run_button.click()
    assert [(spec.cancel_policy, spec.new_session) for spec in started] == [(CancelPolicy.SIGINT_GROUP, True)]
    assert started[0].cwd == panel.arguments.dot_dp
    assert started[0].command[1:3] == ["-m", "discopop_library.SuggestionCheck"]


def test_a_new_run_clears_the_old_console_and_table(qtbot: QtBot, checked: SuggestionCheckPanel) -> None:
    checked.console.append_text("old output\n")
    assert checked.table.rowCount() == 4
    with mock.patch.object(suggestion_check_panel, "suggestion_check_command", lambda *_a, **_k: _program("1")):
        checked.run_button.click()
        # the candidates stay, without their results
        assert {row[3] for row in row_texts(checked)} == {"Not checked"}
    assert "old output" not in checked.console.text()
    qtbot.waitUntil(lambda: not checked.running, timeout=20000)
    # the results on disk come back
    assert checked.table.rowCount() == 4


def test_the_events_are_handled_on_the_main_thread(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    threads: List[threading.Thread] = []
    original = panel._on_job_event

    def recording(event: Any) -> None:
        threads.append(threading.current_thread())
        original(event)

    panel._on_job_event = recording  # type: ignore[method-assign]
    run_with(panel, "print('x')")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert threads and all(thread is threading.main_thread() for thread in threads)


def test_closing_the_window_stops_the_run(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    run_with(panel, "import time; print('ready', flush=True); time.sleep(60)")
    qtbot.waitUntil(lambda: "ready" in panel.console.text(), timeout=20000)
    panel.cancel_jobs()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert "Suggestion check stopped." in panel.console.text()


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


def test_cancel_jobs_without_a_job_is_harmless(panel: SuggestionCheckPanel) -> None:
    panel.cancel_jobs()


def test_a_run_opens_the_output_pane(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    with qtbot.waitSignal(panel.output_requested, timeout=5000):
        run_with(panel, "print('x')")
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)
    assert panel.header.chip.level == widgets.CHIP_OK and panel.header.chip.text() == "Completed"


# ── the results ──────────────────────────────────────────────────────────────


def test_the_results_of_an_earlier_session_are_shown(checked: SuggestionCheckPanel) -> None:
    assert row_texts(checked) == [
        ["3", "main.cpp:13", "1", "Approved", "none", "4", "agree"],
        ["4", "main.cpp:14", "1", "Unsure", "", "0", ""],
        ["5", "main.cpp:15", "1", "Error", "", "0", ""],
        ["12", "main.cpp:13", "1", "Approved", "rounding", "4", "agree"],
    ]
    assert checked.header.chip.text() == "4 checked, 2 approved"
    assert checked.header.chip.level == widgets.CHIP_OK
    assert checked.table.isColumnHidden(view.COLUMNS.index("Cost"))
    # an approval is selected first
    assert checked._selected_id() == "3"


def test_a_recorded_cost_is_shown(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3])
    write_results(dot, {3: dict(APPROVAL, cost=0.25)})
    panel = make_panel(qtbot, tmp_path)
    assert not panel.table.isColumnHidden(view.COLUMNS.index("Cost"))
    assert panel.table.item(0, view.COLUMNS.index("Cost")).text() == "$0.2500"  # type: ignore[union-attr]


def test_stale_results_cannot_be_used(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3])
    write_results(dot, {3: APPROVAL}, current=False)
    panel = make_panel(qtbot, tmp_path)
    assert panel.header.chip.text() == suggestion_check_panel.STALE_TEXT
    assert panel.header.chip.level == widgets.CHIP_WARN
    assert not panel.publish_button.isEnabled()


def test_a_new_pattern_detection_makes_the_results_stale(checked: SuggestionCheckPanel) -> None:
    write_unsure(Path(checked.arguments.dot_dp), [3, 4, 5, 12, 20])
    checked.project_state.publish(PatternsChanged())
    assert checked.header.chip.text() == suggestion_check_panel.STALE_TEXT
    assert checked.scope_caption.text().startswith("All 5 unsure suggestion(s)")


def test_the_details_of_an_approval(checked: SuggestionCheckPanel) -> None:
    text = checked.details_view.toPlainText()
    assert text.startswith("Suggestion 3: Approved")
    assert "Assumption: the order does not matter" in text
    assert "  Blocker 1: RAW dependency main.cpp:5 -> main.cpp:6 on s" in text
    assert [checked.patch_combo.itemText(i) for i in range(checked.patch_combo.count())] == ["file 1"]
    assert checked.patch_view.toPlainText() == "+#pragma omp parallel for 3\n"
    assert checked.assumption_label.text() == ("Rests on the agent's assumption - 3: the order does not matter")


def test_the_details_of_a_rejection(checked: SuggestionCheckPanel) -> None:
    select_rows(checked, 1)
    text = checked.details_view.toPlainText()
    assert text.startswith("Suggestion 4: Unsure") and "Reason: cannot tell" in text
    assert checked.patch_combo.count() == 0
    assert checked.patch_view.toPlainText() == "(suggestion 4 was not approved, so it has no patch)"
    assert checked.transcript_view.toPlainText() == "(no transcript recorded for suggestion 4)"
    # no approval selected: the button would use all of them
    assert checked.publish_button.text() == "Use all approved suggestions (2)"
    assert checked.assumption_label.text().startswith("Rests on the agent's assumption - 3: ")


def test_the_transcripts(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3])
    write_results(dot, {3: APPROVAL})
    directory = dot / "suggestion_check" / "transcripts" / "3"
    directory.mkdir(parents=True)
    for name in ("check_1_0_prompt.txt", "check_1_0_answer.txt", "check_1_0_tools.txt", "review_0_prompt.txt"):
        (directory / name).write_text("text of " + name)
    (directory / "check_1_0_events.jsonl").write_text("{}")
    panel = make_panel(qtbot, tmp_path)
    assert [panel.transcript_combo.itemText(i) for i in range(panel.transcript_combo.count())] == [
        "check_1_0_prompt.txt",
        "check_1_0_answer.txt",
        "check_1_0_tools.txt",
        "review_0_prompt.txt",
    ]
    assert panel.transcript_view.toPlainText() == "text of check_1_0_prompt.txt"
    panel.transcript_combo.setCurrentIndex(2)
    panel.transcript_combo.activated.emit(2)
    assert panel.transcript_view.toPlainText() == "text of check_1_0_tools.txt"


def test_the_selection_survives_a_refresh(checked: SuggestionCheckPanel) -> None:
    select_rows(checked, 2)
    assert checked._selected_id() == "5"
    checked._load_results_from_file()
    assert checked._selected_id() == "5"
    assert checked.details_view.toPlainText().startswith("Suggestion 5: Error")


def test_an_unreadable_results_file_leaves_the_table(checked: SuggestionCheckPanel) -> None:
    Path(checked.arguments.dot_dp, "suggestion_check", "results.json").write_text("{not json")
    checked._load_results_from_file()
    assert checked.table.rowCount() == 4


# ── using the approvals ──────────────────────────────────────────────────────


def test_using_the_selected_approval(checked: SuggestionCheckPanel, dialog_answers: DialogRecorder) -> None:
    published: List[Any] = []
    for event_type in (PatternsChanged, AutotuningChanged, ResultsChanged):
        checked.project_state.subscribe(event_type, published.append)
    assert checked.publish_button.text() == "Use approved suggestion 3"
    dialog_answers.answer("ask_yes_no", True)
    checked.publish_button.click()
    question = dialog_answers.messages("ask_yes_no")[0]
    assert "not DiscoPoP's analysis" in question and "3: the order does not matter" in question
    assert dialog_answers.titles("show_message") == ["Suggestions In Use"]
    dot = Path(checked.arguments.dot_dp)
    assert (dot / "patch_generator" / "3" / MARKER_FILE).is_file()
    assert (dot / "patch_generator" / "3" / "1.patch").read_text() == "+#pragma omp parallel for 3\n"
    assert not (dot / "patch_generator" / "12").exists()
    assert [type(event) for event in published] == [PatternsChanged, AutotuningChanged, ResultsChanged]
    assert row_texts(checked)[0][3] == "Approved (in use)"
    assert "In use: published to patch_generator/3" in checked.details_view.toPlainText()
    assert checked.withdraw_button.text() == "Withdraw 3" and checked.withdraw_button.isEnabled()
    assert status_text(checked) == "1 agent-approved suggestion(s) in use"


def test_publishing_can_be_declined(checked: SuggestionCheckPanel, dialog_answers: DialogRecorder) -> None:
    dialog_answers.answer("ask_yes_no", False)
    checked.publish_button.click()
    assert not Path(checked.arguments.dot_dp, "patch_generator").exists()


def test_using_all_approvals_and_withdrawing_them(
    checked: SuggestionCheckPanel, dialog_answers: DialogRecorder
) -> None:
    select_rows(checked, 1)
    dialog_answers.answer("ask_yes_no", True)
    checked.publish_button.click()
    assert view.published_suggestions(checked.arguments.dot_dp) == ["3", "12"]
    assert checked.withdraw_button.text() == "Withdraw all (2)"
    published: List[Any] = []
    checked.project_state.subscribe(PatternsChanged, published.append)
    checked.withdraw_button.click()
    assert view.published_suggestions(checked.arguments.dot_dp) == []
    assert len(published) == 1
    assert "Withdrawn: 3, 12" in checked.console.text()
    assert not checked.withdraw_button.isEnabled()


def test_skipped_approvals_are_explained(checked: SuggestionCheckPanel, dialog_answers: DialogRecorder) -> None:
    # the patch generator wrote a patch for this id: it is never replaced
    generated = Path(checked.arguments.dot_dp, "patch_generator", "3")
    generated.mkdir(parents=True)
    (generated / "0.patch").write_text("generated")
    published: List[Any] = []
    checked.project_state.subscribe(PatternsChanged, published.append)
    dialog_answers.answer("ask_yes_no", True)
    checked.publish_button.click()
    assert dialog_answers.titles("show_warning") == ["Suggestions Not Used"]
    assert "Not used 3: the patch generator wrote a patch for this id" in dialog_answers.messages("show_warning")[0]
    assert published == []
    assert (generated / "0.patch").read_text() == "generated"


def test_several_rows_can_be_selected(checked: SuggestionCheckPanel) -> None:
    select_rows(checked, 0, 3)
    assert checked._selected_ids() == ["3", "12"]
    assert checked.publish_button.text() == "Use approved suggestions 3, 12"
    assert "3: the order does not matter; 12: the sum is commutative [results may differ by rounding]" in (
        checked.assumption_label.text()
    )


def test_several_stored_connections_allow_backend_and_model_alone(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    write_llm_config(tmp_path, {"a": {"backend": "alpha"}, "b": {"backend": "beta"}})
    panel = make_panel(qtbot, tmp_path)
    ready(panel)
    # backend and model alone resolve through that backend's own section of the file, whatever is stored
    assert "refuse" not in panel.connection_hint.text()
    assert "c62828" not in panel.connection_hint.styleSheet()
    started: List[Any] = []

    def recording_runner(spec: Any, _events: Any) -> Any:
        started.append(spec)
        return mock.MagicMock()

    with mock.patch.object(suggestion_check_panel, "JobRunner", recording_runner):
        panel.run_button.click()
    assert len(started) == 1 and "--backend" in started[0].command and "--connection" not in started[0].command


def test_the_only_stored_connection_is_named(qtbot: QtBot, tmp_path: Path) -> None:
    write_llm_config(tmp_path, {"solo": {"backend": "beta", "model": "m2"}})
    panel = make_panel(qtbot, tmp_path)
    assert panel.connection_hint.text().startswith(
        "The backend and the model below override those of the only stored connection, solo"
    )


def test_an_unresolvable_connection_cannot_run(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    write_llm_config(tmp_path, {"odd": {"backend": "nonexistent"}})
    panel = make_panel(qtbot, tmp_path)
    ready(panel)
    panel.connection_combo.setCurrentText("odd")
    panel.run_button.click()
    assert dialog_answers.titles("show_error") == ["LLM Connection"] and not panel.running


def test_an_unreadable_configuration_cannot_run(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    directory = dot_dp_of(tmp_path) / "patch_repair"
    directory.mkdir(parents=True)
    (directory / "llm_config.json").write_text("{broken")
    panel = make_panel(qtbot, tmp_path)
    ready(panel)
    panel.run_button.click()
    assert dialog_answers.titles("show_error") == ["LLM Connection"]
    assert dialog_answers.messages("show_error")[0].startswith("Could not read the LLM configuration")


# ── the hotspot filter ───────────────────────────────────────────────────────


def test_the_hotspot_types_default_like_patch_repairs(panel: SuggestionCheckPanel) -> None:
    assert {name: check.isChecked() for name, check in panel.hotspot_checks.items()} == {
        "yes": True,
        "maybe": True,
        "no": False,
    }
    ready(panel)
    assert panel._snapshot_request().hotspot_types == "yes,maybe"
    panel.hotspot_checks["no"].setChecked(True)
    panel.hotspot_checks["yes"].setChecked(False)
    assert panel._snapshot_request().hotspot_types == "maybe,no"
    panel._announce_request(panel._snapshot_request())
    assert "  Hotspot types: maybe,no" in panel.console.text()
    # nothing checked: the default, as in the Patch Repair tab
    for check in panel.hotspot_checks.values():
        check.setChecked(False)
    assert panel._snapshot_request().hotspot_types == "yes,maybe"


def _with_skipped(dot: Path, skipped: List[Dict[str, Any]]) -> None:
    path = dot / "suggestion_check" / "results.json"
    document = json.loads(path.read_text())
    document["skipped_by_hotspot"] = skipped
    path.write_text(json.dumps(document))


def test_the_suggestions_skipped_by_the_hotspot_filter_are_shown(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3, 4, 5])
    write_results(dot, {3: APPROVAL})
    _with_skipped(dot, [{"pattern_id": 4, "hotspot_type": "no"}, {"pattern_id": 5, "hotspot_type": "no"}])
    panel = make_panel(qtbot, tmp_path)
    assert not panel.skipped_label.isHidden()
    assert panel.skipped_label.text().startswith("Skipped (cold): 4 (NO), 5 (NO).")
    assert panel.header.chip.text() == "1 checked, 1 approved, 2 skipped (cold)"


def test_a_run_which_skipped_everything_is_no_run_without_results(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [4])
    write_results(dot, {})
    _with_skipped(dot, [{"pattern_id": 4, "hotspot_type": "no"}])
    panel = make_panel(qtbot, tmp_path)
    assert panel.header.chip.text() == "0 checked, 0 approved, 1 skipped (cold)"
    # the skipped candidate is a row of the table
    assert row_texts(panel) == [["4", "main.cpp:14", "1", "Skipped (cold)", "", "", ""]]
    assert not panel.skipped_label.isHidden()


def test_a_skipped_event_reloads_and_a_new_run_clears_the_skipped(qtbot: QtBot, panel: SuggestionCheckPanel) -> None:
    dot = Path(panel.arguments.dot_dp)
    write_unsure(dot, [3, 4])
    write_results(dot, {})
    _with_skipped(dot, [{"pattern_id": 3, "hotspot_type": "no"}])
    assert panel.skipped_label.isHidden()
    panel._on_progress({"event": "skipped_by_hotspot", "suggestions": [{"pattern_id": 3, "hotspot_type": "no"}]})
    assert not panel.skipped_label.isHidden()
    # the line of the last run is gone as soon as the next one starts
    run_with(panel, "import time; time.sleep(30)")
    assert panel.running and panel.skipped_label.isHidden()
    panel._stop()
    qtbot.waitUntil(lambda: not panel.running, timeout=20000)


def test_a_skipped_suggestion_with_an_earlier_result_keeps_its_row_only(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3, 4])
    write_results(dot, {3: APPROVAL})
    _with_skipped(dot, [{"pattern_id": 3, "hotspot_type": "no"}, {"pattern_id": 4, "hotspot_type": "no"}])
    panel = make_panel(qtbot, tmp_path)
    assert panel.skipped_label.text().startswith("Skipped (cold): 4 (NO).")


def test_the_candidates_are_listed_before_the_first_run(qtbot: QtBot, tmp_path: Path) -> None:
    dot = dot_dp_of(tmp_path)
    write_unsure(dot, [3, 4])
    panel = make_panel(qtbot, tmp_path)
    assert row_texts(panel) == [
        ["3", "main.cpp:13", "1", "Not checked", "", "", ""],
        ["4", "main.cpp:14", "1", "Not checked", "", "", ""],
    ]
    panel.table.selectRow(0)
    details = panel.details_view.toPlainText()
    assert "not checked yet" in details and "RAW dependency" in details
    assert not panel.publish_button.isEnabled()
