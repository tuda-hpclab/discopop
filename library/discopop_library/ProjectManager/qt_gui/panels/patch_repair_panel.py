# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Patch Repair tab: fixing suggestions whose patch does not compile.

Ported from ``gui/mixins/patch_repair_panel.py``; what the tab shows is computed by
``services/patch_repair_view.py``. The backend and model selectors are built from the ``llm_backends`` registry, so a
new agent reaches the GUI without touching this file.
"""

import queue
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.PatchRepairArguments import DEFAULT_HOTSPOT_TYPES
from discopop_library.PatchRepair.results import PROGRESS_PREFIX
from discopop_library.ProjectManager.plots.data import split_progress_events
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter, start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel
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
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkRunner,
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
RUNNING_TEXT = "⟳ Running..."
_SETTINGS_WIDTH = 650

_TONE_COLORS = {
    patch_repair_view.TONE_IDLE: widgets.STATUS_IDLE,
    patch_repair_view.TONE_BUSY: widgets.STATUS_BUSY,
    patch_repair_view.TONE_OK: widgets.STATUS_OK,
    patch_repair_view.TONE_FAIL: widgets.STATUS_FAIL,
    patch_repair_view.TONE_STOP: widgets.STATUS_STOP,
}
_COLUMNS = ("Suggestion", "Hotspot", "Status", "Files", "Attempts", "First error")


class PatchRepairPanel(Panel):
    """The Patch Repair tab.

    Subscribes to ``ConfigChanged`` and ``PatternsChanged`` (the run button needs patches and a configuration)
    and publishes ``AutotuningChanged`` and ``ResultsChanged`` after a run that ended without an error: a repaired
    patch changes what the tuner and the report show.
    """

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
        self._backend_query: Optional[WorkRunner] = None
        # results.json as it currently stands, keyed by suggestion id (as a string)
        self._records: Dict[str, Dict[str, Any]] = {}

        self.console = widgets.OutputConsole()
        self._build_settings()
        self._build_agent_settings()
        self.selector = SuggestionSelector(arguments.dot_dp, "patch_repair_scope")
        self.run_button = widgets.primary_button(RUN_TEXT, self._run)
        self.run_button.setEnabled(False)
        self.stop_button = widgets.danger_button("Stop", self._stop)
        self.stop_button.setEnabled(False)
        self.summary_label = widgets.caption_label("(not run yet)")

        scope_layout = QVBoxLayout()
        scope_layout.addWidget(widgets.caption_label("Suggestions to consider (the hotspot filter applies on top):"))
        scope_layout.addWidget(self.selector)
        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.addWidget(self._settings_box)
        column_layout.addWidget(self._agent_box)
        column_layout.addWidget(widgets.group_box("Suggestion Scope", scope_layout))
        column_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(column)

        outcome_layout = QVBoxLayout()
        outcome_layout.addWidget(self.summary_label)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(scroll, 1)
        left_layout.addLayout(widgets.hbox(self.run_button, self.stop_button, None, margins=5))
        left_layout.addWidget(widgets.group_box("Outcome", outcome_layout))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([_SETTINGS_WIDTH, 700])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        project_state.subscribe(ConfigChanged, lambda _event: self._update_ui())
        project_state.subscribe(PatternsChanged, lambda _event: self._update_ui())
        self._on_backend_changed()
        self._update_budget()
        self._update_ui()
        self._load_results_from_file()
        # no results.json yet means nothing rendered the diff panes, which would leave them blank rather than saying why
        self._show_diff()

    # ── construction ────────────────────────────────────────────────────────

    def _build_settings(self) -> None:
        self.config_label = widgets.caption_label("(none selected)")
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

        layout = QVBoxLayout()
        layout.addLayout(widgets.hbox(widgets.heading_label("Configuration:"), self.config_label, None))
        layout.addWidget(widgets.heading_label("Hotspot Types:"))
        layout.addLayout(widgets.hbox(*self.hotspot_checks.values(), None, spacing=30))
        layout.addWidget(
            widgets.caption_label(
                "NO suggestions are skipped by default to save time and agent cost. "
                "Without hotspot results every suggestion counts as YES."
            )
        )
        layout.addLayout(widgets.hbox(QLabel("Log Level:"), self.log_level_combo, None))
        layout.addWidget(self.dry_run_check)
        dry_run_caption = widgets.caption_label(
            "A repair is still built to check it, so a patch file is written and put back; "
            "it ends the run exactly as it started."
        )
        dry_run_caption.setContentsMargins(20, 0, 0, 0)
        layout.addWidget(dry_run_caption)
        self._settings_box = widgets.group_box("Settings", layout)

    def _build_agent_settings(self) -> None:
        # built from the registry, so a newly added agent reaches the GUI without a change here
        backends = llm_backends.available_backends()
        installed = llm_backends.first_installed_backend()
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(backends)
        self.backend_combo.setCurrentText(installed or (backends[0] if backends else ""))
        self.backend_combo.currentTextChanged.connect(lambda _text: self._on_backend_changed())
        self.backend_hint = widgets.caption_label("")
        # Editable, not read-only: a backend's model list depends on which providers are authenticated and is not
        # always exhaustive, so a model missing from it must still be typeable.
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText("")
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
        self.budget_label = widgets.caption_label("")

        layout = QVBoxLayout()
        layout.addLayout(widgets.hbox(QLabel("Backend:"), self.backend_combo, None))
        layout.addWidget(self.backend_hint)
        model_row = widgets.hbox(QLabel("Model:"), self.model_combo)
        model_row.setStretch(1, 1)
        layout.addLayout(model_row)
        layout.addWidget(widgets.caption_label("Leave empty to use the backend's own default model."))
        layout.addLayout(widgets.hbox(QLabel("Agent timeout (s):"), self.timeout_spin, None))
        layout.addLayout(
            widgets.hbox(QLabel("Prompts:"), self.prompts_spin, 15, QLabel("Retries:"), self.retries_spin, None)
        )
        layout.addWidget(self.budget_label)
        layout.addWidget(
            widgets.caption_label(
                "A prompt is an independent attempt with a fresh context; a retry is a "
                "follow-up turn in the same conversation, told what was wrong."
            )
        )
        self._agent_box = widgets.group_box("LLM Agent", layout)

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
        notebook.addTab(self.table, "📋 Results")

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
        notebook.addTab(diff_tab, "🔀 Patch")

        notebook.addTab(self.console, "🖥 Console")
        return notebook

    # ── state ───────────────────────────────────────────────────────────────

    def _on_backend_changed(self) -> None:
        """Refresh the model list and say so when the selected agent is not installed."""
        name = self.backend_combo.currentText()
        try:
            module = llm_backends.get(name)
        except KeyError:
            self.backend_hint.setText("Unknown backend: " + name)
            widgets.set_label_color(self.backend_hint, widgets.STATUS_FAIL)
            return

        if not module.available():
            self.backend_hint.setText(str(getattr(module, "INSTALL_HINT", "")) or (name + " could not be run."))
            widgets.set_label_color(self.backend_hint, widgets.STATUS_FAIL)
            self._set_models([])
            return

        def query_backend(_ctx: WorkContext) -> Tuple[str, List[str]]:
            # version() and list_models() run the agent's own command, which can take a moment; they must not block
            # the UI thread. A failure leaves the list empty and the field still typeable.
            return module.version() or "", module.list_models()

        def apply(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self._backend_query = None
            if self.backend_combo.currentText() != name:
                return  # another backend was selected in the meantime
            version, models = event.result if event.error is None else ("", [])
            self.backend_hint.setText(
                patch_repair_view.backend_description(version, str(getattr(module, "DESCRIPTION", "")))
            )
            widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE)
            self._set_models(models)

        self.backend_hint.setText("Querying " + name + "...")
        widgets.set_label_color(self.backend_hint, widgets.STATUS_IDLE)
        self._backend_query = start_work(self, query_backend, apply)

    def _set_models(self, models: List[str]) -> None:
        """Fill the model list; what is typed in the field stays."""
        typed = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setCurrentText(typed)

    def _update_budget(self) -> None:
        self.budget_label.setText(patch_repair_view.budget_text(self.prompts_spin.value(), self.retries_spin.value()))
        widgets.set_label_color(self.budget_label, widgets.STATUS_IDLE)

    def _update_config_display(self) -> None:
        config = self.project_state.current_config
        if config:
            self.config_label.setText(config)
            self.config_label.setStyleSheet("")
        else:
            self.config_label.setText("(none selected)")
            widgets.set_label_color(self.config_label, widgets.STATUS_IDLE)

    def _update_ui(self) -> None:
        """Enable the run button only once there are patches to repair."""
        self._update_config_display()
        if self.running:
            return
        self.run_button.setEnabled(self._prerequisites_met())
        self.selector.refresh()

    def _prerequisites_met(self) -> bool:
        """Patches must exist: without them there is nothing to build and nothing to fix."""
        return has_patches(self.arguments.dot_dp) and bool(self.project_state.current_config)

    def _set_summary(self, text: str, color: str) -> None:
        self.summary_label.setText(text)
        widgets.set_label_color(self.summary_label, color)

    # ── running ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "Patch repair is already running.")
            return
        if not self.project_state.current_config:
            dialogs.show_error(self, "No Configuration Selected", "Please select a configuration first.")
            return

        self.running = True
        self.run_button.setEnabled(False)
        self.run_button.setText(RUNNING_TEXT)
        self.stop_button.setEnabled(True)
        self.status.set("⏳ Patch repair in progress...", widgets.STATUS_BUSY)

        self.console.clear()
        self._records = {}
        self._refresh_table()

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
            self._set_summary(text, _TONE_COLORS[tone])

    def _stop(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.stop_button.setEnabled(False)
        self.status.set("Stopping patch repair...", widgets.STATUS_STOP)

    def _on_complete(self, error: bool = False, stopped: bool = False) -> None:
        self.running = False
        # results.json is the authoritative record: rebuild from it so the table is complete even if a live event
        # was missed
        self._load_results_from_file()
        self.run_button.setEnabled(True)
        self.run_button.setText(RUN_TEXT)
        self.stop_button.setEnabled(False)

        if error:
            self.status.set("Patch repair failed", widgets.STATUS_FAIL, reset_ms=4000)
            return
        if stopped:
            self.status.set("Patch repair stopped", widgets.STATUS_IDLE, reset_ms=4000)
            return

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
        if self._backend_query is not None:
            self._backend_query.cancel()

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
