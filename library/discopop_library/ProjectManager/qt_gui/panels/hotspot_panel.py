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
    QHeaderView,
    QCheckBox,
    QComboBox,
    QLabel,
    QMenu,
    QSpinBox,
    QStackedWidget,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
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
from discopop_library.ProjectManager.services import hotspot_view, measurement_queue
from discopop_library.ProjectManager.services.configurations import list_configurations
from discopop_library.ProjectManager.services.hotspot_build import BUILD_CURRENT
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession, Timeouts
from discopop_library.ProjectManager.services.measurement_queue import MeasurementQueue
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkProgress,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    HotspotsChanged,
    ProjectState,
)
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

RUN_TEXT = "Run Measurements"
_DETAIL_BAR_WIDTH = 260
_SETTINGS_WIDTH = 330
_FIXED_TABS = 2  # Regions, Runs
_RESET_MS = 3000
_KEY_ROLE = Qt.ItemDataRole.UserRole
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_RUN_NUMERIC_COLUMNS = (0, 3, 5)  # Run, Time (s), Regions
_CONFIG_LIST_MAX_ROWS = 8
_STATE_COLORS = {
    measurement_queue.RUNNING: widgets.STATUS_BUSY,
    measurement_queue.MEASURED: widgets.STATUS_OK,
    measurement_queue.FAILED: widgets.STATUS_FAIL,
    measurement_queue.STOPPED: widgets.STATUS_STOP,
}

