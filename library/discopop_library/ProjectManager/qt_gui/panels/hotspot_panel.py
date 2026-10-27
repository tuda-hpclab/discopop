# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Hotspot Detection tab: run measurements and present the analysis.

Ported from ``gui/mixins/hotspot_panel.py``. The measurement flow (instrument, measure, merge the runs, analyze)
is :class:`~discopop_library.ProjectManager.services.hotspot_session.HotspotSession`, the texts and rows shown
here come from ``services/hotspot_view.py``; this panel owns the widgets.
"""

import functools
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QLabel,
    QMenu,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_charts
from discopop_library.ProjectManager.plots.hotspot_data import (
    HOTNESS_ORDER,
    KIND_FUNCTION,
    KIND_LOOP,
    HotspotRegion,
    MeasurementRun,
)
from discopop_library.ProjectManager.qt_gui import chart_embedding, dialogs, widgets
from discopop_library.ProjectManager.qt_gui.detail_bar import DetailBar
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import hotspot_view
from discopop_library.ProjectManager.services.hotspot_build import BUILD_CURRENT
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession, Timeouts
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.project_state import ConfigChanged, HotspotsChanged, ProjectState
from discopop_library.ProjectManager.services.vscode import (
    VSCODE_NOT_FOUND_MESSAGE,
    find_code_executable,
    open_file_at,
)

# Chart types offered by the "+" button: a menu label and the stem of the tab title.
PLOT_TYPES: Dict[str, Dict[str, str]] = {
    "quadrant": {"label": "Hotness quadrant", "stem": "Quadrant"},
    "bars": {"label": "Top-N runtime bars", "stem": "Bars"},
    "profile": {"label": "Per-region run profile", "stem": "Profile"},
}

_DETAIL_BAR_WIDTH = 300
_RESET_MS = 3000
_KEY_ROLE = Qt.ItemDataRole.UserRole

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}


@dataclass
class PlotTab:
    """One chart tab: its type, its controls, the figure it draws into and the region selected in it."""

    plot_type: str
    widget: QWidget
    figure: Any
    canvas: Any
    detail: DetailBar
    selection: Optional[HotspotRegion] = None
    top_n: Optional[QComboBox] = None
    region_combo: Optional[QComboBox] = None
    controls: Dict[str, QWidget] = field(default_factory=dict)


class HotspotPanel(Panel):
    """The Hotspot Detection tab.

    ``timeouts`` returns the (execution, compilation, validation) timeouts of the Execute tab, which a measurement
    uses; it is called on the main thread when a measurement starts. The panel publishes ``HotspotsChanged``
    whenever the hotspot results change (after a measurement, an analysis or after clearing) and shows the
    configuration of ``ConfigChanged``.
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        timeouts: Callable[[], Timeouts],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self._timeouts = timeouts
        self.running = False
        self.regions: List[HotspotRegion] = []
        self.runs: List[MeasurementRun] = []
        self.plot_tabs: List[PlotTab] = []
        self.regions_selection: Optional[HotspotRegion] = None
        self._regions_sort: Optional[Tuple[str, bool]] = None
        self._plot_counter = 0
        self._job: Optional[WorkRunner] = None
        self.session = HotspotSession(arguments)

        self.notebook = QTabWidget()
        self.notebook.setTabsClosable(True)
        self.notebook.tabCloseRequested.connect(self._close_plot)
        self.notebook.addTab(self._build_measurement_tab(), "Measurement")
        self.notebook.addTab(self._build_runs_tab(), "Runs")
        self.notebook.addTab(self._build_regions_tab(), "Regions")
        tab_bar = self.notebook.tabBar()
        for index in range(3):
            button = tab_bar.tabButton(index, tab_bar.ButtonPosition.RightSide)
            if button is not None:
                button.resize(0, 0)
                button.hide()
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.notebook)

        project_state.subscribe(ConfigChanged, lambda _event: self.update_ui())
        # open with the quadrant chart shown, mirroring the Report tab opening on a trade-off scatter
        self.add_plot("quadrant")
        self.notebook.setCurrentIndex(0)
        self.refresh_results()

    # ── construction ───────────────────────────────────────────────────────────

    def _build_measurement_tab(self) -> QWidget:
        self.config_label = QLabel()
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 20)
        self.repetitions.setValue(1)
        explanation = widgets.caption_label(
            "Hotness combines two criteria: average runtime, and how strongly a region's runtime\n"
            "varies across runs (ratio). Repeating one configuration only narrows measurement\n"
            "noise -- to make the ratio meaningful, measure several configurations, i.e. several\n"
            "inputs. Timeouts are taken from the Execute tab."
        )
        settings = widgets.group_box(
            "Measurement",
            widgets.vbox(
                widgets.hbox(widgets.heading_label("Configuration:"), self.config_label, None),
                widgets.hbox(QLabel("Repetitions:"), self.repetitions, None),
                explanation,
                margins=5,
            ),
        )

        self.build_label = QLabel()
        self.runs_label = QLabel()
        self.hotness_label = QLabel()
        self.warning_label = QLabel()
        widgets.set_label_color(self.warning_label, widgets.STATUS_STOP)
        self.warning_label.hide()
        status_box = widgets.group_box(
            "Status",
            widgets.vbox(self.build_label, self.runs_label, self.hotness_label, self.warning_label, margins=5),
        )

        self.run_button = widgets.primary_button("Run Measurement", self.run_measurement)
        self.stop_button = widgets.danger_button("Stop", self.stop_measurement)
        self.reinstrument_button = widgets.create_button("Re-instrument", self.reinstrument)
        self.analyze_button = widgets.create_button("Re-run Analysis", self.rerun_analysis)
        self.clear_button = widgets.danger_button("Clear Measurements", self.clear_measurements)
        for button in (
            self.run_button,
            self.stop_button,
            self.reinstrument_button,
            self.analyze_button,
            self.clear_button,
        ):
            button.setEnabled(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(settings)
        left_layout.addWidget(status_box)
        left_layout.addLayout(widgets.hbox(self.run_button, self.stop_button, None))
        left_layout.addLayout(widgets.hbox(self.reinstrument_button, self.analyze_button, self.clear_button, None))
        left_layout.addStretch(1)

        self.output = widgets.OutputConsole()
        right = widgets.group_box("Output", widgets.vbox(self.output, margins=5))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([650, 500])
        return splitter

    def _build_table(self, columns: Tuple[Tuple[str, int], ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels([name for name, _width in columns])
        for index, (_name, width) in enumerate(columns):
            table.setColumnWidth(index, width)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _build_runs_tab(self) -> QWidget:
        self.runs_table = self._build_table(hotspot_view.RUN_COLUMNS)
        caption = widgets.caption_label(
            "Each run is one execution of the instrumented binary. Runs recorded outside this tab\n"
            "(Execute tab in 'hd' mode, CLI, MCP server) show as (external)."
        )
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(caption)
        layout.addWidget(self.runs_table, 1)
        return tab

    def _build_regions_tab(self) -> QWidget:
        self.hotness_checks: Dict[str, QCheckBox] = {}
        filters: List[Any] = [QLabel("Hotness:")]
        for hotness in HOTNESS_ORDER:
            check = QCheckBox(hotness)
            check.setChecked(True)
            check.toggled.connect(lambda _checked: self._populate_regions_table())
            self.hotness_checks[hotness] = check
            filters.append(check)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems([hotspot_view.KIND_FILTER_ALL, KIND_LOOP, KIND_FUNCTION])
        self.kind_combo.currentTextChanged.connect(lambda _text: self._populate_regions_table())
        filters.extend([14, QLabel("Kind:"), self.kind_combo, None])

        self.regions_table = self._build_table(hotspot_view.REGION_COLUMNS)
        header = self.regions_table.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._sort_regions_by_section)
        self.regions_table.itemSelectionChanged.connect(self._on_region_row_selected)
        self.regions_detail = self._make_detail_bar(lambda: self.regions_selection)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.regions_table)
        splitter.addWidget(self.regions_detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, _DETAIL_BAR_WIDTH])

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(widgets.hbox(*filters))
        layout.addWidget(splitter, 1)
        return tab

    def _make_detail_bar(self, current: Callable[[], Optional[HotspotRegion]]) -> DetailBar:
        """A detail bar plus a "show in VSCode" action bound to ``current()``."""
        detail = DetailBar(placeholder=hotspot_view.DETAIL_PLACEHOLDER)
        detail.setMinimumWidth(160)
        detail.add_action(
            "Show in VSCode",
            lambda: self._open_region_in_vscode(current()),
            enabled=lambda: current() is not None,
        )
        return detail

    # ── the chart tabs ─────────────────────────────────────────────────────────

    def add_plot(self, plot_type: str) -> PlotTab:
        self._plot_counter += 1
        title = f"{PLOT_TYPES[plot_type]['stem']} {self._plot_counter}"
        canvas_widget, figure, canvas, _toolbar = chart_embedding.create_canvas()
        container = QWidget()
        created: List[PlotTab] = []  # the detail bar's action reads the selection of the tab that owns the bar
        detail = self._make_detail_bar(lambda: created[0].selection)
        tab = PlotTab(plot_type, container, figure, canvas, detail)
        created.append(tab)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(canvas_widget)
        splitter.addWidget(tab.detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([900, _DETAIL_BAR_WIDTH])
        layout = QVBoxLayout(container)
        layout.addWidget(splitter, 1)
        layout.addLayout(self._build_plot_controls(tab))

        self.plot_tabs.append(tab)
        self.notebook.addTab(container, title)
        self.notebook.setCurrentWidget(container)
        self._render(tab)
        return tab

    def _build_plot_controls(self, tab: PlotTab) -> Any:
        items: List[Any] = []
        if tab.plot_type == "bars":
            tab.top_n = QComboBox()
            tab.top_n.addItems(list(hotspot_charts.TOP_N_CHOICES))
            tab.top_n.setCurrentText(str(hotspot_charts.DEFAULT_TOP_N))
            tab.top_n.currentTextChanged.connect(lambda _text: self._render(tab))
            items.extend([QLabel("Show top:"), tab.top_n])
        elif tab.plot_type == "profile":
            # Selection is per-tab (as on the Report tab), so this chart carries its own region picker rather than
            # following another tab's selection.
            tab.region_combo = QComboBox()
            tab.region_combo.setMinimumWidth(380)
            tab.region_combo.currentIndexChanged.connect(lambda _index: self._render(tab))
            items.extend([QLabel("Region:"), tab.region_combo])
        items.append(None)
        close = widgets.danger_button("✕", lambda: self._close_tab_widget(tab.widget))
        items.append(close)
        return widgets.hbox(*items)

    def _close_tab_widget(self, widget: QWidget) -> None:
        index = self.notebook.indexOf(widget)
        if index >= 0:
            self._close_plot(index)

    def _close_plot(self, index: int) -> None:
        widget = self.notebook.widget(index)
        tab = next((candidate for candidate in self.plot_tabs if candidate.widget is widget), None)
        if widget is None or tab is None:
            return  # the three fixed tabs cannot be closed
        self.plot_tabs.remove(tab)
        self.notebook.removeTab(index)
        widget.deleteLater()
        self.notebook.setCurrentIndex(0)

    def _render(self, tab: PlotTab) -> None:
        regions = self.regions
        on_select = functools.partial(self._on_plot_region_selected, tab)
        if tab.plot_type == "quadrant":
            hotspot_charts.render_quadrant(tab.figure, regions, on_select=on_select)
        elif tab.plot_type == "bars":
            try:
                top_n = int(tab.top_n.currentText()) if tab.top_n is not None else hotspot_charts.DEFAULT_TOP_N
            except ValueError:
                top_n = hotspot_charts.DEFAULT_TOP_N
            hotspot_charts.render_top_bars(tab.figure, regions, top_n=top_n, on_select=on_select)
        elif tab.plot_type == "profile":
            hotspot_charts.render_run_profile(tab.figure, self._resolve_profile_region(tab), on_select=on_select)
        chart_embedding.redraw(tab.canvas)

    def _resolve_profile_region(self, tab: PlotTab) -> Optional[HotspotRegion]:
        """The region the profile tab's picker selects, defaulting to the hottest."""
        regions = self.regions
        combo = tab.region_combo
        if not regions:
            if combo is not None:
                self._set_combo_items(combo, [])
            return None
        if combo is None:
            return regions[0]

        labels = [hotspot_view.region_choice_label(region) for region in regions]
        previous = combo.currentText()
        if [combo.itemText(index) for index in range(combo.count())] != labels:
            self._set_combo_items(combo, labels)
        # regions are sorted hottest-first, so the first entry is the hottest
        combo.blockSignals(True)
        combo.setCurrentIndex(labels.index(previous) if previous in labels else 0)
        combo.blockSignals(False)
        return regions[combo.currentIndex()]

    @staticmethod
    def _set_combo_items(combo: QComboBox, labels: List[str]) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(labels)
        combo.blockSignals(False)

    # ── selection ──────────────────────────────────────────────────────────────

    def _on_plot_region_selected(self, tab: PlotTab, region: HotspotRegion) -> None:
        tab.selection = region
        tab.detail.show_fields(hotspot_view.region_detail_fields(region))

    def _on_region_row_selected(self) -> None:
        rows = self.regions_table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.regions_table.item(rows[0].row(), 0)
        key = item.data(_KEY_ROLE) if item is not None else ""
        match = next((region for region in self.regions if region.key.serialize() == key), None)
        self.regions_selection = match
        if match is None:
            self.regions_detail.show_placeholder()
        else:
            self.regions_detail.show_fields(hotspot_view.region_detail_fields(match))

    def _open_region_in_vscode(self, region: Optional[HotspotRegion]) -> None:
        if region is None:
            return
        code_executable = find_code_executable()
        if code_executable is None:
            dialogs.show_error(self, "VSCode Not Found", VSCODE_NOT_FOUND_MESSAGE)
            return
        if not os.path.exists(region.key.path):
            dialogs.show_warning(
                self, "File Not Found", f"The recorded source path no longer exists:\n{region.key.path}"
            )
            return
        try:
            open_file_at(code_executable, region.key.path, region.key.line)
        except OSError as e:
            dialogs.show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")

    # ── data loading and display ───────────────────────────────────────────────

    def refresh_results(self) -> None:
        """Reload Hotspots.json and the run log, then refresh every view."""
        results = self.session.load_results()
        self.regions = results.regions
        self.runs = results.runs

        # A selection from a previous analysis may no longer exist.
        self.regions_selection = None
        self.regions_detail.show_placeholder()

        self._populate_regions_table()
        self._populate_runs_table()
        for tab in self.plot_tabs:
            tab.selection = None
            tab.detail.show_placeholder()
            self._render(tab)
        self.update_ui()

    def _sort_regions_by_section(self, section: int) -> None:
        self._regions_sort = hotspot_view.next_sort(self._regions_sort, hotspot_view.REGION_COLUMNS[section][0])
        self._populate_regions_table()

    def visible_regions(self) -> List[HotspotRegion]:
        allowed = {hotness for hotness, check in self.hotness_checks.items() if check.isChecked()}
        return hotspot_view.visible_regions(self.regions, allowed, self.kind_combo.currentText(), self._regions_sort)

    def _populate_regions_table(self) -> None:
        table = self.regions_table
        regions = self.visible_regions()
        table.setRowCount(0)
        table.setRowCount(len(regions))
        for row, region in enumerate(regions):
            color = QBrush(QColor(hotspot_charts.hotness_color(region.hotness)))
            for column, value in enumerate(hotspot_view.region_row(region)):
                item = QTableWidgetItem(value)
                item.setForeground(color)
                if column == 0:
                    # the serialized key lets a row click recover its region without a parallel index
                    item.setData(_KEY_ROLE, region.key.serialize())
                table.setItem(row, column, item)

    def _populate_runs_table(self) -> None:
        table = self.runs_table
        table.setRowCount(0)
        table.setRowCount(len(self.runs))
        for row, run in enumerate(self.runs):
            for column, value in enumerate(hotspot_view.run_row(run)):
                item = QTableWidgetItem(value)
                if hotspot_view.run_failed(run):
                    item.setForeground(QBrush(QColor(widgets.STATUS_FAIL)))
                table.setItem(row, column, item)

    # ── prerequisites and button states ────────────────────────────────────────

    @property
    def current_config(self) -> Optional[str]:
        return self.project_state.current_config

    @staticmethod
    def _show(label: QLabel, text: str, color: Optional[str]) -> None:
        label.setText(text)
        # no color: the palette's own text color, which is readable in a dark theme too
        label.setStyleSheet("" if color is None else f"color: {color};")

    def update_ui(self) -> None:
        """Show the selected configuration, the build state, the accumulated runs and the button states."""
        current_config = self.current_config
        if current_config:
            self._show(self.config_label, current_config, None)
        else:
            self._show(self.config_label, "(none selected)", widgets.STATUS_IDLE)

        state, detail = self.session.build_state(current_config)
        summary = hotspot_view.measurement_summary(state, detail, self.runs, self.regions)
        self._show(self.build_label, summary.build_text, widgets.STATUS_OK if summary.build_ok else widgets.STATUS_STOP)
        self._show(self.runs_label, summary.runs_text, None)
        self._show(self.hotness_label, summary.hotness_text, None if summary.has_regions else widgets.STATUS_IDLE)
        self.warning_label.setText("\n".join(summary.warnings))
        self.warning_label.setVisible(bool(summary.warnings))

        idle = not self.running
        has_config = bool(current_config)
        self.run_button.setEnabled(idle and has_config)
        self.reinstrument_button.setEnabled(idle and has_config)
        self.analyze_button.setEnabled(idle and bool(self.runs))
        self.clear_button.setEnabled(idle and self.session.has_data())

    # ── running measurements ───────────────────────────────────────────────────

    def _run_job(self, work: Callable[[WorkContext], bool]) -> None:
        """Run ``work`` on a worker thread and show what it reports; ``_on_work_complete`` ends it."""
        job: List[WorkRunner] = []

        def handle(event: WorkEvent) -> None:
            self._on_event(job[0], event)

        self._job = start_work(self, work, handle)
        job.append(self._job)

    def _on_event(self, job: WorkRunner, event: WorkEvent) -> None:
        """Handle one event of the hotspot work; runs on the main thread."""
        if isinstance(event, WorkOutput):
            self.output.append_text(event.text)
        elif isinstance(event, WorkStatus):
            # after Stop, a late progress status would hide "Stopping ..."
            if self._job is None or not self._job.cancel_requested:
                self.status.set(event.text, _STATUS_COLORS[event.kind])
        elif isinstance(event, WorkFinished):
            if event.error is not None:  # a crash of the work must not leave the UI stuck
                self.output.append_text(f"\nError: {event.error}\n")
            self._job = None
            self._on_work_complete(bool(event.result) and event.error is None, job.cancel_requested)

    def run_measurement(self) -> None:
        self._start_work(execute_runs=True)

    def reinstrument(self) -> None:
        self._start_work(execute_runs=False, force_compile=True)

    def _start_work(self, *, execute_runs: bool, force_compile: bool = False) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        config = self.current_config
        if not config:
            dialogs.show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return

        state, _detail = self.session.build_state(config)
        needs_compile = force_compile or state != BUILD_CURRENT
        repetitions = max(1, self.repetitions.value()) if execute_runs else 0
        request = self.session.make_request(
            config, needs_compile=needs_compile, repetitions=repetitions, timeouts=self._timeouts()
        )

        self.running = True
        self.update_ui()
        self.run_button.setEnabled(False)
        self.run_button.setText("⟳ Running...")
        self.stop_button.setEnabled(True)
        self.output.clear()
        self.status.set("⏳ Hotspot measurement in progress...", widgets.STATUS_BUSY)
        self._run_job(lambda ctx: self.session.run(ctx, request))

    def rerun_analysis(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        self.running = True
        self.update_ui()
        self.stop_button.setEnabled(True)
        self.output.clear()
        self.status.set("⏳ Hotspot analysis in progress...", widgets.STATUS_BUSY)
        self._run_job(self.session.invoke_analyzer)

    def _on_work_complete(self, success: bool, cancelled: bool) -> None:
        self.running = False
        self.run_button.setText("Run Measurement")
        self.stop_button.setEnabled(False)

        self.refresh_results()
        # the analyzer's output gates the hotspot types of the Autotuning tab and the hint of Pattern Detection
        self.project_state.publish(HotspotsChanged())

        if cancelled:
            self.status.set("Hotspot measurement stopped", widgets.STATUS_STOP, reset_ms=_RESET_MS)
        elif success:
            self.status.set("Hotspot measurement completed", widgets.STATUS_OK, reset_ms=_RESET_MS)
        else:
            self.status.set("Hotspot measurement failed", widgets.STATUS_FAIL, reset_ms=_RESET_MS)

    def stop_measurement(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.stop_button.setEnabled(False)
        self.status.set("Stopping hotspot measurement...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        """Stop a running measurement (the window is closing)."""
        if self._job is not None:
            self._job.cancel()

    # ── clearing ───────────────────────────────────────────────────────────────

    def clear_measurements(self) -> None:
        if self.running:
            dialogs.show_error(self, "Measurement Running", "Stop the running measurement first.")
            return
        if not dialogs.ask_yes_no(
            self,
            "Clear Measurements",
            f"Delete the accumulated hotspot measurements ({len(self.runs)} run(s)) and the analysis results?\n\n"
            "The instrumented build stays in place, but the next measurement will re-instrument.",
        ):
            return
        self.session.delete_hotspot_dir()
        self.output.clear()
        self.refresh_results()
        self.project_state.publish(HotspotsChanged())
        self.status.set("Hotspot measurements cleared", reset_ms=_RESET_MS)
