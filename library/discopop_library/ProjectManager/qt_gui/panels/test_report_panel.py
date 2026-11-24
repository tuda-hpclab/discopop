# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import functools
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from discopop_library.Amdahl import regions
from discopop_library.Amdahl.model import SuggestionExtent
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import report_panel
from discopop_library.ProjectManager.qt_gui.panels.report_panel import ReportPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.jobs import WorkFinished, WorkOutput
from discopop_library.ProjectManager.services.project_state import ProjectState, ResultsChanged


def results() -> Dict[str, Any]:
    return {
        "tiny": {
            "execute.sh": {
                "seq_settings.json": [{"applied_suggestions": [], "code": 0, "time": 10.0, "thread_count": 1}],
                "par_settings.json": [
                    {"applied_suggestions": [3, 7], "code": 0, "time": 4.0, "thread_count": 8, "label": "auto"},
                    {"applied_suggestions": [3], "code": 1, "time": 1.0, "thread_count": 8},
                ],
            }
        }
    }


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> ReportPanel:
    arguments = make_arguments(tmp_path)
    status = StatusLine()
    qtbot.addWidget(status)
    output: List[str] = []
    created = ReportPanel(arguments, ProjectState(), status, output.append)
    created.output = output  # type: ignore[attr-defined]
    qtbot.addWidget(created)
    return created


def write_results(panel: ReportPanel) -> None:
    Path(panel.arguments.project_dir, "execution_results.json").write_text(json.dumps(results()))


def test_without_results_the_table_is_empty_and_no_report_can_be_generated(panel: ReportPanel) -> None:
    assert panel.table.rowCount() == 0
    # an empty table is replaced by a caption saying what to do
    assert panel.table_stack.currentWidget() is panel.empty_label
    assert panel.empty_label.text().startswith("No execution results yet")
    assert not panel.generate_report_button.isEnabled() and not panel.view_report_button.isEnabled()
    # one chart of every type is open next to the table, the first of them shown
    titles = [panel.notebook.tabText(i) for i in range(panel.notebook.count())]
    assert titles[:3] == ["Table", "Scatter 1", "Scaling 2"] and len(titles) == 1 + len(report_panel.PLOT_TYPES)
    assert panel.notebook.currentIndex() == 1


def test_results_changed_refreshes_the_table(panel: ReportPanel) -> None:
    write_results(panel)
    panel.project_state.publish(ResultsChanged())
    assert panel.table.rowCount() == 3
    first_row = [panel.table.item(0, column).text() for column in range(3)]  # type: ignore[union-attr]
    second_row = [panel.table.item(1, column).text() for column in range(3)]  # type: ignore[union-attr]
    # repeated values are left out
    assert first_row == ["tiny", "execute.sh", "seq"] and second_row == ["", "", "par"]
    assert panel.generate_report_button.isEnabled()
    assert panel.table_stack.currentWidget() is panel.table


def test_the_table_formats_its_values(panel: ReportPanel) -> None:
    write_results(panel)
    panel.project_state.publish(ResultsChanged())

    def row(index: int) -> List[str]:
        return [panel.table.item(index, column).text() for column in range(13)]  # type: ignore[union-attr]

    # label, applied, not applied, threads, status, time, speedup, efficiency, Amdahl ceiling, Amdahl limit
    assert row(0)[3:] == ["—", "—", "—", "1", "✓ valid", "10.0 s", "1.00", "1.00", "—", "—"]
    assert row(1)[3:8] == ["auto", "3, 7", "—", "8", "✓ valid"] and row(1)[8:11] == ["4.00 s", "2.50", "0.31"]
    for index in range(3):
        assert not any(text in ("[]", "None") or "[" in text for text in row(index))
    item = panel.table.item(1, 8)
    assert item is not None and item.textAlignment() & Qt.AlignmentFlag.AlignRight
    # the last column does not stretch: the label column takes the spare width
    header = panel.table.horizontalHeader()
    assert not header.stretchLastSection()


def test_chart_tabs_are_added_from_the_menu_and_closed(panel: ReportPanel) -> None:
    write_results(panel)
    opened = len(panel.plot_tabs)
    tab = panel.add_plot("scaling")
    assert panel.notebook.currentWidget() is tab.widget and len(panel.plot_tabs) == opened + 1
    tab.combos["metric"].setCurrentText("runtime")  # re-renders without an error
    panel.notebook.tabCloseRequested.emit(2)
    assert len(panel.plot_tabs) == opened and panel.notebook.count() == opened + 1
    # the table cannot be closed
    panel.notebook.tabCloseRequested.emit(0)
    assert panel.notebook.tabText(0) == "Table"


