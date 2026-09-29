# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional

from discopop_library.ProjectManager.gui.mixins.helpers import show_error, Tooltip, clean_ansi_output
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_TUNING_REPETITIONS,
    validate_repetitions,
)
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.gui.widgets import (
    create_styled_output_console,
    heading_label,
    caption_label,
)
from discopop_library.ProjectManager.gui.plots import autotuning_chart, embedding, mode_style
from discopop_library.ProjectManager.gui.plots.autotuning_chart import ProgressModel
from discopop_library.ProjectManager.gui.plots.data import parse_progress_jsonl, split_progress_events
from discopop_library.ProjectManager.gui.plots.hotspot_data import hotspots_available_for_explorer

logger_name = "AutotuningPanel"


class AutotuningPanelMixin(ConfigManagerMixinBase):
    autotuning_running = False
    autotuning_output_text: Optional[scrolledtext.ScrolledText] = None
    autotuning_run_button: Optional[RoundedButton] = None
    autotuning_stop_button: Optional[RoundedButton] = None
    autotuning_config_label: Optional[ttk.Label] = None
    autotuning_threads_var: Optional[tk.StringVar] = None
    autotuning_repetitions_var: Optional[tk.StringVar] = None
    autotuning_hotspot_types_vars: Optional[Dict[str, tk.BooleanVar]] = None
    autotuning_algorithm_var: Optional[tk.StringVar] = None
    autotuning_algorithm_map: Dict[str, str] = {}
    autotuning_algorithm_hint: Optional[ttk.Label] = None
    autotuning_log_level_var: Optional[tk.StringVar] = None
    autotuning_suggestions_label: Optional[ttk.Label] = None
    _autotuning_tab_tooltip: Optional[Any] = None
    _autotuning_tab_tooltip_timer: Optional[str] = None
    _autotuning_tab_tooltip_active_tab: Optional[int] = None
    _autotuning_process: Optional["subprocess.Popen[str]"] = None
    # Live-plot state (Live Plot sub-tab): matplotlib figure/canvas, the accumulated
    # progress model, and the value labels of the summary tile row.
    _autotuning_figure: Optional[Any] = None
    _autotuning_canvas: Optional[Any] = None
    _autotuning_progress_model: Optional[ProgressModel] = None
    _autotuning_tile_values: Optional[List[Any]] = None
    _autotuning_plot_frame: Optional[tk.Widget] = None
    # Banner above the live plot, shown only while configurations could not be patched.
    _autotuning_warning_label: Optional[ttk.Label] = None
    # how many not-applied configurations have already been announced on the console
    _autotuning_reported_not_applied: int = 0

    def _build_autotuning_panel(self, parent: tk.Widget) -> None:
        main_paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Left panel - scrollable settings, with the Run/Stop buttons and the
        # "Selected Suggestion IDs" overview pinned below (mirrors the Execute tab).
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, minsize=650, width=650)

        scroll_container = ttk.Frame(left_frame)
        scroll_container.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(scroll_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(scroll_container, highlightthickness=0, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=canvas.yview)

        options_outer = ttk.Frame(canvas)
        _win = canvas.create_window((0, 0), window=options_outer, anchor=tk.NW)

        def _on_content_configure(event: Any) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_resize(event: Any) -> None:
            canvas.itemconfig(_win, width=event.width)

        options_outer.bind("<Configure>", _on_content_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event: Any) -> object:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def _bind_scroll(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
            for child in widget.winfo_children():
                _bind_scroll(child)  # type: ignore

        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        settings_frame = ttk.LabelFrame(options_outer, text="Settings", padding=5)
        settings_frame.pack(fill=tk.X, padx=5, pady=5)

        # Configuration display
        config_row = ttk.Frame(settings_frame)
        config_row.pack(fill=tk.X, pady=3)
        heading_label(config_row, "Configuration:").pack(side=tk.LEFT, padx=5)
        self.autotuning_config_label = caption_label(config_row, "(none selected)")
        self.autotuning_config_label.pack(side=tk.LEFT, padx=5)

        # Threads selection
        threads_row = ttk.Frame(settings_frame)
        threads_row.pack(fill=tk.X, pady=5)
        ttk.Label(threads_row, text="Threads:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.autotuning_threads_var = tk.StringVar(value=widgets.THREAD_AUTO)
        threads_combo = widgets.thread_selector(threads_row, self.autotuning_threads_var)
        threads_combo.pack(side=tk.LEFT, padx=5)
        caption_label(threads_row, "(auto = CPU count / 2; custom counts can be typed)").pack(side=tk.LEFT, padx=5)

        # Repetitions
        # Kept apart from the count used for the measured runs (Execute tab): the
        # search performs one program execution per candidate, so repeating every
        # one of them multiplies the tuning time. Raising it is worth it only when
        # the machine's noise is large enough to decide the search's comparisons.
        repetitions_row = ttk.Frame(settings_frame)
        repetitions_row.pack(fill=tk.X, pady=5)
        ttk.Label(repetitions_row, text="Repetitions:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.autotuning_repetitions_var = tk.StringVar(value=str(DEFAULT_TUNING_REPETITIONS))
        ttk.Entry(repetitions_row, textvariable=self.autotuning_repetitions_var, width=6).pack(side=tk.LEFT, padx=5)
        caption_label(
            repetitions_row,
            "(runs per candidate; the median decides its rank. Above 1 multiplies the tuning time)",
        ).pack(side=tk.LEFT, padx=5)

        # Hotspot types
        hotspot_frame = ttk.Frame(settings_frame)
        hotspot_frame.pack(fill=tk.X, pady=5)
        heading_label(hotspot_frame, "Hotspot Types:").pack(anchor=tk.W, padx=5)

        self.autotuning_hotspot_types_vars = {}
        for htype in ["yes", "no", "maybe"]:
            var = tk.BooleanVar(value=htype == "yes")
            self.autotuning_hotspot_types_vars[htype] = var
            cb = ttk.Checkbutton(hotspot_frame, text=htype.upper(), variable=var)
            cb.pack(side=tk.LEFT, padx=20)

        # Algorithm selection
        algo_frame = ttk.Frame(settings_frame)
        algo_frame.pack(fill=tk.X, pady=5)
        heading_label(algo_frame, "Algorithm:").pack(anchor=tk.W, padx=5)
        # Default to the deterministic search: repeating a tuning run reproduces its
        # decisions, which the randomized evolutionary search cannot promise.
        self.autotuning_algorithm_var = tk.StringVar(value="Hotspot-guided region descent")
        algo_options = [
            ("0", "No combination (measure only)"),
            ("1", "Linear combination"),
            ("3", "Evolutionary combination"),
            ("4", "Greedy combination"),
            ("5", "Coordinate descent combination"),
            ("6", "Hotspot-guided region descent"),
        ]
        self.autotuning_algorithm_map = {opt[1]: opt[0] for opt in algo_options}
        algo_combo = ttk.Combobox(algo_frame, textvariable=self.autotuning_algorithm_var, state="readonly", width=40)
        algo_combo["values"] = [opt[1] for opt in algo_options]
        algo_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.autotuning_algorithm_combo = algo_combo

        # The default algorithm stops immediately when no hotspot detection results
        # exist, so say that here rather than letting the run fail for a reason that
        # is only visible in the console output.
        self.autotuning_algorithm_hint = caption_label(algo_frame, "")
        self.autotuning_algorithm_hint.pack(anchor=tk.W, padx=5)
        algo_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_algorithm_hint())
        self._update_algorithm_hint()

        # Log level
        loglevel_frame = ttk.Frame(settings_frame)
        loglevel_frame.pack(fill=tk.X, pady=5)
        ttk.Label(loglevel_frame, text="Log Level:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.autotuning_log_level_var = tk.StringVar(value="WARNING")
        loglevel_combo = ttk.Combobox(
            loglevel_frame,
            textvariable=self.autotuning_log_level_var,
            values=widgets.LOG_LEVEL_VALUES,
            state="readonly",
            width=10,
        )
        loglevel_combo.pack(side=tk.LEFT, padx=5)

        # Suggestion selection: pick between searching for the best combination
        # (algorithm + restricted search space) and evaluating one fixed combination.
        selection_frame = ttk.LabelFrame(options_outer, text="Suggestion Selection", padding=5)
        selection_frame.pack(fill=tk.X, padx=5, pady=5)

        self.autotuning_suggestions_mode_var = tk.StringVar(value="search")
        ttk.Radiobutton(
            selection_frame,
            text="Search for best combination",
            variable=self.autotuning_suggestions_mode_var,
            value="search",
            command=self._update_autotuning_mode_widgets,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            selection_frame,
            text="Evaluate a specific combination",
            variable=self.autotuning_suggestions_mode_var,
            value="evaluate",
            command=self._update_autotuning_mode_widgets,
        ).pack(anchor=tk.W)

        # Overview of the active selector + shortcut to the patch viewer/editor,
        # mirroring the Execute tab.
        info_row = ttk.Frame(selection_frame)
        info_row.pack(fill=tk.X, pady=(3, 0))
        self.autotuning_suggestions_count_label = ttk.Label(
            info_row, text="No suggestions available", foreground="gray", font=widgets.FONT_CAPTION
        )
        self.autotuning_suggestions_count_label.pack(side=tk.LEFT, padx=(20, 10))
        self.autotuning_browse_edit_button = widgets.create_button(
            info_row, text="Browse / Edit →", command=self._open_suggestion_browser, state="disabled"
        )
        self.autotuning_browse_edit_button.pack(side=tk.LEFT)

        self._autotuner_search_space_container = ttk.Frame(selection_frame)
        caption_label(self._autotuner_search_space_container, "Suggestions the algorithm may explore:").pack(
            anchor=tk.W, padx=(20, 0)
        )
        self.autotuner_search_space_selector = SuggestionSelector(
            self._autotuner_search_space_container,
            self.arguments.dot_dp,
            "autotuner_search_space",
            on_change=self._update_autotuning_suggestion_count,
        )
        self.autotuner_search_space_selector.pack(fill=tk.X, padx=(20, 0))

        self._autotuner_evaluate_container = ttk.Frame(selection_frame)
        caption_label(
            self._autotuner_evaluate_container, "Suggestions to apply together and compare to the baseline:"
        ).pack(anchor=tk.W, padx=(20, 0))
        self.autotuner_evaluate_selector = SuggestionSelector(
            self._autotuner_evaluate_container,
            self.arguments.dot_dp,
            "autotuner_evaluate",
            on_change=self._update_autotuning_suggestion_count,
        )
        self.autotuner_evaluate_selector.pack(fill=tk.X, padx=(20, 0))

        self._update_autotuning_mode_widgets()

        # Horizontal divider separating the action buttons from the settings above.
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(8, 0))

        # Run button
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, padx=0, pady=0)

        self.autotuning_run_button = widgets.primary_button(
            button_frame, text="Run Autotuning", command=self._run_autotuning, state="disabled"
        )
        self.autotuning_run_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.autotuning_stop_button = widgets.danger_button(
            button_frame, text="Stop", command=self._stop_autotuning, state="disabled"
        )
        self.autotuning_stop_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Selected suggestions display
        suggestions_frame = ttk.LabelFrame(left_frame, text="Selected Suggestion IDs", padding=5)
        suggestions_frame.pack(fill=tk.X, padx=5, pady=5)

        self.autotuning_suggestions_label = caption_label(suggestions_frame, "(none)", justify=tk.LEFT)
        self.autotuning_suggestions_label.pack(anchor=tk.W)

        # Right panel - a sub-notebook: a live search plot (default) and the
        # raw console. The plot auto-refreshes from the autotuner's @@AT_PROGRESS
        # stream; the console keeps the human-readable log.
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame)

        right_notebook = ttk.Notebook(right_frame)
        right_notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # --- Live Plot tab (default) ---
        plot_tab = ttk.Frame(right_notebook)
        right_notebook.add(plot_tab, text="📈 Live Plot")

        tiles_frame = ttk.Frame(plot_tab)
        tiles_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(6, 2))
        self._autotuning_tile_values = []
        # placeholder tiles; labels come from an empty model so they read "—"
        for key, value in ProgressModel().summary_tiles():
            tile = ttk.Frame(tiles_frame)
            tile.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3)
            caption_label(tile, key).pack(anchor=tk.W)
            value_label = heading_label(tile, value)
            value_label.pack(anchor=tk.W)
            self._autotuning_tile_values.append(value_label)

        # Warning banner: a configuration whose patches did not apply was never run,
        # so it is not a parallel measurement. Called out here as well as in the plot,
        # because it invalidates the conclusion one would otherwise draw from the run.
        self._autotuning_warning_label = ttk.Label(
            plot_tab,
            text="",
            foreground=mode_style.status_color(mode_style.NOT_APPLIED_STATUS),
            font=widgets.FONT_BODY,
            wraplength=900,
            justify=tk.LEFT,
        )

        plot_frame = ttk.Frame(plot_tab)
        plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._autotuning_plot_frame = plot_frame
        self._autotuning_figure, self._autotuning_canvas, _ = embedding.create_canvas(plot_frame)
        self._autotuning_progress_model = ProgressModel()

        # --- Console tab ---
        console_tab = ttk.Frame(right_notebook)
        right_notebook.add(console_tab, text="🖥 Console")
        self.autotuning_output_text = create_styled_output_console(console_tab)
        self.autotuning_output_text.pack(fill=tk.BOTH, expand=True)

        _bind_scroll(options_outer)
        self._update_autotuning_ui()
        self._setup_autotuning_tab_tooltip()
        # show the last run (if any) so the plot is not empty on open
        self._load_autotuning_progress_from_file()

    def _update_algorithm_hint(self) -> None:
        """Warn when the selected algorithm needs hotspot data the project lacks.

        Only the hotspot-guided descent hard-requires ``Hotspots.json``; it aborts
        without measuring anything when none exists. Since it is the default, a
        project that never ran hotspot detection would otherwise look as though the
        tuner simply did nothing.
        """
        hint = getattr(self, "autotuning_algorithm_hint", None)
        if hint is None or self.autotuning_algorithm_var is None:
            return

        selected = self.autotuning_algorithm_map.get(self.autotuning_algorithm_var.get(), "0")
        if selected != "6":
            hint.config(text="", foreground=widgets.STATUS_IDLE)
            return

        if hotspots_available_for_explorer(self.arguments.dot_dp):
            hint.config(
                text="Ranks hot code regions by their measured runtime. Reproducible across runs.",
                foreground=widgets.STATUS_IDLE,
            )
        else:
            hint.config(
                text="No hotspot detection results found - run Hotspot Detection first, " "or pick another algorithm.",
                foreground=widgets.STATUS_FAIL,
            )

    def _update_autotuning_ui(self) -> None:
        if self.autotuning_run_button is not None:
            self.autotuning_run_button.config(state="normal")

        self._refresh_autotuning_suggestions_display()

    def _setup_autotuning_tab_tooltip(self) -> None:
        tooltip_text = "Prerequisites not met:\n" "Pattern Detection needs to be executed first."
        self._autotuning_tab_tooltip = Tooltip(self.right_tabs, tooltip_text)

        def on_motion(event: Any) -> None:
            try:
                result = self.right_tabs.tk.call(str(self.right_tabs), "identify", "tab", event.x, event.y)
                tab_under_cursor: Optional[int] = int(result) if result != "" else None
            except Exception:
                tab_under_cursor = None

            if tab_under_cursor == self._autotuning_tab_tooltip_active_tab:
                return

            _hide_tooltip()

            if tab_under_cursor == self.autotuning_tab_index:
                ready = self._check_explorer_prerequisites() if hasattr(self, "_check_explorer_prerequisites") else True
                browse_ready = (
                    self._check_browse_suggestions_available()
                    if hasattr(self, "_check_browse_suggestions_available")
                    else True
                )
                if not (ready and browse_ready):
                    self._autotuning_tab_tooltip_active_tab = tab_under_cursor
                    assert self._autotuning_tab_tooltip is not None
                    self._autotuning_tab_tooltip_timer = self.after(  # type: ignore
                        500, self._autotuning_tab_tooltip.showtip, event.x_root, event.y_root + 20
                    )

        def _hide_tooltip() -> None:
            if self._autotuning_tab_tooltip_timer:
                self.after_cancel(self._autotuning_tab_tooltip_timer)  # type: ignore
                self._autotuning_tab_tooltip_timer = None
            if self._autotuning_tab_tooltip is not None:
                self._autotuning_tab_tooltip.hidetip()
            self._autotuning_tab_tooltip_active_tab = None

        def on_leave(event: Any) -> None:
            _hide_tooltip()

        self.right_tabs.bind("<Motion>", on_motion, add="+")
        self.right_tabs.bind("<Leave>", on_leave, add="+")

    def _update_autotuning_mode_widgets(self) -> None:
        """Show/enable the selector for the active suggestion mode; disable the other.

        In 'evaluate' mode the optimization algorithm does not run (the autotuner
        checks the one fixed combination), so its dropdown is disabled too.
        """
        if not hasattr(self, "autotuner_search_space_selector"):
            return
        search = self.autotuning_suggestions_mode_var.get() == "search"
        if search:
            self._autotuner_evaluate_container.pack_forget()
            self._autotuner_search_space_container.pack(fill=tk.X, pady=(3, 0))
        else:
            self._autotuner_search_space_container.pack_forget()
            self._autotuner_evaluate_container.pack(fill=tk.X, pady=(3, 0))
        self.autotuner_search_space_selector.set_enabled(search)
        self.autotuner_evaluate_selector.set_enabled(not search)
        if hasattr(self, "autotuning_algorithm_combo"):
            self.autotuning_algorithm_combo.config(state="readonly" if search else "disabled")
        self._update_autotuning_suggestion_count()

    def _update_autotuning_suggestion_count(self) -> None:
        """Update the 'N of M selected' overview for the currently active selector."""
        if not hasattr(self, "autotuning_suggestions_count_label") or not hasattr(
            self, "autotuner_search_space_selector"
        ):
            return
        search = self.autotuning_suggestions_mode_var.get() == "search"
        selector = self.autotuner_search_space_selector if search else self.autotuner_evaluate_selector
        total = len(selector.get_available_ids())
        selected = len(selector.get_selected_ids())
        if total == 0:
            self.autotuning_suggestions_count_label.config(text="No suggestions available", foreground="gray")
        else:
            fg = "black" if selected > 0 else "gray"
            self.autotuning_suggestions_count_label.config(text=f"{selected} of {total} selected", foreground=fg)

    def _refresh_autotuning_suggestions_display(self) -> None:
        """Read autotuning results and update the display label."""
        if hasattr(self, "autotuner_search_space_selector"):
            self.autotuner_search_space_selector.refresh()
        if hasattr(self, "autotuner_evaluate_selector"):
            self.autotuner_evaluate_selector.refresh()
        if hasattr(self, "autotuning_browse_edit_button"):
            total = len(self.autotuner_search_space_selector.get_available_ids())
            self.autotuning_browse_edit_button.config(state="normal" if total > 0 else "disabled")
        self._update_autotuning_suggestion_count()
        if not hasattr(self, "autotuning_suggestions_label") or self.autotuning_suggestions_label is None:
            return

        results_path = os.path.join(self.arguments.dot_dp, "auto_tuner", "results.json")
        suggested_ids = []
        autotuner_executed = os.path.exists(results_path)

        if autotuner_executed:
            try:
                with open(results_path, "r") as f:
                    results_data = json.load(f)
                config_key = getattr(self, "current_config", None) or ""
                config_results = results_data.get(config_key, {})
                suggested_ids = sorted(
                    [str(sid) for sid in config_results.get("applied_suggestions", [])],
                    key=lambda x: int(x) if x.isdigit() else x,
                )
            except (json.JSONDecodeError, IOError):
                pass

        if suggested_ids:
            self.autotuning_suggestions_label.config(text=", ".join(suggested_ids), foreground="black")
        elif autotuner_executed:
            self.autotuning_suggestions_label.config(text="No suggestions selected", foreground="gray")
        else:
            self.autotuning_suggestions_label.config(text="Autotuner not yet executed", foreground="gray")

    def _on_autotuning_progress(self, event: Dict[str, Any]) -> None:
        """Ingest one progress event (main thread) and refresh the live plot."""
        if self._autotuning_progress_model is None:
            self._autotuning_progress_model = ProgressModel()
        self._autotuning_progress_model.ingest(event)
        self._announce_not_applied(event)
        self._redraw_autotuning_plot()
        self._update_autotuning_tiles()

    def _announce_not_applied(self, event: Dict[str, Any]) -> None:
        """Echo a not-applied measurement to the console as it happens.

        The plot already encodes the state, but the console is the place a user looks
        when a search "found nothing": without this line an unpatchable suggestion set
        is indistinguishable from one that simply did not help.
        """
        if event.get("event") != "measurement":
            return
        failed = event.get("failed_suggestions") or []
        if not (event.get("application_failed") or failed):
            return
        if self.autotuning_output_text is None:
            return
        self._autotuning_reported_not_applied += 1
        suggestions = failed or event.get("suggestions") or []
        text = (
            "⚠ Suggestion application failed for "
            + (", ".join(str(s) for s in suggestions) if suggestions else "(unknown)")
            + " - configuration skipped, not measured.\n"
        )
        self.autotuning_output_text.config(state=tk.NORMAL)
        self.autotuning_output_text.insert(tk.END, text)
        self.autotuning_output_text.see(tk.END)
        self.autotuning_output_text.config(state="disabled")

    def _redraw_autotuning_plot(self) -> None:
        if self._autotuning_figure is None or self._autotuning_progress_model is None:
            return
        autotuning_chart.render(self._autotuning_figure, self._autotuning_progress_model)
        if self._autotuning_canvas is not None:
            embedding.redraw(self._autotuning_canvas)

    def _update_autotuning_tiles(self) -> None:
        if self._autotuning_tile_values is None or self._autotuning_progress_model is None:
            return
        tiles = self._autotuning_progress_model.summary_tiles()
        for label_widget, (_key, value) in zip(self._autotuning_tile_values, tiles):
            label_widget.config(text=value)
        self._update_autotuning_warning()

    def _update_autotuning_warning(self) -> None:
        """Show/hide the not-applied banner above the live plot."""
        if self._autotuning_warning_label is None or self._autotuning_progress_model is None:
            return
        warning = self._autotuning_progress_model.not_applied_warning()
        if warning is None:
            self._autotuning_warning_label.pack_forget()
            self._autotuning_warning_label.config(text="")
            return
        self._autotuning_warning_label.config(
            text=warning + " Their runtimes are not measurements - the code was left unmodified."
        )
        self._autotuning_warning_label.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 4))

    def _load_autotuning_progress_from_file(self) -> None:
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
        self._autotuning_progress_model = ProgressModel.from_events(events)
        self._redraw_autotuning_plot()
        self._update_autotuning_tiles()
        # canvases built before the window is laid out render at the wrong size
        if self._autotuning_plot_frame is not None:
            embedding.force_resize_redraw(self._autotuning_plot_frame)

    def _update_autotuning_config_display(self) -> None:
        """Update the configuration display label."""
        if not hasattr(self, "autotuning_config_label") or self.autotuning_config_label is None:
            return

        if self.current_config:
            self.autotuning_config_label.config(text=self.current_config, foreground="black")
        else:
            self.autotuning_config_label.config(text="(none selected)", foreground="gray")

    def _run_autotuning(self) -> None:
        if self.autotuning_running:
            show_error(self, "Already Running", "Autotuning is already running.")
            return

        if not self.current_config:
            show_error(self, "No Configuration Selected", "Please select a configuration first.")
            return

        self.autotuning_running = True
        if self.autotuning_run_button is not None:
            self.autotuning_run_button.config(state="disabled", text="⟳ Running...")

        if self.autotuning_stop_button is not None:
            self.autotuning_stop_button.config(state="normal")

        self.status_label.config(text="⏳ Autotuning in progress...", foreground=widgets.STATUS_BUSY)

        if self.autotuning_output_text is not None:
            self.autotuning_output_text.config(state=tk.NORMAL)
            self.autotuning_output_text.delete("1.0", tk.END)
            self.autotuning_output_text.config(state="disabled")

        # start a fresh live plot for this run
        self._autotuning_progress_model = ProgressModel()
        self._autotuning_reported_not_applied = 0
        self._redraw_autotuning_plot()
        self._update_autotuning_tiles()

        def append_output(text: str) -> None:
            if self.autotuning_output_text is not None:
                self.autotuning_output_text.config(state=tk.NORMAL)
                self.autotuning_output_text.insert(tk.END, text)
                self.autotuning_output_text.see(tk.END)
                self.autotuning_output_text.config(state="disabled")

        def thread_safe_append(text: str) -> None:
            self.after(0, lambda: append_output(text))  # type: ignore

        def thread_func() -> None:
            try:
                thread_safe_append("Starting autotuning...\n")
                self._invoke_autotuner(thread_safe_append)
                self.after(0, lambda: self._on_autotuning_complete())  # type: ignore
            except Exception as e:
                thread_safe_append(f"\nError: {str(e)}\n")
                self.after(0, lambda: self._on_autotuning_complete(error=True))  # type: ignore

        thread = threading.Thread(target=thread_func, daemon=True)
        thread.start()

    def _invoke_autotuner(self, output_callback: Callable[[str], None]) -> None:
        assert self.autotuning_threads_var is not None
        assert self.autotuning_hotspot_types_vars is not None
        assert self.autotuning_algorithm_var is not None
        assert self.autotuning_log_level_var is not None

        dot_discopop = self.arguments.dot_dp

        selected_hotspot_types = [htype for htype, var in self.autotuning_hotspot_types_vars.items() if var.get()]
        hotspot_types = ",".join(selected_hotspot_types) if selected_hotspot_types else "yes,no,maybe"

        threads_value = widgets.thread_value(self.autotuning_threads_var)
        # A typo in the field must not abort a tuning run that is otherwise ready;
        # an unusable value falls back to measuring each candidate once, which is
        # what the run would have done before the field existed.
        repetitions_value = DEFAULT_TUNING_REPETITIONS
        if self.autotuning_repetitions_var is not None:
            typed = self.autotuning_repetitions_var.get().strip()
            try:
                parsed = int(typed)
                problem = validate_repetitions(parsed)
            except ValueError:
                parsed, problem = DEFAULT_TUNING_REPETITIONS, "expected a whole number, got '" + typed + "'"
            if problem is None:
                repetitions_value = parsed
            else:
                output_callback("Ignoring the repetition count: " + problem + ". Measuring each candidate once.\n")
        algorithm_description = self.autotuning_algorithm_var.get()
        algorithm_value = self.autotuning_algorithm_map.get(algorithm_description, "0")
        log_level = self.autotuning_log_level_var.get()

        output_callback("Configuration:\n")
        output_callback(f"  Configuration: {self.current_config}\n")
        output_callback(f"  Hotspot Types: {hotspot_types}\n")
        output_callback(f"  Threads: {threads_value}\n")
        output_callback(f"  Repetitions: {repetitions_value}\n")
        output_callback(f"  Algorithm: {algorithm_value}\n")
        output_callback(f"  Log Level: {log_level}\n\n")

        cmd = [
            sys.executable,
            "-m",
            "discopop_library.EmpiricalAutotuning",
            "--dot-dp-path",
            dot_discopop,
            "-c",
            self.current_config or "tiny",
            "-ht",
            hotspot_types,
            "-A",
            algorithm_value,
            "--log",
            log_level,
        ]

        if threads_value != "auto":
            cmd.extend(["-t", threads_value])

        # Emitted only when it changes something, so a default tuning run is the
        # command it was before this field existed.
        if repetitions_value > 1:
            cmd.extend(["-xr", str(repetitions_value)])

        mode = self.autotuning_suggestions_mode_var.get()
        if mode == "evaluate":
            evaluate_ids = self.autotuner_evaluate_selector.get_selected_ids()
            if evaluate_ids:
                cmd.extend(["-s", ",".join(evaluate_ids)])
                output_callback("Evaluating specific combination: " + ", ".join(evaluate_ids) + "\n")
            else:
                output_callback("No suggestions selected to evaluate; running the search algorithm instead.\n")
        else:
            if not self.autotuner_search_space_selector.is_all_selected():
                search_ids = self.autotuner_search_space_selector.get_selected_ids()
                cmd.extend(["--search-space", ",".join(search_ids)])
                output_callback(
                    "Restricting search space to suggestion IDs: " + (", ".join(search_ids) or "(none)") + "\n"
                )

        output_callback("Running autotuner...\n\n")

        self._autotuning_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=dot_discopop,
        )

        assert self._autotuning_process.stdout is not None
        for line in self._autotuning_process.stdout:
            # Structured progress events drive the live plot and are kept out of the
            # console; everything else is echoed to the console as before. Events are
            # extracted from anywhere in the line: stdout and stderr share one stream,
            # so a progress bar redraw can leave its bar text in front of an event.
            events, residual = split_progress_events(line)
            for event in events:
                self.after(0, lambda e=event: self._on_autotuning_progress(e))  # type: ignore
            cleaned = clean_ansi_output(residual.rstrip("\n"))
            if cleaned:
                output_callback(cleaned + "\n")

        self._autotuning_process.wait()

        if self._autotuning_process.returncode != 0:
            raise RuntimeError(f"Autotuner exited with return code {self._autotuning_process.returncode}")

        output_callback("\nAutotuning completed.\n")
        self._autotuning_process = None

    def _on_autotuning_complete(self, error: bool = False) -> None:
        self.autotuning_running = False

        # progress.jsonl is the authoritative record of the finished run: rebuild the
        # plot from it, so the final view is complete even if a live event was lost.
        self._load_autotuning_progress_from_file()

        if self.autotuning_run_button is not None:
            self.autotuning_run_button.config(state="normal", text="Run Autotuning")

        if self.autotuning_stop_button is not None:
            self.autotuning_stop_button.config(state="disabled")

        if not error:
            self._refresh_autotuning_suggestions_display()
            if hasattr(self, "_refresh_suggestion_selection_display"):
                self._refresh_suggestion_selection_display()
            if hasattr(self, "_update_report_display"):
                self._update_report_display()
            not_applied = (
                self._autotuning_progress_model.counts()[3] if self._autotuning_progress_model is not None else 0
            )
            if not_applied:
                self.status_label.config(
                    text=f"⚠ Autotuning completed - {not_applied} configuration(s) could not be patched",
                    foreground=widgets.STATUS_FAIL,
                )
            else:
                self.status_label.config(text="Autotuning completed successfully", foreground=widgets.STATUS_OK)
            self.after(6000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore
        else:
            self.status_label.config(text="Autotuning failed", foreground=widgets.STATUS_FAIL)
            self.after(3000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore

    def _stop_autotuning(self) -> None:
        if self._autotuning_process is not None:
            # Send SIGINT (not SIGTERM/terminate()) so the autotuner's search loop
            # takes the same KeyboardInterrupt path as a manual Ctrl+C, letting it
            # finish gracefully and save the best solution found so far.
            self._autotuning_process.send_signal(signal.SIGINT)
        if self.autotuning_stop_button is not None:
            self.autotuning_stop_button.config(state="disabled")
        if hasattr(self, "_update_report_display"):
            self._update_report_display()
        self.status_label.config(text="Stopping autotuning...", foreground=widgets.STATUS_STOP)
