# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Patch Repair tab: fixing suggestions whose patch does not compile.

Ported from ``gui/mixins/patch_repair_panel.py``; what the tab shows is computed by
``services/patch_repair_view.py``. The "LLM Agent" box (stored connection, or backend and model) is shared with the
Blocker Resolution tab (``qt_gui/llm_agent_panel.py``).
"""

import queue
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.PatchRepair.PatchRepairArguments import DEFAULT_HOTSPOT_TYPES
from discopop_library.PatchRepair.results import PROGRESS_PREFIX
from discopop_library.ProjectManager.plots.data import split_progress_events
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter
from discopop_library.ProjectManager.qt_gui.llm_agent_panel import LlmAgentPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.services import patch_repair_view
from discopop_library.ProjectManager.services.commands import patch_repair_command
from discopop_library.ProjectManager.services.jobs import (
    CancelPolicy,
    JobEvent,
    JobFailedToStart,
    JobFinished,
    JobOutput,
    JobRunner,
    JobSpec,
)
from discopop_library.ProjectManager.services.patches import has_patches
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    ConfigChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import PatchRepairRequest
from discopop_library.ProjectManager.services.text import clean_ansi_output

RUN_TEXT = "Run Patch Repair"
_SETTINGS_WIDTH = 480
DESCRIPTION = "An LLM agent repairs suggestions whose patches do not build or validate."
NOT_RUN_TEXT = "Not run yet"
NO_RESULTS_TEXT = "No repair run yet."

_TONE_COLORS = {
    patch_repair_view.TONE_IDLE: widgets.STATUS_IDLE,
    patch_repair_view.TONE_BUSY: widgets.STATUS_BUSY,
    patch_repair_view.TONE_OK: widgets.STATUS_OK,
    patch_repair_view.TONE_FAIL: widgets.STATUS_FAIL,
    patch_repair_view.TONE_STOP: widgets.STATUS_STOP,
}
_CHIP_LEVELS = {
    patch_repair_view.TONE_IDLE: widgets.CHIP_IDLE,
    patch_repair_view.TONE_BUSY: widgets.CHIP_BUSY,
    patch_repair_view.TONE_OK: widgets.CHIP_OK,
    patch_repair_view.TONE_FAIL: widgets.CHIP_ERROR,
    patch_repair_view.TONE_STOP: widgets.CHIP_WARN,
}
_COLUMNS = ("Suggestion", "Hotspot", "Status", "Files", "Attempts", "First error")


class PatchRepairPanel(LlmAgentPanel):
    """The Patch Repair tab.

    Subscribes to ``ConfigChanged`` and ``PatternsChanged`` (the run button needs patches and a configuration)
    and publishes ``AutotuningChanged`` and ``ResultsChanged`` after a run that ended without an error: a repaired
    patch changes what the tuner and the report show. The main window calls :meth:`reload_connections` on
    ``LlmConfigChanged``.
    """

    output_title = "Patch Repair"
    llm_shared_with = "the blocker resolution"

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self.running = False
        self._job: Optional[JobRunner] = None
        # results.json as it currently stands, keyed by suggestion id (as a string)
        self._records: Dict[str, Dict[str, Any]] = {}

        self.console = self.make_console()
        self.run_button = widgets.RunStopButton(RUN_TEXT, self._run, self._stop)
        self.run_button.setEnabled(False)
        self.header = widgets.PanelHeader("Patch Repair", DESCRIPTION, [self.run_button])
        self.header.chip.set_status(widgets.CHIP_IDLE, NOT_RUN_TEXT)
        self.selector = SuggestionSelector(arguments.dot_dp, "patch_repair_scope")
        self._build_settings()
        self._build_agent_settings()
        self._build_scope()
        self._build_advanced()

        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(self._settings_box)
        column_layout.addWidget(self._agent_box)
        column_layout.addWidget(self._scope_box)
        column_layout.addWidget(self._advanced)
        self.splitter = widgets.SettingsSplitter(column, self._build_results(), _SETTINGS_WIDTH)
        self.header.add_action(self.splitter.toggle_button, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(self.splitter, 1)

        project_state.subscribe(ConfigChanged, lambda _event: self._update_ui())
        project_state.subscribe(PatternsChanged, lambda _event: self._update_ui())
        self.reload_connections()
        self._update_budget()
        self._update_ui()
        self._load_results_from_file()
        # no results.json yet means nothing rendered the diff panes, which would leave them blank rather than saying why
        self._show_diff()

    # ── construction ────────────────────────────────────────────────────────

    def _build_settings(self) -> None:
        # NO is unchecked by default: a cold suggestion contributes negligibly to the runtime, so repairing it spends
        # agent tokens and build time on code that will never be worth parallelizing.
        default_types = [t.strip() for t in DEFAULT_HOTSPOT_TYPES.split(",")]
        self.hotspot_checks: Dict[str, QCheckBox] = {}
        for htype in ["yes", "maybe", "no"]:
            check = QCheckBox(htype.upper())
            check.setChecked(htype in default_types)
            self.hotspot_checks[htype] = check
        self.log_level_combo = widgets.log_level_selector("INFO")
        self.dry_run_check = QCheckBox("Dry run (do not modify the patches)")

        section = widgets.FormSection("Settings")
        section.add_row(
            "Hotspot types:",
            widgets.hbox(*self.hotspot_checks.values(), None, spacing=20),
            "NO suggestions are skipped by default to save time and agent cost. "
            "Without hotspot results every suggestion counts as YES.",
        )
        section.add_widget(
            self.dry_run_check,
            "A repair is still built to check it, so a patch file is written and put back; "
            "it ends the run exactly as it started.",
        )
        self._settings_box = section

    def _build_agent_settings(self) -> None:
        self._agent_box = self.build_llm_agent_section("Empty: the backend's default model.")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setSingleStep(10)
        self.timeout_spin.setValue(300)
        self.prompts_spin = QSpinBox()
        self.prompts_spin.setRange(1, 10)
        self.prompts_spin.setValue(2)
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(2)
        self.prompts_spin.valueChanged.connect(lambda _value: self._update_budget())
        self.retries_spin.valueChanged.connect(lambda _value: self._update_budget())

    def _build_scope(self) -> None:
        section = widgets.FormSection("Suggestion Scope")
        section.add_widget(widgets.caption_label("Suggestions to consider (the hotspot filter applies on top):"))
        section.add_widget(self.selector)
        self._scope_box = section

    def _build_advanced(self) -> None:
        section = widgets.FormSection()
        section.add_row("Agent timeout (s):", self.timeout_spin)
        budget_hint = section.add_row(
            "Prompts / retries:",
            widgets.hbox(
                self.prompts_spin,
                widgets.caption_label("prompts"),
                12,
                self.retries_spin,
                widgets.caption_label("retries"),
                None,
            ),
            " ",
        )
        assert budget_hint is not None
        self.budget_label = budget_hint
        section.add_widget(
            widgets.caption_label(
                "A prompt is an independent attempt with a fresh context; a retry is a "
                "follow-up turn in the same conversation, told what was wrong."
            )
        )
        section.add_row("Log level:", self.log_level_combo)
        self._advanced = widgets.CollapsibleSection(
            "Advanced", section, summary="agent timeout, prompts, retries, log level"
        )

    def _build_results(self) -> QTabWidget:
        notebook = QTabWidget()

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column, width in enumerate((80, 60, 150, 60, 65)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        # the first error is the widest and least essential column: it takes whatever room is left, and the full
        # text is in the console and in results.json rather than only here
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        # an empty table says what to do instead of showing bare column headers
        self.empty_label = widgets.empty_state_label(NO_RESULTS_TEXT)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_label)
        self.results_stack.addWidget(self.table)
        notebook.addTab(self.results_stack, "Results")

        self.file_combo = QComboBox()
        self.file_combo.setMinimumContentsLength(30)
        # a suggestion's patch set can hold several files, and a repair may have changed only some of them
        self.file_combo.activated.connect(lambda _index: self._show_diff())
        # which suggestion is shown is the one selected in the Results tab; without saying so, an empty pane reads
        # as "there is nothing to show"
        self.diff_source_label = widgets.caption_label("")
        self.diff_original = widgets.CodeView()
        self.diff_repaired = widgets.CodeView()
        # stacked rather than side by side: what a repair changes is almost always the pragma, which is the longest
        # line in the patch
        panes = QSplitter(Qt.Orientation.Vertical)
        for title, view in (
            ("Generated patch (before repair)", self.diff_original),
            ("Patch in use (after repair)", self.diff_repaired),
        ):
            pane = QWidget()
            pane_layout = QVBoxLayout(pane)
            pane_layout.setContentsMargins(0, 0, 0, 0)
            pane_layout.addWidget(widgets.heading_label(title))
            pane_layout.addWidget(view, 1)
            panes.addWidget(pane)
        diff_tab = QWidget()
        diff_layout = QVBoxLayout(diff_tab)
        diff_layout.addLayout(widgets.hbox(QLabel("File:"), self.file_combo, self.diff_source_label, None))
        diff_layout.addWidget(panes, 1)
        notebook.addTab(diff_tab, "Patch")
        return notebook

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    # ── state ───────────────────────────────────────────────────────────────

    def _update_budget(self) -> None:
        self.budget_label.setText(patch_repair_view.budget_text(self.prompts_spin.value(), self.retries_spin.value()))
        widgets.set_label_color(self.budget_label, widgets.STATUS_IDLE)

    def _update_ui(self) -> None:
        """Enable the run button only once there are patches to repair."""
        if self.running:
            return
        self.run_button.setEnabled(self._prerequisites_met())
        self.selector.refresh()

    def _prerequisites_met(self) -> bool:
        """Patches must exist: without them there is nothing to build and nothing to fix."""
        return has_patches(self.arguments.dot_dp) and bool(self.project_state.current_config)

    def _set_summary(self, text: str, tone: str) -> None:
        """Show the outcome in the header chip: the first sentence as the chip, the rest behind "Details"."""
        first, _separator, rest = text.partition(". ")
        if rest:
            self.header.chip.set_status(_CHIP_LEVELS[tone], first, rest)
        else:
            self.header.chip.set_status(_CHIP_LEVELS[tone], text)

    # ── running ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "Patch repair is already running.")
            return
        if not self.project_state.current_config:
            dialogs.show_error(self, "No Configuration Selected", "Please select a configuration first.")
            return
        if self._connection_problem:
            # patch repair would fail on it before repairing anything
            dialogs.show_error(self, "LLM Connection", self._connection_problem)
            return

        self.running = True
        self.run_button.set_running(True)
        self.set_busy(True)
        self.output_requested.emit()
        self.status.set("Patch repair in progress...", widgets.STATUS_BUSY)

        self.console.clear()
        self._records = {}
        self._refresh_table()
        self.header.chip.set_status(widgets.CHIP_BUSY, "Starting…")

        # the job's thread must not read widgets or selectors
        request = self._snapshot_request()
        dot_discopop = self.arguments.dot_dp
        self.console.append_text("Starting patch repair...\n")
        self._announce_request(request)

        events: "queue.Queue[JobEvent]" = queue.Queue()
        # A subprocess, never in-process: the tool drives the autotuner and an external agent. SIGINT rather than
        # terminate(): the tool finishes the suggestion it is on and writes results.json, instead of leaving a
        # half-written patch behind. Sent to the process group as a terminal does, so the autotuner and the program
        # it measures stop too.
        job = JobRunner(
            JobSpec(
                patch_repair_command(request, dot_discopop),
                cwd=dot_discopop,
                cancel_policy=CancelPolicy.SIGINT_GROUP,
                new_session=True,
            ),
            events,
        )
        self._job = job
        QtJobAdapter(self, events, self._on_job_event).start()
        job.start()

    def _snapshot_request(self) -> PatchRepairRequest:
        """Read the panel into an immutable request; call on the main thread only."""
        selected_types = [name for name, check in self.hotspot_checks.items() if check.isChecked()]
        hotspot_types = ",".join(selected_types) if selected_types else DEFAULT_HOTSPOT_TYPES
        suggestion_ids: Optional[Tuple[str, ...]] = None
        if not self.selector.is_all_selected():
            suggestion_ids = tuple(self.selector.get_selected_ids())
        return PatchRepairRequest(
            connection=self._selected_connection() or None,
            configuration=self.project_state.current_config or "tiny",
            hotspot_types=hotspot_types,
            prompts=self.prompts_spin.value(),
            retries=self.retries_spin.value(),
            agent_timeout=self.timeout_spin.value(),
            log_level=self.log_level_combo.currentText(),
            backend=self.backend_combo.currentText(),
            model=self.model_combo.currentText().strip(),
            dry_run=self.dry_run_check.isChecked(),
            suggestion_ids=suggestion_ids,
        )

    def _announce_request(self, request: PatchRepairRequest) -> None:
        if request.suggestion_ids is not None:
            self.console.append_text(
                "Restricting to suggestion IDs: " + (", ".join(request.suggestion_ids) or "(none)") + "\n"
            )
        self.console.append_text("Configuration:\n")
        self.console.append_text("  Configuration: " + request.configuration + "\n")
        self.console.append_text("  Hotspot Types: " + request.hotspot_types + "\n")
        if request.connection:
            self.console.append_text("  Connection: " + request.connection + "\n\n")
        else:
            self.console.append_text("  Backend: " + request.backend + "\n")
            self.console.append_text("  Model: " + (request.model or "(default)") + "\n\n")

    def _on_job_event(self, event: JobEvent) -> None:
        """Handle one event of the patch repair job; runs on the main thread."""
        if isinstance(event, JobOutput):
            progress_events, residual = split_progress_events(event.line + "\n", PROGRESS_PREFIX)
            for progress_event in progress_events:
                self._on_progress(progress_event)
            cleaned = clean_ansi_output(residual.rstrip("\n"))
            if cleaned:
                self.console.append_text(cleaned + "\n")
        elif isinstance(event, JobFinished):
            self._job = None
            if event.cancelled:
                self.console.append_text("\nPatch repair stopped.\n")
                self._on_complete(stopped=True)
            elif event.returncode != 0:
                self.console.append_text(
                    "\nError: Patch repair exited with return code " + str(event.returncode) + "\n"
                )
                self._on_complete(error=True)
            else:
                self.console.append_text("\nPatch repair completed.\n")
                self._on_complete()
        elif isinstance(event, JobFailedToStart):
            self._job = None
            self.console.append_text("\nError: " + event.error + "\n")
            self._on_complete(error=True)

    def _on_progress(self, event: Dict[str, Any]) -> None:
        """Update the table and the summary from one structured progress event."""
        if str(event.get("event") or "") == "suggestion":
            self._records[str(event.get("suggestion_id"))] = dict(event)
            self._refresh_table()
        for text, tone in patch_repair_view.progress_summary(event):
            self._set_summary(text, tone)

    def _stop(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping patch repair...", widgets.STATUS_STOP)

    def _on_complete(self, error: bool = False, stopped: bool = False) -> None:
        self.running = False
        # results.json is the authoritative record: rebuild from it so the table is complete even if a live event
        # was missed
        self._load_results_from_file()
        self.run_button.set_running(False, enabled_after=True)
        self.set_busy(False)

        if error:
            self.header.chip.set_status(widgets.CHIP_ERROR, "Failed", "See the output pane for the error.")
            self.status.set("Patch repair failed", widgets.STATUS_FAIL, reset_ms=4000)
            return
        if stopped:
            self.header.chip.set_status(widgets.CHIP_WARN, "Stopped")
            self.status.set("Patch repair stopped", widgets.STATUS_IDLE, reset_ms=4000)
            return
        if self.header.chip.level == widgets.CHIP_BUSY:  # no "done" event arrived
            self.header.chip.set_status(widgets.CHIP_OK, "Completed")

        repaired = sum(1 for r in self._records.values() if r.get("status") == "repaired")
        if repaired:
            self.status.set(
                "Patch repair completed - " + str(repaired) + " patch set(s) repaired",
                widgets.STATUS_OK,
                reset_ms=6000,
            )
        else:
            self.status.set("Patch repair completed", widgets.STATUS_IDLE, reset_ms=6000)

        # a repaired patch changes what the tuner and the report show
        self.project_state.publish(AutotuningChanged())
        self.project_state.publish(ResultsChanged())

    def cancel_jobs(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self._cancel_backend_query()

    # ── results display ─────────────────────────────────────────────────────

    def _load_results_from_file(self) -> None:
        records = patch_repair_view.load_results(self.arguments.dot_dp)
        if records is not None:
            self._records = records
            self._refresh_table()

    def _selected_id(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows(0)
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item is not None else None

    def _refresh_table(self) -> None:
        previous = self._selected_id()
        rows = patch_repair_view.result_rows(self._records)
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setRowCount(len(rows))
            self.results_stack.setCurrentWidget(self.table if rows else self.empty_label)
            for index, row in enumerate(rows):
                color = QColor(_TONE_COLORS[row.tone])
                for column, value in enumerate(row.cells()):
                    item = QTableWidgetItem(value)
                    item.setForeground(color)
                    self.table.setItem(index, column, item)
            # the Patch tab renders whichever suggestion is selected here, so an unselected table leaves that tab
            # blank -- and rebuilding the table on every progress event would otherwise drop the user's selection
            chosen = patch_repair_view.preferred_row(rows, previous)
            if chosen is not None:
                index = [row.suggestion_id for row in rows].index(chosen)
                self.table.selectRow(index)
                chosen_item = self.table.item(index, 0)
                if chosen_item is not None:
                    self.table.scrollToItem(chosen_item)
        finally:
            self.table.blockSignals(False)
        self._on_row_selected()

    def _on_row_selected(self) -> None:
        suggestion_id = self._selected_id()
        self.file_combo.clear()
        if suggestion_id is None:
            self._show_diff()
            return
        labels, preferred = patch_repair_view.file_labels(
            self._records.get(suggestion_id, {}), self.arguments.dot_dp, suggestion_id
        )
        self.file_combo.addItems(labels)
        if preferred:
            self.file_combo.setCurrentText(preferred)
        self._show_diff()

    def _show_diff(self) -> None:
        source, original, repaired = patch_repair_view.diff_texts(
            self.arguments.dot_dp,
            self._selected_id(),
            patch_repair_view.file_id_of_label(self.file_combo.currentText()),
            bool(self._records),
        )
        self.diff_source_label.setText(source)
        self.diff_original.set_diff(original)
        self.diff_repaired.set_diff(repaired)