def test_a_clicked_record_shows_in_the_detail_bar(panel: ReportPanel) -> None:
    write_results(panel)
    records = panel.records()
    tab = panel.plot_tabs[0]
    panel._on_record_selected(tab, records[1])
    assert ("Speedup", "2.500×") in tab.detail.fields and ("Label", "auto") in tab.detail.fields


def test_generate_report_runs_in_the_background(qtbot: QtBot, panel: ReportPanel) -> None:
    write_results(panel)
    panel.update_display()
    with mock.patch.object(report_panel, "generate_full_report") as generate:
        panel.generate_report_button.click()
        assert not panel.generate_report_button.isEnabled()
        qtbot.waitUntil(lambda: panel.view_report_button.isEnabled(), timeout=5000)
    generate.assert_called_once()
    assert generate.call_args.args[0].show_report is False
    assert panel.output == ["Generating report...\n", "Report generated.\n"]  # type: ignore[attr-defined]
    assert panel.status.text() == "Report generated." and panel.generate_report_button.isEnabled()


def test_a_failing_report_is_reported(qtbot: QtBot, panel: ReportPanel) -> None:
    write_results(panel)
    panel.update_display()
    with mock.patch.object(report_panel, "generate_full_report", side_effect=RuntimeError("no latex")):
        panel.generate_report()
        qtbot.waitUntil(lambda: panel.status.color == widgets.STATUS_FAIL, timeout=5000)
    assert "Error generating report: no latex\n" in panel.output  # type: ignore[attr-defined]
    assert not panel.view_report_button.isEnabled()


def test_view_report_opens_the_newest_pdf_or_says_there_is_none(
    panel: ReportPanel, dialog_answers: DialogRecorder
) -> None:
    panel.view_report()
    assert dialog_answers.messages("show_warning") == ["No report found. Generate one first."]
    report_dir = Path(panel.arguments.project_dir, "reports", "2026-10-17")
    report_dir.mkdir(parents=True)
    (report_dir / "full_report.pdf").write_text("%PDF")
    with mock.patch.object(report_panel, "open_file") as open_file:
        panel.view_report()
    assert open_file.call_args.args[0].endswith("full_report.pdf")


def test_the_report_follows_results_changed(panel: ReportPanel) -> None:
    write_results(panel)
    panel.project_state.publish(ResultsChanged())
    assert panel.table.rowCount() == 3
    # a reset in Project Setup deletes the results and the reports
    Path(panel.arguments.project_dir, "execution_results.json").unlink()
    panel.project_state.publish(ResultsChanged())
    assert panel.table.rowCount() == 0 and not panel.view_report_button.isEnabled()


def test_3d_tab_has_hide_failed_and_fit_view(panel: ReportPanel) -> None:
    write_results(panel)
    tab = panel.add_plot("amdahl3d")
    assert "valid_only" in tab.checks and tab.checks["valid_only"].text() == "Hide failed"
    # failed runs are hidden by default on every Amdahl chart
    for plot_type in ("amdahl", "amdahl_bubble", "amdahl3d"):
        assert panel.add_plot(plot_type).checks["valid_only"].isChecked()
    tab.checks["valid_only"].setChecked(False)  # re-renders without an error
    buttons = {b.text() for b in tab.widget.findChildren(QPushButton)}
    assert "Fit view" in buttons
    next(b for b in tab.widget.findChildren(QPushButton) if b.text() == "Fit view").click()


def count_calls(monkeypatch: pytest.MonkeyPatch, target: Any, name: str) -> List[int]:
    """Count the calls of ``target.name`` (still calling it)."""
    calls: List[int] = []
    original = getattr(target, name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, counted)
    return calls


