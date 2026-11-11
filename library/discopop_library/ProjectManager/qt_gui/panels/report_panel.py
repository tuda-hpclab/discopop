# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Report tab: the execution results as a table and as charts, the PDF report, and the resets.

Ported from ``gui/mixins/report_panel.py`` and ``gui/mixins/report.py``.
"""

import copy
import functools
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QMenu,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.Amdahl.model import SuggestionRegion
from discopop_library.Amdahl.regions import load_regions
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import mode_style, report_charts
from discopop_library.ProjectManager.plots.data import ExecutionRecord, parse_execution_results
from discopop_library.ProjectManager.qt_gui import chart_embedding, dialogs, widgets
from discopop_library.ProjectManager.qt_gui.detail_bar import DetailBar
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.reports.full import generate_full_report
from discopop_library.ProjectManager.services.jobs import WorkEvent, WorkFinished
from discopop_library.ProjectManager.services.project_state import ProjectState, ResultsChanged
from discopop_library.ProjectManager.services.reports import (
    ReportProblem,
    NO_VALUE,
    find_latest_report_pdf,
    format_limit,
    format_ratio,
    format_seconds,
    format_suggestion_ids,
    has_execution_results,
)
from discopop_library.ProjectManager.utilities.reset import reset_project

# chart types offered by the "+" button: a menu label and the stem of the tab title
PLOT_TYPES: Dict[str, Dict[str, str]] = {
    "pareto": {"label": "Trade-off scatter", "stem": "Scatter"},
    "scaling": {"label": "Thread scaling", "stem": "Scaling"},
    "spbars": {"label": "Speedup / efficiency bars", "stem": "Bars"},
    "rtbars": {"label": "Runtime bars", "stem": "Runtime"},
    "amdahl": {"label": "Speedup vs. Amdahl ceiling", "stem": "Amdahl"},
    "amdahl_bubble": {"label": "Amdahl bubble chart (size = efficiency)", "stem": "Amdahl bubbles"},
    "amdahl3d": {"label": "Amdahl ceiling / efficiency / speedup (3D)", "stem": "Amdahl 3D"},
}

TABLE_COLUMNS = (
    "Config",
    "Script",
    "Setting",
    "Label",
    "Applied Suggestions",
    "Not Applied",
    "Threads",
    "Status",
    "Time",
    "Speedup",
    "Efficiency",
    "Amdahl ceiling",
    "Amdahl limit",
)

# the columns holding numbers (right-aligned): Threads, Time, Speedup, Efficiency, Amdahl ceiling, Amdahl limit
_NUMERIC_COLUMNS = frozenset({6, 8, 9, 10, 11, 12})
_LABEL_COLUMN = 3  # takes the width the other columns leave
_EMPTY_TEXT = "No execution results yet — run a configuration in the Execute stage."
_NOT_APPLIED_BG = "#f3e6f7"
_BEST_BG = "#d6ebd5"
_DETAIL_BAR_WIDTH = 280


@dataclass
class PlotTab:
    """One chart tab: its type, its controls and the figure it draws into."""

    plot_type: str
    widget: QWidget
    figure: Any
    canvas: Any
    detail: DetailBar
    combos: Dict[str, QComboBox] = field(default_factory=dict)
    checks: Dict[str, QCheckBox] = field(default_factory=dict)


def load_execution_records(project_dir: str) -> List[ExecutionRecord]:
    path = os.path.join(project_dir, "execution_results.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return parse_execution_results(data, _load_regions(project_dir))


def _load_regions(project_dir: str) -> Optional[Dict[int, SuggestionRegion]]:
    """Suggestion runtime shares for the Amdahl ceilings; None if they cannot be derived."""
    try:
        # execution_results.json lives in <.discopop>/project
        return load_regions(os.path.dirname(os.path.normpath(project_dir))) or None
    except Exception:  # noqa: BLE001 -- the report must work without the ceilings
        return None


def record_fields(record: ExecutionRecord) -> List[tuple[str, str]]:
    """What the detail bar shows for a clicked record."""
    fields = [
        ("Config", record.config),
        ("Mode", record.mode),
        ("Suggestions", format_suggestion_ids(record.applied_suggestions) if record.applied_suggestions else "(none)"),
        ("Threads", str(record.thread_count)),
        ("Runtime", f"{record.time:.3f} s" if record.has_measurement else "not executed"),
        ("Status", report_charts.record_status_text(record)),
    ]
    if record.application_failed:
        fields.append(
            (
                "Not applied",
                (
                    format_suggestion_ids(record.failed_suggestions or record.requested_suggestions)
                    if (record.failed_suggestions or record.requested_suggestions)
                    else "(unknown)"
                ),
            )
        )
    if record.speedup is not None:
        fields.append(("Speedup", f"{record.speedup:.3f}×"))
    if record.efficiency is not None:
        fields.append(("Efficiency", f"{record.efficiency:.3f}"))
    if record.amdahl_ceiling is not None:
        fields.append(("Amdahl ceiling", f"{record.amdahl_ceiling:.3f}× ({record.thread_count} threads)"))
        limit = record.amdahl_limit
        fields.append(("Amdahl limit", "unbounded" if limit is None or limit == float("inf") else f"{limit:.3f}×"))
        fields.append(("Parallel fraction", f"{record.parallel_fraction:.3f} (estimate)"))
    fields.append(("Script", record.script))
    fields.append(("Label", record.label or "(unnamed)"))
    return fields


class ReportPanel(Panel):
    """The Report tab.

    ``append_output`` receives the progress of the PDF report (the main window passes the console of the Execute
    tab); without it the progress goes to the status line only.
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        append_output: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self._append_output = append_output
        self._execution_running = False
        self.plot_tabs: List[PlotTab] = []
        self._plot_counter = 0

        self.generate_report_button = widgets.primary_button("Generate PDF Report", self.generate_report)
        self.view_report_button = widgets.create_button("View Report PDF", self.view_report)
        self.view_report_button.setEnabled(False)
        self.reload_button = widgets.create_button("Reload", self.update_display)
        self.overflow = widgets.overflow_button(
            [
                ("Reset Execution Results…", self._confirm_reset_results),
                ("Reset Project…", self._confirm_reset_project),
            ]
        )
        menu_actions = self.overflow.menu().actions()
        self.reset_results_action, self.reset_project_action = menu_actions[0], menu_actions[1]
        self.header = widgets.PanelHeader(
            "Report",
            "Measured runs of all configurations: table and charts.",
            [self.view_report_button, self.reload_button, self.generate_report_button, self.overflow],
        )

        # the results: a permanent Table tab and closable chart tabs, added from the "+" menu in the corner
        self.notebook = QTabWidget()
        self.notebook.setTabsClosable(True)
        self.notebook.tabCloseRequested.connect(self._close_tab)
        self.table = self._build_table()
        # without results a caption says what to do instead of an empty table
        self.empty_label = widgets.caption_label(_EMPTY_TEXT)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.empty_label)
        self.table_stack.addWidget(self.table)
        self.notebook.addTab(self.table_stack, "Table")
        table_close = self.notebook.tabBar().tabButton(0, self.notebook.tabBar().ButtonPosition.RightSide)
        if table_close is not None:
            table_close.resize(0, 0)
            table_close.hide()
        self.add_plot_button = QToolButton()
        self.add_plot_button.setText("＋")
        self.add_plot_button.setToolTip("Add a chart")
        self.add_plot_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.add_plot_button)
        for key, meta in PLOT_TYPES.items():
            action = QAction(meta["label"], menu)
            action.triggered.connect(functools.partial(self.add_plot, key))
            menu.addAction(action)
        self.add_plot_button.setMenu(menu)
        self.notebook.setCornerWidget(self.add_plot_button, Qt.Corner.TopRightCorner)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.notebook, 1)

        project_state.subscribe(ResultsChanged, lambda _event: self.update_display())
        # open with one chart of every type; more can be added from the "+" menu
        for plot_type in PLOT_TYPES:
            self.add_plot(plot_type)
        self.notebook.setCurrentIndex(1)  # the first chart, not whichever was added last
        self.update_display()

    # ── the table ───────────────────────────────────────────────────────────

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, len(TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(list(TABLE_COLUMNS))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_LABEL_COLUMN, QHeaderView.ResizeMode.Stretch)
        return table

    def records(self) -> List[ExecutionRecord]:
        return load_execution_records(self.arguments.project_dir)

    def update_display(self) -> None:
        """Refresh the table, the open charts and the report buttons from ``execution_results.json``."""
        records = self.records()
        self._fill_table(records)
        for tab in self.plot_tabs:
            self._render(tab)
        self.generate_report_button.setEnabled(
            not self._execution_running and has_execution_results(self.arguments.project_dir)
        )

    def _fill_table(self, records: List[ExecutionRecord]) -> None:
        # the best (highest speedup) valid record per configuration is highlighted
        best_index: Dict[str, int] = {}
        best_speedup: Dict[str, float] = {}
        for index, record in enumerate(records):
            if record.valid and record.speedup is not None and record.speedup > best_speedup.get(record.config, -1.0):
                best_speedup[record.config] = record.speedup
                best_index[record.config] = index

        self.table.setRowCount(len(records))
        previous: tuple[Optional[str], Optional[str], Optional[str]] = (None, None, None)
        for row, record in enumerate(records):
            # a value repeated from the row above is left out, which groups the rows visually
            config = record.config if record.config != previous[0] else ""
            script = record.script if (record.config, record.script) != previous[:2] else ""
            setting = record.mode if (record.config, record.script, record.mode) != previous else ""
            previous = (record.config, record.script, record.mode)
            not_applied = (
                format_suggestion_ids(record.failed_suggestions or record.requested_suggestions)
                if record.application_failed
                else NO_VALUE
            )
            values = (
                config,
                script,
                setting,
                record.label or NO_VALUE,
                format_suggestion_ids(record.applied_suggestions),
                not_applied,
                str(record.thread_count),
                report_charts.record_status_text(record),
                # a skipped run has no runtime to show
                format_seconds(record.time) if record.has_measurement else NO_VALUE,
                format_ratio(record.speedup),
                format_ratio(record.efficiency),
                format_ratio(record.amdahl_ceiling),
                format_limit(record.amdahl_limit),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in _NUMERIC_COLUMNS:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                # a skipped run (suggestions not applied) is neither a failure nor a result
                if record.application_failed:
                    item.setForeground(QColor(mode_style.status_color(mode_style.NOT_APPLIED_STATUS)))
                    item.setBackground(QColor(_NOT_APPLIED_BG))
                elif not record.valid:
                    item.setForeground(QColor(widgets.STATUS_FAIL))
                if best_index.get(record.config) == row:
                    item.setBackground(QColor(_BEST_BG))
                self.table.setItem(row, column, item)
        self.table_stack.setCurrentWidget(self.table if records else self.empty_label)

    # ── the chart tabs ───────────────────────────────────────────────────────

    def add_plot(self, plot_type: str) -> PlotTab:
        self._plot_counter += 1
        title = f"{PLOT_TYPES[plot_type]['stem']} {self._plot_counter}"
        canvas_widget, figure, canvas, _toolbar = chart_embedding.create_canvas()
        detail = DetailBar()
        detail.setMinimumWidth(160)
        container = QWidget()
        tab = PlotTab(plot_type, container, figure, canvas, detail)

        # the chart on the left, the always-visible detail bar on the right (draggable), the controls below
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(canvas_widget)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, _DETAIL_BAR_WIDTH])
        layout = QVBoxLayout(container)
        layout.addWidget(splitter, 1)
        layout.addLayout(self._build_controls(tab))

        self.plot_tabs.append(tab)
        self.notebook.addTab(container, title)
        self.notebook.setCurrentWidget(container)
        self._render(tab)
        return tab

    def _build_controls(self, tab: PlotTab) -> Any:
        configs = ["all"] + sorted({record.config for record in self.records()})
        items: List[Any] = []

        def add_combo(label: str, key: str, values: List[str], default: str) -> None:
            combo = QComboBox()
            combo.addItems(values)
            combo.setCurrentText(default)
            combo.currentTextChanged.connect(lambda _text: self._render(tab))
            tab.combos[key] = combo
            items.extend([QLabel(label + ":"), combo, 8])

        def add_check(label: str, key: str, default: bool) -> None:
            check = QCheckBox(label)
            check.setChecked(default)
            check.toggled.connect(lambda _checked: self._render(tab))
            tab.checks[key] = check
            items.extend([check, 8])

        if tab.plot_type == "pareto":
            add_combo("X", "x", ["efficiency", "speedup", "threads"], "efficiency")
            add_combo("Y", "y", ["speedup", "efficiency", "runtime"], "speedup")
            add_combo("Config", "config", configs, "all")
            add_check("Frontier", "frontier", True)
            add_check("Valid only", "valid_only", False)
        elif tab.plot_type == "scaling":
            add_combo("Metric", "metric", ["speedup", "runtime", "efficiency"], "speedup")
            add_combo("Config", "config", configs, "all")
            add_check("Ideal", "ideal", True)
        elif tab.plot_type in ("amdahl", "amdahl_bubble"):
            add_combo("Ceiling", "x_mode", list(report_charts.AMDAHL_X_MODES), "both")
            add_combo("Config", "config", configs, "all")
            add_check("Hide failed", "valid_only", True)
        elif tab.plot_type == "amdahl3d":
            add_combo("View", "view", list(report_charts.AMDAHL_3D_VIEWS), "free")
            add_combo("Config", "config", configs, "all")
            add_check("Hide failed", "valid_only", True)
            fit = widgets.create_button(
                "Fit view",
                lambda: self._render(tab, reset_camera=True),
                tooltip="Resize all axes to the visible points and reset the camera to the selected view "
                "(undoes zooming and rotating)",
            )
            items.extend([fit, 8])
        # the bar charts have a fixed metric (spbars: speedup, rtbars: runtime) and no controls
        return widgets.hbox(*items, None)

    def _render(self, tab: PlotTab, reset_camera: bool = False) -> None:
        records = [record for record in self.records() if record.script == "execute.sh"]
        on_select = functools.partial(self._on_record_selected, tab)
        combos, checks = tab.combos, tab.checks
        if tab.plot_type == "pareto":
            report_charts.render_pareto(
                tab.figure,
                records,
                x_metric=combos["x"].currentText(),
                y_metric=combos["y"].currentText(),
                config_filter=combos["config"].currentText(),
                valid_only=checks["valid_only"].isChecked(),
                show_frontier=checks["frontier"].isChecked(),
                on_select=on_select,
            )
        elif tab.plot_type == "scaling":
            report_charts.render_scaling(
                tab.figure,
                records,
                metric=combos["metric"].currentText(),
                config_filter=combos["config"].currentText(),
                show_ideal=checks["ideal"].isChecked(),
                on_select=on_select,
            )
        elif tab.plot_type in ("amdahl", "amdahl_bubble"):
            report_charts.render_amdahl_scatter(
                tab.figure,
                records,
                x_mode=combos["x_mode"].currentText(),
                config_filter=combos["config"].currentText(),
                valid_only=checks["valid_only"].isChecked(),
                on_select=on_select,
                size_by_efficiency=tab.plot_type == "amdahl_bubble",
            )
        elif tab.plot_type == "amdahl3d":
            report_charts.render_amdahl_3d(
                tab.figure,
                records,
                config_filter=combos["config"].currentText(),
                valid_only=checks["valid_only"].isChecked(),
                view=combos["view"].currentText(),
                on_select=on_select,
                keep_camera=not reset_camera,
            )
        elif tab.plot_type == "spbars":
            report_charts.render_bars(tab.figure, records, metric="speedup", on_select=on_select)
        elif tab.plot_type == "rtbars":
            report_charts.render_bars(tab.figure, records, metric="runtime", on_select=on_select)
        chart_embedding.redraw(tab.canvas)

    def _on_record_selected(self, tab: PlotTab, record: ExecutionRecord) -> None:
        tab.detail.show_fields(record_fields(record))

    def _close_tab(self, index: int) -> None:
        widget = self.notebook.widget(index)
        if widget is None or widget is self.table_stack:
            return
        self.plot_tabs = [tab for tab in self.plot_tabs if tab.widget is not widget]
        self.notebook.removeTab(index)
        widget.deleteLater()
        self.notebook.setCurrentIndex(0)

    # ── the PDF report ───────────────────────────────────────────────────────

    def set_execution_running(self, running: bool) -> None:
        """No report while an execution writes the results it would read (the Execute tab calls this)."""
        self._execution_running = running
        if running:
            self.generate_report_button.setEnabled(False)
            self.view_report_button.setEnabled(False)
        else:
            self.update_display()
            self.view_report_button.setEnabled(find_latest_report_pdf(self.arguments.project_dir)[0] is not None)

    def _report_progress(self, text: str) -> None:
        if self._append_output is not None:
            self._append_output(text + "\n")

    def generate_report(self) -> None:
        self.generate_report_button.setEnabled(False)
        self.status.set("Generating report...", widgets.STATUS_BUSY)
        self._report_progress("Generating report...")
        arguments = copy.copy(self.arguments)
        arguments.show_report = False

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self.generate_report_button.setEnabled(True)
            if event.error is None:
                self._report_progress("Report generated.")
                self.status.set("Report generated.", widgets.STATUS_OK, reset_ms=5000)
                self.view_report_button.setEnabled(True)
            else:
                self._report_progress(f"Error generating report: {event.error}")
                self.status.set("Error generating report", widgets.STATUS_FAIL)

        start_work(self, lambda _context: generate_full_report(arguments), handle)

    def view_report(self) -> None:
        report_path, problem = find_latest_report_pdf(self.arguments.project_dir)
        if report_path is None:
            messages = {
                ReportProblem.NO_REPORTS_DIRECTORY: "No report found. Generate one first.",
                ReportProblem.NO_REPORT: "No report found.",
            }
            message = messages.get(problem, "No report PDF found.") if problem is not None else "No report PDF found."
            dialogs.show_warning(self, "No report", message)
            return
        open_file(report_path)

    # ── resets ───────────────────────────────────────────────────────────────

    def _confirm_reset_results(self) -> None:
        if dialogs.ask_yes_no(
            self,
            "Confirm Reset",
            "Are you sure you want to reset execution results?\nThis will delete all execution data and reports.",
        ):
            self.reset(results_only=True)

    def _confirm_reset_project(self) -> None:
        if dialogs.ask_yes_no(
            self,
            "Confirm Reset",
            "Are you sure you want to reset the entire project?\n"
            "This will delete all data except the configuration files.",
        ):
            self.reset(results_only=False)

    def reset(self, *, results_only: bool) -> None:
        arguments = copy.copy(self.arguments)
        arguments.reset = not results_only
        arguments.reset_execution_results = results_only
        what = "Execution results" if results_only else "Project"
        try:
            reset_project(arguments)
        except Exception as e:
            self.status.set(f"Error resetting {what.lower()}: {e}", widgets.STATUS_FAIL)
            return
        self.view_report_button.setEnabled(False)
        self.status.set(f"{what} reset successfully", widgets.STATUS_OK)
        self.project_state.publish(ResultsChanged())


def open_file(path: str) -> None:
    """Open ``path`` with the desktop's default application (xdg-open, open, start), without a shell."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
