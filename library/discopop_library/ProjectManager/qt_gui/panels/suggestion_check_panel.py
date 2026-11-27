# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Suggestion Check tab: an LLM agent checks the unsure suggestions of the pattern detection.

Runs ``discopop_suggestion_check`` (``SuggestionCheck``) as a subprocess, built like the Patch Repair tab; what the
tab shows is computed by ``services/suggestion_check_view.py``. An approval is the agent's judgement, not DiscoPoP's
analysis: it is used by the other stages only after "Use approved suggestions" (``SuggestionCheck/publish.py``), which
the user confirms after reading the assumption it rests on, and "Withdraw" takes it back.
"""

import queue
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.PatchRepair import llm_backends
from discopop_library.ProjectManager.plots.data import split_progress_events
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter, start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import suggestion_check_view as view
from discopop_library.ProjectManager.services.commands import suggestion_check_command
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
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import SuggestionCheckRequest
from discopop_library.ProjectManager.services.text import clean_ansi_output
from discopop_library.SuggestionCheck.results import PROGRESS_PREFIX

RUN_TEXT = "Run Suggestion Check"
_SETTINGS_WIDTH = 480
DESCRIPTION = (
    "An LLM agent checks loops DiscoPoP did not suggest because of a few dependencies. "
    "An approval rests on the agent's assumption, not on DiscoPoP's analysis."
)
NOT_RUN_TEXT = "Not run yet"
NO_RESULTS_TEXT = "No suggestion check run yet."
NO_UNSURE_TEXT = (
    "No unsure suggestions. Run the Pattern Detection with unsure suggestions "
    "(discopop_explorer --unsure-suggestions) first."
)
STALE_TEXT = "Results of an earlier explorer run"
STALE_DETAIL = (
    "The pattern detection ran again since this check, so an id may now name another loop. "
    "Run the check again before using its approvals."
)
# the exit code of a run the check aborted because the project itself changed (SuggestionCheck/run.py)
ABORTED_RETURNCODE = 2

_TONE_COLORS = {
    view.TONE_IDLE: widgets.STATUS_IDLE,
    view.TONE_BUSY: widgets.STATUS_BUSY,
    view.TONE_OK: widgets.STATUS_OK,
    view.TONE_FAIL: widgets.STATUS_FAIL,
    view.TONE_STOP: widgets.STATUS_STOP,
}
_CHIP_LEVELS = {
    view.TONE_IDLE: widgets.CHIP_IDLE,
    view.TONE_BUSY: widgets.CHIP_BUSY,
    view.TONE_OK: widgets.CHIP_OK,
    view.TONE_FAIL: widgets.CHIP_ERROR,
    view.TONE_STOP: widgets.CHIP_WARN,
}
_COST_COLUMN = view.COLUMNS.index("Cost")


class SuggestionCheckPanel(Panel):
    """The Suggestion Check tab.

    Subscribes to ``PatternsChanged`` (a new pattern detection brings other unsure suggestions and makes the results
    stale). Publishes ``ResultsChanged`` after a check run (the sidebar shows its state) and ``PatternsChanged``,
    ``AutotuningChanged`` and ``ResultsChanged`` after approvals were put into use or withdrawn: they are suggestions
    of the other stages then.
    """

    output_title = "Suggestion Check"

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
        self._stale = False
        self._unsure: Dict[str, view.UnsureEntry] = {}
        self._file_mapping: Dict[int, str] = {}
        self._published: List[str] = []
        self._connections_error = ""
        self._connection_names: List[str] = []
        # why the selected connection cannot be resolved ("" if it can)
        self._connection_problem = ""
        # the number of suggestions the running check announced
        self._total = 0

        self.console = self.make_console()
        self.run_button = widgets.RunStopButton(RUN_TEXT, self._run, self._stop)
        self.run_button.setEnabled(False)
        self.header = widgets.PanelHeader("Suggestion Check", DESCRIPTION, [self.run_button])
        self.header.chip.set_status(widgets.CHIP_IDLE, NOT_RUN_TEXT)
        self._build_agent_settings()
        self._build_check_settings()
        self._build_scope()
        self._build_advanced()

        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(self._agent_box)
        column_layout.addWidget(self._check_box)
        column_layout.addWidget(self._scope_box)
        column_layout.addWidget(self._advanced)
        self.splitter = widgets.SettingsSplitter(column, self._build_results(), _SETTINGS_WIDTH)
        self.header.add_action(self.splitter.toggle_button, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(self.splitter, 1)

        project_state.subscribe(PatternsChanged, lambda _event: self._on_patterns_changed())
        self._on_backend_changed()
        self.reload_connections()
        self._update_budget()
        self._reload_unsure()
        self._update_ui()
        self._load_results_from_file()
        self._show_loaded_summary()
        # no results.json yet means nothing rendered the detail panes, which would leave them blank rather than
        # saying why
        self._on_row_selected()

    # ── construction ────────────────────────────────────────────────────────

    def _build_agent_settings(self) -> None:
        # built from the registry, so a newly added agent reaches the GUI without a change here
        backends = llm_backends.available_backends()
        installed = llm_backends.first_installed_backend()
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(backends)
        self.backend_combo.setCurrentText(installed or (backends[0] if backends else ""))
        self.backend_combo.currentTextChanged.connect(lambda _text: self._on_backend_changed())
        # Editable: a backend's model list is not always exhaustive, so a model missing from it must be typeable.
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText("")
        # The stored connections of the LLM configuration shared with patch repair; the first entry is choosing the
        # backend and the model here. A selected connection shows what it resolves to, read-only.
        self.connection_combo = QComboBox()
        self.connection_combo.currentTextChanged.connect(lambda _text: self._on_connection_changed())
        # what was chosen by hand, restored when the connection is set back to choosing by hand
        self._manual_choice: Optional[Tuple[str, str]] = None

        section = widgets.FormSection("LLM Agent")
        connection_hint = section.add_row("Connection:", self.connection_combo, " ")
        assert connection_hint is not None
        self.connection_hint = connection_hint
        self.connection_hint.setWordWrap(True)
        backend_hint = section.add_row("Backend:", self.backend_combo, " ")
        assert backend_hint is not None
        self.backend_hint = backend_hint
        section.add_row(
            "Model:",
            self.model_combo,
            "Empty: the default model. Any model the backend accepts can be typed.",
            stretch_field=True,
        )
        self._agent_box = section

    def _build_check_settings(self) -> None:
        self.review_check = QCheckBox("Have every approval reviewed by a second agent call")
        self.review_check.setChecked(True)
        self.rounding_check = QCheckBox("Accept rounding differences")
        self.rounding_check.setChecked(True)
        self.tools_check = QCheckBox("Give the agent DiscoPoP's data (MCP)")
        self.tools_check.setChecked(True)
        self.review_check.toggled.connect(lambda _checked: self._update_budget())

        section = widgets.FormSection("Check")
        section.add_widget(
            self.review_check,
            "A fresh conversation reads the changes in a read-only copy; if it disagrees, the suggestion is rejected.",
        )
        section.add_widget(
            self.rounding_check,
            "Approve loops whose results may differ from the sequential program by rounding (floating-point "
            "operations in another order). Such approvals are marked. Off: they are rejected.",
        )
        section.add_widget(
            self.tools_check,
            "The side effects of functions and why DiscoPoP did not parallelize the lines, through "
            "discopop_mcp_server (read-only), if it is installed.",
        )
        self._check_box = section

    def _build_scope(self) -> None:
        self.scope_edit = QLineEdit()
        self.scope_edit.setPlaceholderText("all, or e.g. 12,15-18")
        self.scope_edit.textChanged.connect(lambda _text: self._update_scope_caption())
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 10000)
        self.max_spin.setSpecialValueText("no limit")
        self.max_spin.setValue(0)

        section = widgets.FormSection("Suggestion Scope")
        scope_hint = section.add_row("Unsure suggestions:", self.scope_edit, " ", stretch_field=True)
        assert scope_hint is not None
        self.scope_caption = scope_hint
        self.scope_caption.setWordWrap(True)
        section.add_row("Max. suggestions:", self.max_spin, "Check at most this many of the selected ones.")
        self._scope_box = section

    def _build_advanced(self) -> None:
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 7200)
        self.timeout_spin.setSingleStep(30)
        self.timeout_spin.setValue(600)
        self.prompts_spin = QSpinBox()
        self.prompts_spin.setRange(1, 10)
        self.prompts_spin.setValue(2)
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.setValue(2)
        self.prompts_spin.valueChanged.connect(lambda _value: self._update_budget())
        self.retries_spin.valueChanged.connect(lambda _value: self._update_budget())
        self.log_level_combo = widgets.log_level_selector("WARNING")

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
                "A prompt is an independent attempt with a fresh conversation and a fresh copy of the project; a "
                "retry is a follow-up turn in the same conversation, told what was wrong."
            )
        )
        section.add_row("Log level:", self.log_level_combo)
        self._advanced = widgets.CollapsibleSection(
            "Advanced", section, summary="agent timeout, prompts, retries, log level"
        )

    def _build_results(self) -> QTabWidget:
        notebook = QTabWidget()

        self.table = QTableWidget(0, len(view.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(view.COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # several approvals can be put into use (or withdrawn) at once
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column, width in enumerate((80, 130, 110, 120, 75, 75, 120)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_row_selected)

        self.assumption_label = QLabel("")
        self.assumption_label.setWordWrap(True)
        self.assumption_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.publish_button = widgets.primary_button("Use approved suggestions", self._publish)
        self.withdraw_button = widgets.create_button("Withdraw", self._withdraw)
        self.publish_button.setToolTip(
            "Copy the approved patches to patch_generator/, where the patch applicator, the autotuner and the other "
            "stages find them, marked as agent-approved. " + view.AGENT_NOTE
        )
        self.withdraw_button.setToolTip("Remove approvals that are in use from patch_generator/ again.")
        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self.table, 1)
        results_layout.addWidget(widgets.caption_label(view.AGENT_NOTE + " Nothing is used until you say so."))
        results_layout.addWidget(self.assumption_label)
        results_layout.addLayout(widgets.hbox(self.publish_button, self.withdraw_button, None))

        # an empty table says what to do instead of showing bare column headers
        self.empty_label = widgets.empty_state_label(NO_RESULTS_TEXT)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_label)
        self.results_stack.addWidget(results_page)
        self._results_page = results_page
        notebook.addTab(self.results_stack, "Results")

        # which suggestion is shown is the one selected in the Results tab
        self.details_view = widgets.CodeView(wrap=True)
        notebook.addTab(self.details_view, "Details")

        self.patch_combo = QComboBox()
        self.patch_combo.setMinimumContentsLength(20)
        self.patch_combo.activated.connect(lambda _index: self._show_patch())
        self.patch_view = widgets.CodeView()
        patch_tab = QWidget()
        patch_layout = QVBoxLayout(patch_tab)
        patch_layout.addLayout(widgets.hbox(QLabel("File:"), self.patch_combo, None))
        patch_layout.addWidget(self.patch_view, 1)
        notebook.addTab(patch_tab, "Patch")

        self.transcript_combo = QComboBox()
        self.transcript_combo.setMinimumContentsLength(24)
        self.transcript_combo.activated.connect(lambda _index: self._show_transcript())
        self.transcript_view = widgets.CodeView(wrap=True)
        transcript_tab = QWidget()
        transcript_layout = QVBoxLayout(transcript_tab)
        transcript_layout.addLayout(widgets.hbox(QLabel("File:"), self.transcript_combo, None))
        transcript_layout.addWidget(
            widgets.caption_label(
                "Per agent call: the prompt, the answer and the tool calls (*_tools.txt: what it read, searched for "
                "and changed)."
            )
        )
        transcript_layout.addWidget(self.transcript_view, 1)
        notebook.addTab(transcript_tab, "Transcript")
        self.notebook = notebook
        return notebook

    def output_console(self) -> widgets.OutputConsole:
        return self.console

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
            # version() and list_models() run the agent's own command; they must not block the UI thread
            return module.version() or "", module.list_models()

        def apply(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            self._backend_query = None
            if self.backend_combo.currentText() != name:
                return  # another backend was selected in the meantime
            version, models = event.result if event.error is None else ("", [])
            self.backend_hint.setText(view.backend_description(version, str(getattr(module, "DESCRIPTION", ""))))
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

    def reload_connections(self) -> None:
        """Re-read the stored connections (call after the LLM configuration changed); the selection stays if the
        connection still exists."""
        selected = self.connection_combo.currentText()
        names, error = view.load_connections(self.arguments.dot_dp)
        choices = view.connection_choices(names)
        self.connection_combo.blockSignals(True)
        try:
            self.connection_combo.clear()
            self.connection_combo.addItems(choices)
            self.connection_combo.setCurrentText(selected if selected in choices else view.NO_CONNECTION)
        finally:
            self.connection_combo.blockSignals(False)
        self._connections_error = error
        self._connection_names = names
        self._on_connection_changed()

    def _selected_connection(self) -> str:
        """The stored connection the run uses; "" when the backend and the model are chosen in the panel."""
        name = self.connection_combo.currentText()
        return "" if name in ("", view.NO_CONNECTION) else name

    def _on_connection_changed(self) -> None:
        name = self._selected_connection()
        if not name:
            if self._manual_choice is not None:
                backend, model = self._manual_choice
                self._manual_choice = None
                self.backend_combo.setCurrentText(backend)
                self.model_combo.setCurrentText(model)
            self.backend_combo.setEnabled(True)
            self.model_combo.setEnabled(True)
            self._connection_problem = self._connections_error or view.manual_choice_problem(self._connection_names)
            if self._connection_problem:
                self.connection_hint.setText(self._connection_problem)
                widgets.set_label_color(self.connection_hint, widgets.STATUS_FAIL)
            else:
                self.connection_hint.setText(view.manual_choice_note(self._connection_names))
                widgets.set_label_color(self.connection_hint, widgets.STATUS_IDLE)
            return
        if self._manual_choice is None:
            self._manual_choice = (self.backend_combo.currentText(), self.model_combo.currentText())
        info = view.resolve_connection(self.arguments.dot_dp, name)
        self._connection_problem = info.error
        if info.error:
            self.connection_hint.setText(info.error)
            widgets.set_label_color(self.connection_hint, widgets.STATUS_FAIL)
        else:
            if info.backend and self.backend_combo.findText(info.backend) < 0:
                self.backend_combo.addItem(info.backend)
            self.backend_combo.setCurrentText(info.backend)
            self.model_combo.setCurrentText(info.model)
            self.connection_hint.setText(info.description)
            widgets.set_label_color(self.connection_hint, widgets.STATUS_IDLE)
        # the connection decides: the fields only show what it resolves to
        self.backend_combo.setEnabled(False)
        self.model_combo.setEnabled(False)

    def _update_budget(self) -> None:
        self.budget_label.setText(
            view.budget_text(self.prompts_spin.value(), self.retries_spin.value(), self.review_check.isChecked())
        )
        widgets.set_label_color(self.budget_label, widgets.STATUS_IDLE)

    def _on_patterns_changed(self) -> None:
        """A pattern detection ran: other unsure suggestions, and the results may belong to the earlier run."""
        self._reload_unsure()
        self._update_ui()
        if not self.running:
            self._load_results_from_file()
            self._show_loaded_summary()

    def _reload_unsure(self) -> None:
        self._unsure = view.load_unsure(self.arguments.dot_dp)
        self._file_mapping = view.read_file_mapping(self.arguments.dot_dp)
        self._update_scope_caption()

    def _available_ids(self) -> List[str]:
        return sorted(self._unsure, key=view.sort_key)

    def _update_scope_caption(self) -> None:
        available = self._available_ids()
        self.scope_caption.setText(view.scope_text(view.parse_scope(self.scope_edit.text(), available), available))
        widgets.set_label_color(self.scope_caption, widgets.STATUS_IDLE)

    def _update_ui(self) -> None:
        """Enable the run button only once there are unsure suggestions to check."""
        if self.running:
            return
        self.run_button.setEnabled(view.has_unsure_suggestions(self.arguments.dot_dp))
        self._update_publish_buttons()

    def _set_summary(self, text: str, tone: str) -> None:
        """Show the outcome in the header chip: the first sentence as the chip, the rest behind "Details"."""
        first, _separator, rest = text.partition(". ")
        if rest:
            self.header.chip.set_status(_CHIP_LEVELS[tone], first, rest)
        else:
            self.header.chip.set_status(_CHIP_LEVELS[tone], text)

    def _show_loaded_summary(self) -> None:
        """The chip for the results on disk: stale, or what they hold."""
        if not view.has_unsure_suggestions(self.arguments.dot_dp) and not self._records:
            self.header.chip.set_status(widgets.CHIP_IDLE, "No unsure suggestions", NO_UNSURE_TEXT)
            return
        if not self._records:
            self.header.chip.set_status(widgets.CHIP_IDLE, NOT_RUN_TEXT)
            return
        if self._stale:
            self.header.chip.set_status(widgets.CHIP_WARN, STALE_TEXT, STALE_DETAIL)
            return
        approved = len(view.approved_ids(self._records))
        self.header.chip.set_status(
            widgets.CHIP_OK if approved else widgets.CHIP_IDLE,
            str(len(self._records)) + " checked, " + str(approved) + " approved",
            view.AGENT_NOTE,
        )

    # ── running ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "The suggestion check is already running.")
            return
        self._reload_unsure()
        if not self._unsure:
            dialogs.show_error(self, "No Unsure Suggestions", NO_UNSURE_TEXT)
            return
        if self._connection_problem:
            # the check would fail on it before checking anything
            dialogs.show_error(self, "LLM Connection", self._connection_problem)
            return
        request = self._snapshot_request()
        if request.suggestion_ids is not None and not request.suggestion_ids:
            dialogs.show_error(
                self,
                "No Suggestion Selected",
                "None of the ids in the scope is an unsure suggestion. Available: " + ", ".join(self._available_ids()),
            )
            return

        self.running = True
        self.run_button.set_running(True)
        self.set_busy(True)
        self._update_publish_buttons()
        self.output_requested.emit()
        self.status.set("⏳ Suggestion check in progress...", widgets.STATUS_BUSY)

        self.console.clear()
        self._records = {}
        self._stale = False
        self._total = 0
        self._refresh_table()
        self.header.chip.set_status(widgets.CHIP_BUSY, "Starting…")

        dot_discopop = self.arguments.dot_dp
        self.console.append_text("Starting the suggestion check...\n")
        self._announce_request(request)

        events: "queue.Queue[JobEvent]" = queue.Queue()
        # A subprocess, never in-process: the check drives an external agent. SIGINT rather than terminate(): the
        # check stops between calls and leaves results.json consistent; sent to the process group, so the agent stops
        # too.
        job = JobRunner(
            JobSpec(
                suggestion_check_command(request, dot_discopop),
                cwd=dot_discopop,
                cancel_policy=CancelPolicy.SIGINT_GROUP,
                new_session=True,
            ),
            events,
        )
        self._job = job
        QtJobAdapter(self, events, self._on_job_event).start()
        job.start()

    def _snapshot_request(self) -> SuggestionCheckRequest:
        """Read the panel into an immutable request; call on the main thread only."""
        return SuggestionCheckRequest(
            connection=self._selected_connection(),
            prompts=self.prompts_spin.value(),
            retries=self.retries_spin.value(),
            agent_timeout=self.timeout_spin.value(),
            log_level=self.log_level_combo.currentText(),
            backend=self.backend_combo.currentText(),
            model=self.model_combo.currentText().strip(),
            review=self.review_check.isChecked(),
            accept_rounding=self.rounding_check.isChecked(),
            discopop_tools=self.tools_check.isChecked(),
            max_suggestions=self.max_spin.value(),
            suggestion_ids=view.parse_scope(self.scope_edit.text(), self._available_ids()),
        )

    def _announce_request(self, request: SuggestionCheckRequest) -> None:
        if request.suggestion_ids is not None:
            self.console.append_text("Restricting to unsure suggestions: " + ", ".join(request.suggestion_ids) + "\n")
        self.console.append_text("Configuration:\n")
        if request.connection:
            self.console.append_text("  Connection: " + request.connection + "\n")
        else:
            self.console.append_text("  Backend: " + request.backend + "\n")
            self.console.append_text("  Model: " + (request.model or "(default)") + "\n")
        self.console.append_text("  Review: " + ("on" if request.review else "off") + "\n")
        self.console.append_text("  Rounding differences: " + ("accepted" if request.accept_rounding else "rejected"))
        self.console.append_text("\n  DiscoPoP's data (MCP): " + ("on" if request.discopop_tools else "off") + "\n\n")

    def _on_job_event(self, event: JobEvent) -> None:
        """Handle one event of the check's job; runs on the main thread."""
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
                self.console.append_text("\nSuggestion check stopped.\n")
                self._on_complete(stopped=True)
            elif event.returncode == ABORTED_RETURNCODE:
                self.console.append_text("\nSuggestion check aborted: the project changed while it ran.\n")
                self._on_complete(aborted=True)
            elif event.returncode != 0:
                self.console.append_text(
                    "\nError: The suggestion check exited with return code " + str(event.returncode) + "\n"
                )
                self._on_complete(error=True)
            else:
                self.console.append_text("\nSuggestion check completed.\n")
                self._on_complete()
        elif isinstance(event, JobFailedToStart):
            self._job = None
            self.console.append_text("\nError: " + event.error + "\n")
            self._on_complete(error=True, started=False)

    def _on_progress(self, event: Dict[str, Any]) -> None:
        """Update the table and the summary from one structured progress event."""
        kind = str(event.get("event") or "")
        if kind == "start":
            self._total = len(event.get("suggestions") or [])
        elif kind == "done":
            # results.json is written before the event: it holds the whole record
            self._load_results_from_file()
        for text, tone in view.progress_summary(event, self._total):
            self._set_summary(text, tone)

    def _stop(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping the suggestion check...", widgets.STATUS_STOP)

    def _on_complete(
        self, error: bool = False, stopped: bool = False, aborted: bool = False, started: bool = True
    ) -> None:
        self.running = False
        # results.json is the authoritative record: rebuild from it so the table is complete even if a live event
        # was missed
        self._load_results_from_file()
        self.run_button.set_running(False, enabled_after=view.has_unsure_suggestions(self.arguments.dot_dp))
        self.set_busy(False)
        self._update_publish_buttons()
        if started:
            # the sidebar shows the state of the check
            self.project_state.publish(ResultsChanged())

        if aborted:
            if self.header.chip.level != widgets.CHIP_ERROR:
                self.header.chip.set_status(
                    widgets.CHIP_ERROR, "Aborted", "The project changed while the check ran; see the output pane."
                )
            self.status.set("Suggestion check aborted", widgets.STATUS_FAIL, reset_ms=4000)
            return
        if error:
            self.header.chip.set_status(widgets.CHIP_ERROR, "Failed", "See the output pane for the error.")
            self.status.set("Suggestion check failed", widgets.STATUS_FAIL, reset_ms=4000)
            return
        if stopped:
            self.header.chip.set_status(widgets.CHIP_WARN, "Stopped")
            self.status.set("Suggestion check stopped", widgets.STATUS_IDLE, reset_ms=4000)
            return
        if self.header.chip.level == widgets.CHIP_BUSY:  # no "end" event arrived
            self.header.chip.set_status(widgets.CHIP_OK, "Completed")

        approved = len(view.approved_ids(self._records))
        if approved:
            self.status.set(
                "Suggestion check completed - " + str(approved) + " approved (not in use yet)",
                widgets.STATUS_OK,
                reset_ms=6000,
            )
        else:
            self.status.set("Suggestion check completed", widgets.STATUS_IDLE, reset_ms=6000)

    def cancel_jobs(self) -> None:
        if self._job is not None:
            self._job.cancel()
        if self._backend_query is not None:
            self._backend_query.cancel()

    # ── publishing ──────────────────────────────────────────────────────────

    def _update_publish_buttons(self) -> None:
        selected = self._selected_ids()
        publish = view.publish_plan(self._records, selected)
        withdraw = view.withdraw_plan(self._published, selected)
        self.publish_button.setText(publish.label)
        self.withdraw_button.setText(withdraw.label)
        # a running check rewrites results.json and the approved patches
        self.publish_button.setEnabled(not self.running and bool(publish.ids) and not self._stale)
        self.withdraw_button.setEnabled(not self.running and bool(withdraw.ids))
        self.assumption_label.setText(view.assumption_text(self._records, publish.ids))

    def _publish(self) -> None:
        plan = view.publish_plan(self._records, self._selected_ids())
        if self.running or not plan.ids:
            return
        if not dialogs.ask_yes_no(
            self, "Use Agent-Approved Suggestions", view.confirm_publish_text(self._records, plan.ids)
        ):
            return
        result = view.publish(self.arguments.dot_dp, plan.ids)
        message = view.publish_message(result)
        self.console.append_text(message + "\n")
        if result.skipped:
            dialogs.show_warning(self, "Suggestions Not Used" if not result.published else "Some Not Used", message)
        else:
            dialogs.show_message(self, "Suggestions In Use", message + "\n\n" + view.AGENT_NOTE)
        self._after_publishing(bool(result.published))
        if result.published:
            self.status.set(
                str(len(result.published)) + " agent-approved suggestion(s) in use", widgets.STATUS_OK, reset_ms=6000
            )

    def _withdraw(self) -> None:
        plan = view.withdraw_plan(self._published, self._selected_ids())
        if self.running or not plan.ids:
            return
        withdrawn = view.withdraw(self.arguments.dot_dp, plan.ids)
        self.console.append_text("Withdrawn: " + (", ".join(withdrawn) or "nothing") + "\n")
        self._after_publishing(bool(withdrawn))
        if withdrawn:
            self.status.set("Withdrawn: " + ", ".join(withdrawn), widgets.STATUS_IDLE, reset_ms=6000)

    def _after_publishing(self, changed: bool) -> None:
        self._refresh_table()
        if changed:
            # patch_generator/ changed: the suggestion lists, the tuner and the report read it
            self.project_state.publish(PatternsChanged())
            self.project_state.publish(AutotuningChanged())
            self.project_state.publish(ResultsChanged())

    # ── results display ─────────────────────────────────────────────────────

    def _load_results_from_file(self) -> None:
        dot_dp = self.arguments.dot_dp
        document = view.load_document(dot_dp)
        records = view.records_of(document)
        if records is not None:
            self._records = records
            self._stale = view.results_are_stale(dot_dp, document)
        self._refresh_table()

    def _selected_ids(self) -> List[str]:
        ids = []
        for index in self.table.selectionModel().selectedRows(0):
            item = self.table.item(index.row(), 0)
            if item is not None:
                ids.append(item.text())
        return sorted(ids, key=view.sort_key)

    def _selected_id(self) -> Optional[str]:
        """The suggestion the detail tabs show: the current row if it is selected, else the first selected one."""
        current = self.table.currentRow()
        selected = self._selected_ids()
        if current >= 0:
            item = self.table.item(current, 0)
            if item is not None and item.text() in selected:
                return item.text()
        return selected[0] if selected else None

    def _refresh_table(self) -> None:
        previous = self._selected_ids()
        self._published = view.published_suggestions(self.arguments.dot_dp)
        rows = view.result_rows(self._records, self._file_mapping, self._published)
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            self.table.setRowCount(len(rows))
            self.results_stack.setCurrentWidget(self._results_page if rows else self.empty_label)
            self.empty_label.setText(
                NO_RESULTS_TEXT if view.has_unsure_suggestions(self.arguments.dot_dp) else NO_UNSURE_TEXT
            )
            for index, row in enumerate(rows):
                color = QColor(_TONE_COLORS[row.tone])
                for column, value in enumerate(row.cells()):
                    item = QTableWidgetItem(value)
                    item.setForeground(color)
                    self.table.setItem(index, column, item)
            # the cost column only when the check recorded one
            self.table.setColumnHidden(_COST_COLUMN, not view.has_cost(rows))
            ids = [row.suggestion_id for row in rows]
            # the detail tabs render the selected suggestion, and rebuilding the table on every progress event would
            # otherwise drop the user's selection
            chosen = [i for i in previous if i in ids]
            preferred = view.preferred_row(rows, None)
            if not chosen and preferred is not None:
                chosen = [preferred]
            flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            for suggestion_id in chosen:
                self.table.selectionModel().select(self.table.model().index(ids.index(suggestion_id), 0), flags)
            if chosen:
                first = ids.index(chosen[0])
                self.table.setCurrentCell(first, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
                first_item = self.table.item(first, 0)
                if first_item is not None:
                    self.table.scrollToItem(first_item)
        finally:
            self.table.blockSignals(False)
        self._on_row_selected()

    def _on_row_selected(self) -> None:
        suggestion_id = self._selected_id()
        record = self._records.get(suggestion_id) if suggestion_id is not None else None
        unsure = self._unsure.get(suggestion_id) if suggestion_id is not None else None
        marker = view.marker(self.arguments.dot_dp, suggestion_id) if suggestion_id is not None else None
        if suggestion_id is None and not self._records:
            self.details_view.set_code(NO_RESULTS_TEXT)
        else:
            self.details_view.set_code(view.detail_text(suggestion_id, record, unsure, self._file_mapping, marker))

        self.patch_combo.clear()
        self.transcript_combo.clear()
        if suggestion_id is not None:
            self.patch_combo.addItems(
                ["file " + f for f in view.approved_patch_files(self.arguments.dot_dp, suggestion_id)]
            )
            self.transcript_combo.addItems(view.transcript_files(self.arguments.dot_dp, suggestion_id))
        self._show_patch()
        self._show_transcript()
        self._update_publish_buttons()

    def _show_patch(self) -> None:
        suggestion_id = self._selected_id()
        record = self._records.get(suggestion_id) if suggestion_id is not None else None
        file_id = self.patch_combo.currentText().replace("file ", "", 1).strip()
        if suggestion_id is None and not self._records:
            self.patch_view.set_diff("(no results yet: run the suggestion check)")
            return
        self.patch_view.set_diff(view.patch_text(self.arguments.dot_dp, suggestion_id, file_id, record))

    def _show_transcript(self) -> None:
        suggestion_id = self._selected_id()
        if suggestion_id is None and not self._records:
            self.transcript_view.set_code("(no results yet: run the suggestion check)")
            return
        self.transcript_view.set_code(
            view.transcript_text(self.arguments.dot_dp, suggestion_id, self.transcript_combo.currentText())
        )