def test_a_refresh_parses_the_results_once_and_only_after_a_change(
    panel: ReportPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    parses = count_calls(monkeypatch, report_panel, "load_execution_records")
    renders = count_calls(monkeypatch, panel, "_render")
    write_results(panel)
    panel.project_state.publish(ResultsChanged())
    # once, not once per chart
    assert len(parses) == 1 and len(renders) == len(panel.plot_tabs) and panel.table.rowCount() == 3
    # an event without a change of the results neither parses nor redraws
    panel.project_state.publish(ResultsChanged())
    assert len(parses) == 1 and len(renders) == len(panel.plot_tabs)
    # "Reload" redraws without parsing the unchanged file again
    panel.reload_button.click()
    assert len(parses) == 1 and len(renders) == 2 * len(panel.plot_tabs)


def test_a_chart_control_redraws_without_parsing(panel: ReportPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    write_results(panel)
    panel.update_display()
    parses = count_calls(monkeypatch, report_panel, "load_execution_records")
    renders = count_calls(monkeypatch, panel, "_render")
    panel.plot_tabs[1].combos["metric"].setCurrentText("runtime")
    assert len(renders) == 1 and parses == []


def record_start(started: List[Any], _parent: Any, work: Any, handle: Any) -> Any:
    """Stands in for ``start_work``: records the work instead of running it."""
    started.append((work, handle))
    return mock.Mock()


def test_the_cost_estimate_scales_with_the_detection_result() -> None:
    text = report_panel.extraction_cost_text(int(1.2 * 1024**3))
    assert "(1.2 GiB)" in text and "about 42.0 GiB of memory" in text


def dot_discopop(panel: ReportPanel) -> Path:
    return Path(report_panel.dot_discopop_of(panel.arguments.project_dir))


def write_old_dump(panel: ReportPanel) -> Path:
    """A detection result of an older explorer: a dump without suggestion extents."""
    dump = Path(regions.dump_path_of(str(dot_discopop(panel))))
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text("dump of an older explorer")
    return dump


def test_missing_suggestion_extents_are_computed_on_request_only(
    panel: ReportPanel, monkeypatch: pytest.MonkeyPatch, dialog_answers: DialogRecorder
) -> None:
    def no_decode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("decoded in the GUI process")

    monkeypatch.setattr(regions, "extract_suggestion_extents", no_decode)
    write_results(panel)
    dump = write_old_dump(panel)
    panel.project_state.publish(ResultsChanged())
    assert panel.amdahl_notice.isVisibleTo(panel) and panel.compute_amdahl_button.isEnabled()
    # the notice recommends the pattern detection and names the cost of the alternative
    assert "run the pattern detection again" in panel.amdahl_label.text()
    assert "(25 B)" in panel.amdahl_label.text()

    started: List[Any] = []
    monkeypatch.setattr(report_panel, "start_work", functools.partial(record_start, started))
    # the cost is confirmed first: "No" starts nothing
    dialog_answers.answer("ask_yes_no", False)
    panel.compute_amdahl_button.click()
    assert started == [] and dialog_answers.titles("ask_yes_no") == ["Compute Amdahl ceilings"]
    dialog_answers.answer("ask_yes_no", True)
    panel.compute_amdahl_button.click()
    assert len(started) == 1 and not panel.compute_amdahl_button.isEnabled()
    panel.compute_amdahl_button.click()  # a second click while it runs starts nothing
    assert len(started) == 1

    # the work runs the extraction as a separate process of this interpreter
    work, handle = started[0]
    context = mock.Mock()
    context.run_command.return_value = 0
    assert work(context) == 0
    spec = context.run_command.call_args.args[0]
    assert spec.command[1:] == ["-m", "discopop_library.Amdahl.regions", "--extract-extents", str(dot_discopop(panel))]

    # the process wrote the extents: the notice disappears and the ceilings are read
    regions.write_suggestion_extents(str(dump), {3: SuggestionExtent(3, 1, 10, 20)})
    handle(WorkOutput("Wrote the extents of 1 suggestions"))
    handle(WorkFinished(0, None))
    assert not panel.amdahl_notice.isVisibleTo(panel) and panel.compute_amdahl_button.isEnabled()
    assert "Wrote the extents of 1 suggestions\n" in panel.output  # type: ignore[attr-defined]
    assert panel.status.text() == "Amdahl ceilings computed."


def test_a_failed_extraction_is_reported(
    panel: ReportPanel, monkeypatch: pytest.MonkeyPatch, dialog_answers: DialogRecorder
) -> None:
    write_old_dump(panel)
    dialog_answers.answer("ask_yes_no", True)
    started: List[Any] = []
    monkeypatch.setattr(report_panel, "start_work", functools.partial(record_start, started))
    panel.compute_amdahl_ceilings()
    started[0][1](WorkFinished(1, None))
    assert "Computing the Amdahl ceilings failed: exit code 1\n" in panel.output  # type: ignore[attr-defined]
    assert panel.status.color == widgets.STATUS_FAIL
    # still missing: the notice stays, the button can be used again
    assert panel.amdahl_notice.isVisibleTo(panel) and panel.compute_amdahl_button.isEnabled()


def test_an_error_of_the_amdahl_regions_is_reported_once(panel: ReportPanel, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_dot_dp: str) -> Any:
        raise ValueError("broken extents")

    monkeypatch.setattr(report_panel, "load_regions", broken)
    write_results(panel)
    panel.update_display()
    panel.reload_button.click()
    panel.project_state.publish(ResultsChanged())
    # the report works without the ceilings
    assert panel.table.rowCount() == 3
    assert panel.output.count("Amdahl ceilings unavailable: broken extents\n") == 1  # type: ignore[attr-defined]
