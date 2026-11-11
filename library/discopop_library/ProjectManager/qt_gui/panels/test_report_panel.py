# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import report_panel
from discopop_library.ProjectManager.qt_gui.panels.report_panel import ReportPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
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


def test_reset_asks_first_and_publishes_results_changed(panel: ReportPanel, dialog_answers: DialogRecorder) -> None:
    write_results(panel)
    panel.project_state.publish(ResultsChanged())
    dialog_answers.answer("ask_yes_no", False, True)
    panel.reset_results_action.trigger()
    assert panel.table.rowCount() == 3
    panel.reset_results_action.trigger()
    assert panel.table.rowCount() == 0
    assert panel.status.text() == "Execution results reset successfully"


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