_CHIP_LEVELS = {
    hotspot_view.LEVEL_OK: widgets.CHIP_OK,
    hotspot_view.LEVEL_WARN: widgets.CHIP_WARN,
    hotspot_view.LEVEL_IDLE: widgets.CHIP_IDLE,
}

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

    The header holds the run / stop button, a "\u22ef" menu (re-instrument, re-run analysis, clear) and a chip with the
    state of the measurements; below it the settings are a narrow column left of the result tabs (Regions, Runs and
    the charts), so the regions are visible without switching tabs. The settings list the execution configurations
    with check boxes: Run Measurements measures the checked ones one after another (``HotspotSession.run_batch``)
    and analyzes all runs once at the end; the list shows the state of each (queued, measuring, measured, failed,
    stopped) and, between batches, how many runs it has. The console is in the output
    pane. ``timeouts`` returns the (execution, compilation, validation) timeouts of the Execute tab, which a
    measurement uses; it is called on the main thread when a measurement starts. The panel publishes
    ``HotspotsChanged`` whenever the hotspot results change (after a measurement, an analysis or after clearing) and
    follows the configuration of ``ConfigChanged``.
    """

    output_title = "Hotspots"

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
        # the configurations to measure (checked in the list). Until the user changes a check box, the list follows
        # the configuration selected in the header bar (only it is checked); afterwards the user's choice stays, and
        # a configuration created later starts unchecked.
        self._checked: Dict[str, bool] = {}
        self._user_chose = False
        self._filling_configs = False
        # the running batch, or the last one (its states stay visible until the next batch)
        self.queue: Optional[MeasurementQueue] = None

        self.output = self.make_console()

        self.notebook = QTabWidget()
        self.notebook.setTabsClosable(True)
        self.notebook.tabCloseRequested.connect(self._close_plot)
        self.notebook.addTab(self._build_regions_tab(), "Regions")
        self.notebook.addTab(self._build_runs_tab(), "Runs")
        tab_bar = self.notebook.tabBar()
        for index in range(_FIXED_TABS):
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

        self.header = self._build_header()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_settings())
        splitter.addWidget(self.notebook)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([_SETTINGS_WIDTH, 1000])
        splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.header)
        layout.addWidget(splitter, 1)

        project_state.subscribe(ConfigChanged, lambda _event: self.refresh_configurations())
        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh_configurations())
        # open with the quadrant chart shown, mirroring the Report tab opening on a trade-off scatter
        self.add_plot("quadrant")
        self.notebook.setCurrentIndex(0)
        self.refresh_results()

    # ── construction ───────────────────────────────────────────────────────────

    def _build_header(self) -> widgets.PanelHeader:
        self.run_button = widgets.RunStopButton(RUN_TEXT, self.run_measurement, self.stop_measurement)
        self.run_button.setEnabled(False)
        menu_button = widgets.overflow_button(
            [
                ("Re-instrument", self.reinstrument),
                ("Re-run Analysis", self.rerun_analysis),
                ("Clear Measurements\u2026", self.clear_measurements),
            ]
        )
        menu = menu_button.menu()
        assert menu is not None
        self.reinstrument_action, self.analyze_action, self.clear_action = menu.actions()
        for action in menu.actions():
            action.setEnabled(False)
        return widgets.PanelHeader(
            "Hotspot Detection",
            "Measures which code regions take the time; pattern detection, patch repair and the autotuner use the "
            "result.",
            [self.run_button, menu_button],
        )

    def _build_settings(self) -> QWidget:
        self.config_list = QTreeWidget()
        self.config_list.setColumnCount(2)
        self.config_list.setHeaderLabels(["Configuration", "Status"])
        self.config_list.setRootIsDecorated(False)
        self.config_list.setUniformRowHeights(True)
        self.config_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.config_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.config_list.header().setStretchLastSection(True)
        self.config_list.itemChanged.connect(self._on_config_item_changed)
        self.select_all_button = widgets.create_button("All", lambda: self._check_all(True))
        self.select_none_button = widgets.create_button("None", lambda: self._check_all(False))
        for button in (self.select_all_button, self.select_none_button):
            button.setObjectName(widgets.COMPACT_NAME)
        configs = widgets.FormSection("Execution configurations")
        configs.add_widget(
            self.config_list,
            "Run Measurements measures the checked configurations one after another and analyzes all runs at the "
            "end. Configurations with different inputs make the hotness meaningful.",
        )
        configs.add_widget(widgets.hbox(self.select_all_button, self.select_none_button, None, margins=0))

        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 20)
        self.repetitions.setValue(1)
        section = widgets.FormSection("Measurement")
        section.add_row(
            "Repetitions:",
            self.repetitions,
            "Runs per configuration. Hotness weighs the average runtime and how much it varies between runs; "
            "repeating one configuration only reduces noise. Timeouts come from the Execute stage.",
        )
        self.facts_label = widgets.caption_label("")
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.addWidget(configs)
        layout.addWidget(section)
        layout.addWidget(self.facts_label)
        layout.addStretch(1)
        column.setMinimumWidth(260)
        return column

    def _build_table(
        self, columns: Tuple[Tuple[str, int], ...], headers: Optional[Tuple[str, ...]] = None, stretch: int = -1
    ) -> QTableWidget:
        """A read-only table; columns fit their contents, column ``stretch`` takes the remaining width."""
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(list(headers) if headers else [name for name, _width in columns])
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if stretch >= 0:
            header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(stretch < 0)
        header.setMinimumSectionSize(50)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return table

    @staticmethod
    def _with_empty_state(content: QWidget, text: str) -> Tuple[QStackedWidget, QLabel]:
        """A stack showing ``text`` (page 0) or ``content`` (page 1)."""
        label = widgets.empty_state_label(text)
        stack = QStackedWidget()
        stack.addWidget(label)
        stack.addWidget(content)
        return stack, label

    def _build_runs_tab(self) -> QWidget:
        self.runs_table = self._build_table(hotspot_view.RUN_COLUMNS)
        self.runs_stack, self.runs_empty_label = self._with_empty_state(self.runs_table, hotspot_view.NO_RUNS_TEXT)
        caption = widgets.caption_label(
            "Each run is one execution of the instrumented binary. Runs recorded outside this tab\n"
            "(Execute tab in 'hd' mode, CLI, MCP server) show as (external)."
        )
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(caption)
        layout.addWidget(self.runs_stack, 1)
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

        self.regions_table = self._build_table(hotspot_view.REGION_COLUMNS, hotspot_view.REGION_HEADERS, stretch=3)
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

        self.regions_stack, self.regions_empty_label = self._with_empty_state(splitter, hotspot_view.NO_REGIONS_TEXT)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(widgets.hbox(*filters))
        layout.addWidget(self.regions_stack, 1)
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
        self._fill_config_list()
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
            for column, value in enumerate(hotspot_view.region_cells(region)):
                item = QTableWidgetItem(value)
                item.setForeground(color)
                if column in hotspot_view.REGION_NUMERIC_COLUMNS:
                    item.setTextAlignment(_RIGHT)
                if column == 0:
                    # the serialized key lets a row click recover its region without a parallel index
                    item.setData(_KEY_ROLE, region.key.serialize())
                table.setItem(row, column, item)
        if self.regions:
            self.regions_stack.setCurrentIndex(1)
        else:
            self.regions_empty_label.setText(
                hotspot_view.NO_ANALYSIS_TEXT if self.runs else hotspot_view.NO_REGIONS_TEXT
            )
            self.regions_stack.setCurrentIndex(0)

    def _populate_runs_table(self) -> None:
        table = self.runs_table
        table.setRowCount(0)
        table.setRowCount(len(self.runs))
        for row, run in enumerate(self.runs):
            for column, value in enumerate(hotspot_view.run_row(run)):
                item = QTableWidgetItem(value)
                if hotspot_view.run_failed(run):
                    item.setForeground(QBrush(QColor(widgets.STATUS_FAIL)))
                if column in _RUN_NUMERIC_COLUMNS:
                    item.setTextAlignment(_RIGHT)
                table.setItem(row, column, item)
        self.runs_stack.setCurrentIndex(1 if self.runs else 0)

    # ── the execution configurations ───────────────────────────────────────────

    def refresh_configurations(self) -> None:
        """The configurations on disk into the list, then the button states.

        Not while a batch runs: its list stays as it started (it is rebuilt when the batch ends).
        """
        if self.running:
            return
        self._fill_config_list()
        self.update_ui()

    def _config_status(self, name: str) -> Tuple[str, Optional[str]]:
        """The status column of ``name``: its state in the running / last batch, else its recorded runs."""
        runs = sum(1 for run in self.runs if run.config == name)
        runs_text = f"{runs} run" + ("" if runs == 1 else "s") if runs else "not measured"
        item = self.queue.item(name) if self.queue is not None else None
        if item is None or (item.state == measurement_queue.QUEUED and not self.running):
            return runs_text, None
        if item.state == measurement_queue.MEASURED:
            # its runs may have been cleared since
            return ("✓ " + runs_text, _STATE_COLORS[item.state]) if runs else (runs_text, None)
        return measurement_queue.state_text(item), _STATE_COLORS.get(item.state)

    def _fill_config_list(self) -> None:
        names = list_configurations(self.arguments.project_config_dir)
        self._filling_configs = True
        try:
            self.config_list.clear()
            current = self.project_state.current_config
            for name in names:
                if not self._user_chose:
                    self._checked[name] = name == current
                checked = self._checked.setdefault(name, False)
                status, color = self._config_status(name)
                item = QTreeWidgetItem([name, status])
                flags = Qt.ItemFlag.ItemIsEnabled | (
                    Qt.ItemFlag.NoItemFlags if self.running else Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setFlags(flags)
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setToolTip(1, status)
                if color is not None:
                    item.setForeground(1, QBrush(QColor(color)))
                self.config_list.addTopLevelItem(item)
        finally:
            self._filling_configs = False
        rows = max(1, min(len(names), _CONFIG_LIST_MAX_ROWS))
        row_height = self.config_list.sizeHintForRow(0) if names else 22
        self.config_list.setFixedHeight(self.config_list.header().sizeHint().height() + rows * row_height + 6)

    def _update_config_statuses(self) -> None:
        """The status column in place (on every state change of a running batch: keeps the scroll position)."""
        for row in range(self.config_list.topLevelItemCount()):
            item = self.config_list.topLevelItem(row)
            if item is None:
                continue
            status, color = self._config_status(item.text(0))
            self._filling_configs = True
            try:
                item.setText(1, status)
                item.setToolTip(1, status)
                item.setForeground(1, QBrush(QColor(color)) if color is not None else QBrush())
            finally:
                self._filling_configs = False

    def _on_config_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling_configs or column != 0:
            return
        self._checked[item.text(0)] = item.checkState(0) == Qt.CheckState.Checked
        self._user_chose = True
        self.update_ui()

    def _check_all(self, checked: bool) -> None:
        for name in list_configurations(self.arguments.project_config_dir):
            self._checked[name] = checked
        self._user_chose = True
        self.refresh_configurations()

    def selected_configs(self) -> List[str]:
        """The checked configurations, in the order of the list."""
        return [name for name in list_configurations(self.arguments.project_config_dir) if self._checked.get(name)]

    def set_selected_configs(self, names: List[str]) -> None:
        for name in list_configurations(self.arguments.project_config_dir):
            self._checked[name] = name in names
        self._user_chose = True
        self.refresh_configurations()

    # ── prerequisites and button states ────────────────────────────────────────

    @property
    def current_config(self) -> Optional[str]:
        """The configuration whose build the header describes and Re-instrument builds: the first checked one."""
        selected = self.selected_configs()
        return selected[0] if selected else None

    def update_ui(self) -> None:
        """Show the state of the measurements in the header and the button states."""
        current_config = self.current_config
        state, detail = self.session.build_state(current_config)
        status = hotspot_view.measurement_status(state, detail, self.runs, self.regions)
        self.facts_label.setText(status.facts)
        running_item = self.queue.running() if self.queue is not None else None
        if self.running and running_item is not None and self.queue is not None:
            position = self.queue.position(running_item.name)
            self.header.chip.set_status(
                widgets.CHIP_BUSY, f"Measuring {position} of {len(self.queue.items)}: {running_item.name}"
            )
        elif self.running:
            self.header.chip.set_status(widgets.CHIP_BUSY, "Measurement running")
        elif not current_config:
            self.header.chip.set_status(
                widgets.CHIP_IDLE,
                "No configuration selected",
                "Check the execution configurations to measure in the list on the left.",
            )
        else:
            self.header.chip.set_status(_CHIP_LEVELS[status.level], status.text, status.detail)

        idle = not self.running
        has_config = bool(current_config)
        self.run_button.setEnabled(idle and has_config)
        count = len(self.selected_configs())
        self.run_button.set_run_text(RUN_TEXT if count != 1 else "Run Measurement")
        self.run_button.setToolTip(
            "" if has_config or self.running else "Check at least one execution configuration in the list to measure."
        )
        self.select_all_button.setEnabled(idle)
        self.select_none_button.setEnabled(idle)
        self.reinstrument_action.setEnabled(idle and has_config)
        self.analyze_action.setEnabled(idle and bool(self.runs))
        self.clear_action.setEnabled(idle and self.session.has_data())

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
        elif isinstance(event, WorkProgress):
            if self.queue is not None:
                self.queue.apply(event.key, event.state, event.detail)
                self._update_config_statuses()
                self.update_ui()
        elif isinstance(event, WorkFinished):
            if event.error is not None:  # a crash of the work must not leave the UI stuck
                self.output.append_text(f"\nError: {event.error}\n")
            self._job = None
            self._on_work_complete(bool(event.result) and event.error is None, job.cancel_requested)

    def run_measurement(self) -> None:
        """Measure the checked configurations one after another, then analyze."""
        if self.running:
            dialogs.show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        configs = self.selected_configs()
        if not configs:
            dialogs.show_warning(
                self, "No Configuration Selected", "Check the execution configurations to measure first."
            )
            return
        repetitions = max(1, self.repetitions.value())
        timeouts = self._timeouts()
        self.queue = MeasurementQueue(configs)
        self.running = True
        self.run_button.set_running(True)
        self._fill_config_list()
        self.update_ui()
        self.output.clear()
        self.output_requested.emit()
        self.status.set("⏳ Hotspot measurement in progress...", widgets.STATUS_BUSY)
        self._run_job(lambda ctx: self.session.run_batch(ctx, configs, repetitions=repetitions, timeouts=timeouts))

    def reinstrument(self) -> None:
        self._start_work(execute_runs=False, force_compile=True)

    def _start_work(self, *, execute_runs: bool, force_compile: bool = False) -> None:
        """One configuration (the first checked one): Re-instrument, or a single measurement."""
        if self.running:
            dialogs.show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        config = self.current_config
        if not config:
            dialogs.show_warning(
                self, "No Configuration Selected", "Check the execution configurations to measure first."
            )
            return
        self.queue = None

        state, _detail = self.session.build_state(config)
        needs_compile = force_compile or state != BUILD_CURRENT
        repetitions = max(1, self.repetitions.value()) if execute_runs else 0
        request = self.session.make_request(
            config, needs_compile=needs_compile, repetitions=repetitions, timeouts=self._timeouts()
        )

        self.running = True
        self.run_button.set_running(True)
        self.update_ui()
        self.output.clear()
        self.output_requested.emit()
        self.status.set("⏳ Hotspot measurement in progress...", widgets.STATUS_BUSY)
        self._run_job(lambda ctx: self.session.run(ctx, request))

    def rerun_analysis(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        self.running = True
        self.run_button.set_running(True)
        self.update_ui()
        self.output.clear()
        self.output_requested.emit()
        self.status.set("⏳ Hotspot analysis in progress...", widgets.STATUS_BUSY)
        self._run_job(self.session.invoke_analyzer)

    def _on_work_complete(self, success: bool, cancelled: bool) -> None:
        self.running = False
        self.run_button.set_running(False)
        tally = ""
        if self.queue is not None:
            if cancelled or not self.queue.finished():
                # stopped, or the work ended early: what did not finish is stopped
                self.queue.stop_remaining()
            if len(self.queue.items) > 1:
                tally = " (" + self.queue.tally() + ")"

        self.refresh_results()
        # the analyzer's output gates the hotspot types of the Autotuning tab and the hint of Pattern Detection
        self.project_state.publish(HotspotsChanged())

        if cancelled:
            self.status.set("Hotspot measurement stopped" + tally, widgets.STATUS_STOP, reset_ms=_RESET_MS)
        elif success:
            self.status.set("Hotspot measurement completed" + tally, widgets.STATUS_OK, reset_ms=_RESET_MS)
        else:
            self.status.set("Hotspot measurement failed" + tally, widgets.STATUS_FAIL, reset_ms=_RESET_MS)

    def stop_measurement(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping hotspot measurement...", widgets.STATUS_STOP)

    def output_console(self) -> widgets.OutputConsole:
        return self.output

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
        self.queue = None
        self.output.clear()
        self.refresh_results()
        self.project_state.publish(HotspotsChanged())
        self.status.set("Hotspot measurements cleared", reset_ms=_RESET_MS)
