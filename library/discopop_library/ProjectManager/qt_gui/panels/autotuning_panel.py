# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Autotuning tab: the options of the autotuner, the live progress of its search and its console.

Ported from ``gui/mixins/autotuning_panel.py``.
"""

import os
import queue
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_TUNING_REPETITIONS,
    validate_repetitions,
)
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import autotuning_chart, mode_style
from discopop_library.ProjectManager.plots.autotuning_chart import ProgressModel
from discopop_library.ProjectManager.plots.data import parse_progress_jsonl, split_progress_events
from discopop_library.ProjectManager.plots.hotspot_data import hotspots_available_for_explorer
from discopop_library.ProjectManager.qt_gui import chart_embedding, dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.suggestion_browser import open_suggestion_browser
from discopop_library.ProjectManager.qt_gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.services.autotuner_results import (
    autotuner_results_exist,
    read_autotuner_applied_suggestions,
)
from discopop_library.ProjectManager.services.commands import autotuner_command
from discopop_library.ProjectManager.services.explorer_state import explorer_prerequisites_met
from discopop_library.ProjectManager.services.jobs import (
    CancelPolicy,
    JobEvent,
    JobFailedToStart,
    JobFinished,
    JobOutput,
    JobRunner,
    JobSpec,
)
from discopop_library.ProjectManager.services.patches import has_patches, sort_suggestion_ids
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import AutotunerRequest
from discopop_library.ProjectManager.services.text import clean_ansi_output

# the name of the tab in the main window (``main_window.TAB_AUTOTUNING``; not imported, the window imports this module)
TAB_AUTOTUNING = "Autotuning"
TAB_DISABLED_TOOLTIP = "Prerequisites not met:\nPattern Detection needs to be executed first."

SEARCH_MODE = "search"
EVALUATE_MODE = "evaluate"

# the algorithm choices: the description shown and the value of the autotuner's algorithm option
ALGORITHM_OPTIONS: List[Tuple[str, str]] = [
    ("0", "No combination (measure only)"),
    ("1", "Linear combination"),
    ("3", "Evolutionary combination"),
    ("4", "Greedy combination"),
    ("5", "Coordinate descent combination"),
    ("6", "Hotspot-guided region descent"),
]
# the deterministic search: repeating a tuning run reproduces its decisions, which the randomized evolutionary
# search cannot promise
DEFAULT_ALGORITHM = "Hotspot-guided region descent"
HOTSPOT_TYPES = ("yes", "no", "maybe")

_MAX_REPETITIONS = 1000
_OPTIONS_MIN_WIDTH = 650


def _set_state_text(label: QLabel, text: str, active: bool) -> None:
    """Show ``text`` in the normal text color when ``active``, else grayed out."""
    label.setText(text)
    label.setStyleSheet("" if active else f"color: {widgets.STATUS_IDLE};")


class AutotuningPanel(Panel):
    """The Autotuning tab.

    ``tabs`` is the main window: the panel enables and disables its own tab (``TAB_AUTOTUNING``) there, depending
    on whether parallelization suggestions and profiling data exist (``update_tab_state``; the window calls it once
    after it put the panel into its tab, the panel itself whenever the prerequisites may have changed).
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        tabs: TabHost,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self._tabs = tabs
        self.running = False
        self._job: Optional[JobRunner] = None
        self._reported_not_applied = 0
        self.progress_model = ProgressModel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_side())
        splitter.addWidget(self._build_right_side())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([_OPTIONS_MIN_WIDTH, 900])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._update_mode_widgets()
        self._update_algorithm_hint()
        self._update_config_display()
        self._update_ui()
        # show the last run (if any) so the plot is not empty on open
        self._load_progress_from_file()

        project_state.subscribe(ConfigChanged, lambda _event: self._update_config_display())
        project_state.subscribe(ConfigChanged, lambda _event: self._refresh_suggestions_display())
        project_state.subscribe(PatternsChanged, lambda _event: self._update_ui())
        project_state.subscribe(HotspotsChanged, lambda _event: self._update_ui())
        project_state.subscribe(HotspotsChanged, lambda _event: self._update_algorithm_hint())
        project_state.subscribe(AutotuningChanged, lambda _event: self._refresh_suggestions_display())
        project_state.subscribe(AutotuningFinished, lambda _event: self._refresh_suggestions_display())

    # ── building ─────────────────────────────────────────────────────────────

    def _build_left_side(self) -> QWidget:
        # the options scroll; the Run / Stop buttons and the overview of the selected suggestions stay below
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.addWidget(self._build_settings())
        options_layout.addWidget(self._build_selection())
        options_layout.addStretch(1)
        scroll.setWidget(options)

        self.run_button = widgets.primary_button("Run Autotuning", self.run)
        self.stop_button = widgets.danger_button("Stop", self.stop)
        self.stop_button.setEnabled(False)
        self.suggestions_label = widgets.caption_label("(none)")
        self.suggestions_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        side = QWidget()
        side.setMinimumWidth(_OPTIONS_MIN_WIDTH)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll, 1)
        layout.addLayout(widgets.hbox(self.run_button, self.stop_button, None, margins=5))
        layout.addWidget(widgets.group_box("Selected Suggestion IDs", widgets.vbox(self.suggestions_label)))
        return side

    def _build_settings(self) -> QWidget:
        self.config_label = widgets.caption_label("(none selected)")

        self.threads = widgets.ThreadSelector()
        # Kept apart from the count used for the measured runs (Execute tab): the search performs one program
        # execution per candidate, so repeating every one of them multiplies the tuning time.
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, _MAX_REPETITIONS)
        self.repetitions.setValue(DEFAULT_TUNING_REPETITIONS)

        self.hotspot_type_checks: Dict[str, QCheckBox] = {}
        for hotspot_type in HOTSPOT_TYPES:
            check = QCheckBox(hotspot_type.upper())
            check.setChecked(hotspot_type == "yes")
            self.hotspot_type_checks[hotspot_type] = check

        self.algorithm_map = {description: value for value, description in ALGORITHM_OPTIONS}
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItems([description for _value, description in ALGORITHM_OPTIONS])
        self.algorithm_combo.setCurrentText(DEFAULT_ALGORITHM)
        self.algorithm_combo.currentTextChanged.connect(lambda _text: self._update_algorithm_hint())
        # the default algorithm stops immediately when no hotspot detection results exist, so say that here rather
        # than letting the run fail for a reason that is only visible in the console output
        self.algorithm_hint = widgets.caption_label("")

        self.log_level = widgets.log_level_selector("WARNING")

        layout = QVBoxLayout()
        layout.addLayout(widgets.hbox(widgets.heading_label("Configuration:"), self.config_label, None))
        layout.addLayout(
            widgets.hbox(
                QLabel("Threads:"),
                self.threads,
                widgets.caption_label("(auto = CPU count / 2; custom counts can be typed)"),
                None,
            )
        )
        layout.addLayout(
            widgets.hbox(
                QLabel("Repetitions:"),
                self.repetitions,
                widgets.caption_label(
                    "(runs per candidate; the median decides its rank. Above 1 multiplies the tuning time)"
                ),
                None,
            )
        )
        layout.addWidget(widgets.heading_label("Hotspot Types:"))
        layout.addLayout(widgets.hbox(*self.hotspot_type_checks.values(), None, margins=0, spacing=30))
        layout.addWidget(widgets.heading_label("Algorithm:"))
        layout.addWidget(self.algorithm_combo)
        layout.addWidget(self.algorithm_hint)
        layout.addLayout(widgets.hbox(QLabel("Log Level:"), self.log_level, None))
        return widgets.group_box("Settings", layout)

    def _build_selection(self) -> QWidget:
        # pick between searching for the best combination (algorithm + restricted search space) and evaluating one
        # fixed combination
        self.search_mode_radio = QRadioButton("Search for best combination")
        self.evaluate_mode_radio = QRadioButton("Evaluate a specific combination")
        self.search_mode_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.search_mode_radio)
        self.mode_group.addButton(self.evaluate_mode_radio)
        self.search_mode_radio.toggled.connect(lambda _checked: self._update_mode_widgets())

        # an overview of the active selector and a shortcut to the patch viewer, as on the Execute tab
        self.suggestions_count_label = QLabel("No suggestions available")
        self.browse_button = widgets.create_button("Browse / Edit →", self._open_suggestion_browser)
        self.browse_button.setEnabled(False)

        self.search_space_selector = SuggestionSelector(
            self.arguments.dot_dp, "autotuner_search_space", on_change=self._update_suggestion_count
        )
        self.search_space_container = QWidget()
        search_layout = QVBoxLayout(self.search_space_container)
        search_layout.setContentsMargins(20, 3, 0, 0)
        search_layout.addWidget(widgets.caption_label("Suggestions the algorithm may explore:"))
        search_layout.addWidget(self.search_space_selector)

        self.evaluate_selector = SuggestionSelector(
            self.arguments.dot_dp, "autotuner_evaluate", on_change=self._update_suggestion_count
        )
        self.evaluate_container = QWidget()
        evaluate_layout = QVBoxLayout(self.evaluate_container)
        evaluate_layout.setContentsMargins(20, 3, 0, 0)
        evaluate_layout.addWidget(widgets.caption_label("Suggestions to apply together and compare to the baseline:"))
        evaluate_layout.addWidget(self.evaluate_selector)

        layout = QVBoxLayout()
        layout.addWidget(self.search_mode_radio)
        layout.addWidget(self.evaluate_mode_radio)
        layout.addLayout(widgets.hbox(20, self.suggestions_count_label, self.browse_button, None))
        layout.addWidget(self.search_space_container)
        layout.addWidget(self.evaluate_container)
        return widgets.group_box("Suggestion Selection", layout)

    def _build_right_side(self) -> QWidget:
        # a live search plot (default) and the raw console: the plot refreshes from the autotuner's @@AT_PROGRESS
        # stream, the console keeps the human-readable log
        self.tile_values: List[QLabel] = []
        tiles = widgets.hbox(margins=2)
        # placeholder tiles; the values come from an empty model, so they read "—"
        for key, value in ProgressModel().summary_tiles():
            value_label = widgets.heading_label(value)
            self.tile_values.append(value_label)
            tiles.addLayout(widgets.vbox(widgets.caption_label(key), value_label, spacing=0), 1)

        # a configuration whose patches did not apply was never run, so it is not a parallel measurement: called out
        # here as well as in the plot, because it invalidates the conclusion one would otherwise draw from the run
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        widgets.set_label_color(self.warning_label, mode_style.status_color(mode_style.NOT_APPLIED_STATUS))
        self.warning_label.hide()

        canvas_widget, self.figure, self.canvas, _toolbar = chart_embedding.create_canvas()
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        plot_layout.addLayout(tiles)
        plot_layout.addWidget(self.warning_label)
        plot_layout.addWidget(canvas_widget, 1)

        self.console = widgets.OutputConsole()

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(plot_tab, "📈 Live Plot")
        self.right_tabs.addTab(self.console, "🖥 Console")
        return self.right_tabs

    # ── the options ──────────────────────────────────────────────────────────

    def _update_algorithm_hint(self) -> None:
        """Warn when the selected algorithm needs hotspot data the project lacks.

        Only the hotspot-guided descent hard-requires ``Hotspots.json``; it aborts without measuring anything when
        none exists. Since it is the default, a project that never ran hotspot detection would otherwise look as
        though the tuner simply did nothing.
        """
        if self.algorithm_map.get(self.algorithm_combo.currentText(), "0") != "6":
            self.algorithm_hint.setText("")
            widgets.set_label_color(self.algorithm_hint, widgets.STATUS_IDLE)
        elif hotspots_available_for_explorer(self.arguments.dot_dp):
            self.algorithm_hint.setText("Ranks hot code regions by their measured runtime. Reproducible across runs.")
            widgets.set_label_color(self.algorithm_hint, widgets.STATUS_IDLE)
        else:
            self.algorithm_hint.setText(
                "No hotspot detection results found - run Hotspot Detection first, or pick another algorithm."
            )
            widgets.set_label_color(self.algorithm_hint, widgets.STATUS_FAIL)

    def mode(self) -> str:
        return SEARCH_MODE if self.search_mode_radio.isChecked() else EVALUATE_MODE

    def _active_selector(self) -> SuggestionSelector:
        return self.search_space_selector if self.mode() == SEARCH_MODE else self.evaluate_selector

    def _update_mode_widgets(self) -> None:
        """Show / enable the selector of the active suggestion mode and disable the other.

        In 'evaluate' mode the optimization algorithm does not run (the autotuner checks the one fixed
        combination), so its dropdown is disabled too.
        """
        search = self.mode() == SEARCH_MODE
        self.search_space_container.setVisible(search)
        self.evaluate_container.setVisible(not search)
        self.search_space_selector.set_enabled(search)
        self.evaluate_selector.set_enabled(not search)
        self.algorithm_combo.setEnabled(search)
        self._update_suggestion_count()

    def _update_suggestion_count(self) -> None:
        """Update the 'N of M selected' overview for the active selector."""
        selector = self._active_selector()
        total = len(selector.get_available_ids())
        selected = len(selector.get_selected_ids())
        if total == 0:
            _set_state_text(self.suggestions_count_label, "No suggestions available", False)
        else:
            _set_state_text(self.suggestions_count_label, f"{selected} of {total} selected", selected > 0)

    def _open_suggestion_browser(self) -> None:
        open_suggestion_browser(self, self.arguments.dot_dp)

    def _update_config_display(self) -> None:
        current = self.project_state.current_config
        _set_state_text(self.config_label, current or "(none selected)", bool(current))

    def _update_ui(self) -> None:
        # a running tuning keeps its Run button disabled, whatever changed meanwhile
        self.run_button.setEnabled(not self.running)
        self._refresh_suggestions_display()
        self.update_tab_state()

    def update_tab_state(self) -> None:
        """Enable the Autotuning tab when profiling data and parallelization suggestions exist."""
        dot_dp = self.arguments.dot_dp
        ready = explorer_prerequisites_met(dot_dp) and has_patches(dot_dp)
        self._tabs.set_tab_enabled(TAB_AUTOTUNING, ready, "" if ready else TAB_DISABLED_TOOLTIP)

    def _refresh_suggestions_display(self) -> None:
        """Re-read the suggestions and the autotuner's results into the selectors and the overview."""
        self.search_space_selector.refresh()
        self.evaluate_selector.refresh()
        self.browse_button.setEnabled(len(self.search_space_selector.get_available_ids()) > 0)
        self._update_suggestion_count()

        autotuner_executed = autotuner_results_exist(self.arguments.dot_dp)
        suggested_ids: List[str] = []
        if autotuner_executed:
            config_key = self.project_state.current_config or ""
            suggested_ids = sort_suggestion_ids(read_autotuner_applied_suggestions(self.arguments.dot_dp, config_key))

        if suggested_ids:
            _set_state_text(self.suggestions_label, ", ".join(suggested_ids), True)
        elif autotuner_executed:
            _set_state_text(self.suggestions_label, "No suggestions selected", False)
        else:
            _set_state_text(self.suggestions_label, "Autotuner not yet executed", False)

    # ── the live plot ────────────────────────────────────────────────────────

    def _on_progress(self, event: Dict[str, Any]) -> None:
        """Ingest one progress event and refresh the live plot."""
        self.progress_model.ingest(event)
        self._announce_not_applied(event)
        self._redraw_plot()
        self._update_tiles()

    def _announce_not_applied(self, event: Dict[str, Any]) -> None:
        """Echo a not-applied measurement to the console as it happens.

        The plot already encodes the state, but the console is the place a user looks when a search "found
        nothing": without this line an unpatchable suggestion set is indistinguishable from one that simply did not
        help.
        """
        if event.get("event") != "measurement":
            return
        failed = event.get("failed_suggestions") or []
        if not (event.get("application_failed") or failed):
            return
        self._reported_not_applied += 1
        suggestions = failed or event.get("suggestions") or []
        self.console.append_text(
            "⚠ Suggestion application failed for "
            + (", ".join(str(s) for s in suggestions) if suggestions else "(unknown)")
            + " - configuration skipped, not measured.\n"
        )

    def _redraw_plot(self) -> None:
        autotuning_chart.render(self.figure, self.progress_model)
        chart_embedding.redraw(self.canvas)

    def _update_tiles(self) -> None:
        for label, (_key, value) in zip(self.tile_values, self.progress_model.summary_tiles()):
            label.setText(value)
        self._update_warning()

    def _update_warning(self) -> None:
        """Show / hide the not-applied banner above the live plot."""
        warning = self.progress_model.not_applied_warning()
        if warning is None:
            self.warning_label.hide()
            self.warning_label.setText("")
            return
        self.warning_label.setText(warning + " Their runtimes are not measurements - the code was left unmodified.")
        self.warning_label.show()

    def _load_progress_from_file(self) -> None:
        """Populate the live plot from a previous run's progress.jsonl, if present."""
        path = os.path.join(self.arguments.dot_dp, "auto_tuner", "progress.jsonl")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                events = parse_progress_jsonl(f.read())
        except OSError:
            return
        if not events:
            return
        self.progress_model = ProgressModel.from_events(events)
        self._redraw_plot()
        self._update_tiles()

    # ── running ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        if self.running:
            dialogs.show_error(self, "Already Running", "Autotuning is already running.")
            return
        if not self.project_state.current_config:
            dialogs.show_error(self, "No Configuration Selected", "Please select a configuration first.")
            return

        self.running = True
        self.run_button.setEnabled(False)
        self.run_button.setText("⟳ Running...")
        self.stop_button.setEnabled(True)
        self.status.set("⏳ Autotuning in progress...", widgets.STATUS_BUSY)
        self.console.set_text("")

        # start a fresh live plot for this run
        self.progress_model = ProgressModel()
        self._reported_not_applied = 0
        self._redraw_plot()
        self._update_tiles()

        # the job's thread must not read the widgets
        request = self._snapshot_request()
        dot_discopop = self.arguments.dot_dp
        self.console.append_text("Starting autotuning...\n")
        self._announce_request(request)

        events: "queue.Queue[JobEvent]" = queue.Queue()
        # SIGINT (not SIGTERM/terminate()) so the autotuner's search loop takes the same KeyboardInterrupt path as a
        # manual Ctrl+C, letting it finish gracefully and save the best solution found so far. Sent to the process
        # group as a terminal does, so the program it is measuring stops too instead of running on.
        job = JobRunner(
            JobSpec(
                autotuner_command(request, dot_discopop),
                cwd=dot_discopop,
                cancel_policy=CancelPolicy.SIGINT_GROUP,
                new_session=True,
            ),
            events,
        )
        self._job = job
        QtJobAdapter(self, events, self._on_job_event).start()
        job.start()

    def _on_job_event(self, event: JobEvent) -> None:
        """Handle one event of the autotuner job (main thread)."""
        if isinstance(event, JobOutput):
            # Structured progress events drive the live plot and are kept out of the console; everything else is
            # echoed to the console. Events are extracted from anywhere in the line: stdout and stderr share one
            # stream, so a progress bar redraw can leave its bar text in front of an event.
            progress_events, residual = split_progress_events(event.line + "\n")
            for progress_event in progress_events:
                self._on_progress(progress_event)
            cleaned = clean_ansi_output(residual.rstrip("\n"))
            if cleaned:
                self.console.append_text(cleaned + "\n")
        elif isinstance(event, JobFinished):
            self._job = None
            if event.cancelled:
                # the tuner keeps what it measured until the stop, whatever its exit code
                self.console.append_text("\nAutotuning stopped.\n")
                self._on_complete(stopped=True)
            elif event.returncode != 0:
                self.console.append_text(f"\nError: Autotuner exited with return code {event.returncode}\n")
                self._on_complete(error=True)
            else:
                self.console.append_text("\nAutotuning completed.\n")
                self._on_complete()
        elif isinstance(event, JobFailedToStart):
            self._job = None
            self.console.append_text(f"\nError: {event.error}\n")
            self._on_complete(error=True)

    def _snapshot_request(self) -> AutotunerRequest:
        """Read the panel into an immutable request."""
        selected_types = [hotspot_type for hotspot_type, check in self.hotspot_type_checks.items() if check.isChecked()]
        hotspot_types = ",".join(selected_types) if selected_types else "yes,no,maybe"

        # an unusable value falls back to measuring each candidate once (the field only offers whole numbers >= 1,
        # the check keeps the request valid whatever the field is changed to)
        repetitions = self.repetitions.value()
        repetitions_warning = validate_repetitions(repetitions)
        if repetitions_warning is not None:
            repetitions = DEFAULT_TUNING_REPETITIONS

        mode = self.mode()
        evaluate_ids: Tuple[str, ...] = ()
        search_space_ids: Optional[Tuple[str, ...]] = None
        if mode == EVALUATE_MODE:
            evaluate_ids = tuple(self.evaluate_selector.get_selected_ids())
        elif not self.search_space_selector.is_all_selected():
            search_space_ids = tuple(self.search_space_selector.get_selected_ids())

        return AutotunerRequest(
            configuration=self.project_state.current_config or "tiny",
            hotspot_types=hotspot_types,
            threads=self.threads.value(),
            repetitions=repetitions,
            repetitions_warning=repetitions_warning,
            algorithm=self.algorithm_map.get(self.algorithm_combo.currentText(), "0"),
            log_level=self.log_level.currentText(),
            mode=mode,
            evaluate_ids=evaluate_ids,
            search_space_ids=search_space_ids,
        )

    def _announce_request(self, request: AutotunerRequest) -> None:
        output: Callable[[str], None] = self.console.append_text
        if request.repetitions_warning is not None:
            output(
                "Ignoring the repetition count: " + request.repetitions_warning + ". Measuring each candidate once.\n"
            )

        output("Configuration:\n")
        output(f"  Configuration: {request.configuration}\n")
        output(f"  Hotspot Types: {request.hotspot_types}\n")
        output(f"  Threads: {request.threads}\n")
        output(f"  Repetitions: {request.repetitions}\n")
        output(f"  Algorithm: {request.algorithm}\n")
        output(f"  Log Level: {request.log_level}\n\n")

        if request.mode == EVALUATE_MODE:
            if request.evaluate_ids:
                output("Evaluating specific combination: " + ", ".join(request.evaluate_ids) + "\n")
            else:
                output("No suggestions selected to evaluate; running the search algorithm instead.\n")
        elif request.search_space_ids is not None:
            output(
                "Restricting search space to suggestion IDs: "
                + (", ".join(request.search_space_ids) or "(none)")
                + "\n"
            )
        output("Running autotuner...\n\n")

    def _on_complete(self, error: bool = False, stopped: bool = False) -> None:
        self.running = False

        # progress.jsonl is the authoritative record of the finished run: rebuild the plot from it, so the final view
        # is complete even if a live event was lost
        self._load_progress_from_file()

        self.run_button.setEnabled(True)
        self.run_button.setText("Run Autotuning")
        self.stop_button.setEnabled(False)

        if stopped:
            self.project_state.publish(AutotuningFinished())
            self.status.set("Autotuning stopped", widgets.STATUS_IDLE, reset_ms=3000)
        elif not error:
            self.project_state.publish(AutotuningFinished())
            not_applied = self.progress_model.counts()[3]
            if not_applied:
                self.status.set(
                    f"⚠ Autotuning completed - {not_applied} configuration(s) could not be patched",
                    widgets.STATUS_FAIL,
                    reset_ms=6000,
                )
            else:
                self.status.set("Autotuning completed successfully", widgets.STATUS_OK, reset_ms=6000)
        else:
            self.status.set("Autotuning failed", widgets.STATUS_FAIL, reset_ms=3000)

    def stop(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self.stop_button.setEnabled(False)
        self.project_state.publish(ResultsChanged())
        self.status.set("Stopping autotuning...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        if self._job is not None:
            self._job.cancel()
