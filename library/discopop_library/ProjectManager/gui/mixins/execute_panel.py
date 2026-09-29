# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from discopop_library.ProjectManager.configurations.repetitions import DEFAULT_MEASURED_REPETITIONS
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import caption_label
from discopop_library.ProjectManager.gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.gui.mixins.helpers import Tooltip, bind_tooltip_hover
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase


class ExecutePanelMixin(ConfigManagerMixinBase):
    def _build_execute_panel(self, parent: tk.Widget) -> None:
        main_paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Left panel - settings
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

        modes_frame = ttk.LabelFrame(options_outer, text="Execution Modes", padding=5)
        modes_frame.pack(fill=tk.X, padx=5, pady=5)

        modes_inner = ttk.Frame(modes_frame)
        modes_inner.pack(fill=tk.X)

        self.mode_vars: dict[str, tk.BooleanVar] = {}
        self.mode_checkbuttons: dict[str, ttk.Checkbutton] = {}
        mode_tooltips = {
            "seq": "Sequential",
            "dp": "DiscoPoP Instrumented",
            "hd": "Hotspot Detection",
            "par": "Parallel",
        }
        for mode, settings_file in [
            ("seq", "seq_settings.json"),
            ("dp", "dp_settings.json"),
            ("hd", "hd_settings.json"),
            ("par", "par_settings.json"),
        ]:
            var = tk.BooleanVar(value=mode == "seq")
            mode_text = f"{mode_tooltips[mode]} ({mode})"
            cb = ttk.Checkbutton(modes_inner, text=mode_text, variable=var, state="disabled")
            cb.pack(anchor=tk.W, padx=5, pady=2)
            self.mode_vars[mode] = var
            self.mode_checkbuttons[mode] = cb

        settings_frame = ttk.LabelFrame(options_outer, text="Execution Settings", padding=5)
        settings_frame.pack(fill=tk.X, padx=5, pady=5)

        cpu_count = os.cpu_count() or 4
        thread_frame = ttk.Frame(settings_frame)
        thread_frame.pack(fill=tk.X, pady=3)
        ttk.Label(
            thread_frame,
            text=f"Thread Count: (1-{cpu_count})",
            width=20,
            anchor=tk.W,
        ).pack(side=tk.LEFT)
        self.thread_var = tk.IntVar(value=cpu_count // 2)
        thread_entry = ttk.Entry(thread_frame, textvariable=self.thread_var, width=10)
        thread_entry.pack(side=tk.LEFT, padx=5)

        # Beside the thread count rather than among the timeouts: this is part of
        # what the run measures, not a limit imposed on it. Only the seq and par
        # runs are repeated -- dp and hd are instrumented profiling runs whose
        # output feeds the Explorer, and a median of those would mean nothing.
        repetitions_frame = ttk.Frame(settings_frame)
        repetitions_frame.pack(fill=tk.X, pady=3)
        ttk.Label(repetitions_frame, text="Repetitions:", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.execution_repetitions_var = tk.IntVar(value=DEFAULT_MEASURED_REPETITIONS)
        repetitions_entry = ttk.Entry(repetitions_frame, textvariable=self.execution_repetitions_var, width=10)
        repetitions_entry.pack(side=tk.LEFT, padx=5)
        caption_label(repetitions_frame, "(median of N is reported; 1 = measure once. seq/par only)").pack(
            side=tk.LEFT, padx=5
        )

        # The setting itself lives in Editor -> execute.sh, because it describes
        # that script's program. It is mirrored here read-only: the run is started
        # from this tab, so this tab must say which of the two times it produces.
        execution_time_frame = ttk.Frame(settings_frame)
        execution_time_frame.pack(fill=tk.X, pady=3)
        ttk.Label(execution_time_frame, text="Execution time:", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.execution_time_summary_label = caption_label(execution_time_frame, "")
        self.execution_time_summary_label.pack(side=tk.LEFT, padx=5)

        label_prefix_frame = ttk.Frame(settings_frame)
        label_prefix_frame.pack(fill=tk.X, pady=3)
        ttk.Label(label_prefix_frame, text="Label Prefix:", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.label_prefix_var = tk.StringVar(value="")
        label_prefix_entry = ttk.Entry(label_prefix_frame, textvariable=self.label_prefix_var, width=20)
        label_prefix_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        timeout_frame = ttk.LabelFrame(options_outer, text="Timeout Settings", padding=5)
        timeout_frame.pack(fill=tk.X, padx=5, pady=5)

        timeout_exec_frame = ttk.Frame(timeout_frame)
        timeout_exec_frame.pack(fill=tk.X, pady=3)
        ttk.Label(timeout_exec_frame, text="Execution (s):", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.timeout_execution_var = tk.IntVar(value=3600)
        timeout_exec_entry = ttk.Entry(timeout_exec_frame, textvariable=self.timeout_execution_var, width=10)
        timeout_exec_entry.pack(side=tk.LEFT, padx=5)
        caption_label(timeout_exec_frame, "(0 = disabled)").pack(side=tk.LEFT, padx=5)

        timeout_comp_frame = ttk.Frame(timeout_frame)
        timeout_comp_frame.pack(fill=tk.X, pady=3)
        ttk.Label(timeout_comp_frame, text="Compilation (s):", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.timeout_compilation_var = tk.IntVar(value=3600)
        timeout_comp_entry = ttk.Entry(timeout_comp_frame, textvariable=self.timeout_compilation_var, width=10)
        timeout_comp_entry.pack(side=tk.LEFT, padx=5)
        caption_label(timeout_comp_frame, "(0 = disabled)").pack(side=tk.LEFT, padx=5)

        timeout_val_frame = ttk.Frame(timeout_frame)
        timeout_val_frame.pack(fill=tk.X, pady=3)
        ttk.Label(timeout_val_frame, text="Validation (s):", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.timeout_validation_var = tk.IntVar(value=3600)
        timeout_val_entry = ttk.Entry(timeout_val_frame, textvariable=self.timeout_validation_var, width=10)
        timeout_val_entry.pack(side=tk.LEFT, padx=5)
        caption_label(timeout_val_frame, "(0 = disabled, validate.sh only)").pack(side=tk.LEFT, padx=5)

        behavior_frame = ttk.LabelFrame(options_outer, text="Logging & Behavior", padding=5)
        behavior_frame.pack(fill=tk.X, padx=5, pady=5)

        log_level_frame = ttk.Frame(behavior_frame)
        log_level_frame.pack(fill=tk.X, pady=3)
        ttk.Label(log_level_frame, text="Log Level:", width=20, anchor=tk.W).pack(side=tk.LEFT)
        self.log_level_var = tk.StringVar(value="WARNING")
        log_level_combo = ttk.Combobox(
            log_level_frame,
            textvariable=self.log_level_var,
            values=widgets.LOG_LEVEL_VALUES,
            state="readonly",
            width=10,
        )
        log_level_combo.pack(side=tk.LEFT, padx=5)

        checkboxes_frame = ttk.Frame(behavior_frame)
        checkboxes_frame.pack(fill=tk.X, pady=3)

        self.inplace_var = tk.BooleanVar(value=False)
        inplace_cb = ttk.Checkbutton(
            checkboxes_frame,
            text="Execute in-place (skip project copy)",
            variable=self.inplace_var,
        )
        inplace_cb.pack(anchor=tk.W)

        inplace_tooltip = Tooltip(
            inplace_cb,
            "In-place: execution modifies your project directory directly\n"
            "Non-in-place: execution happens in a copy, keeping your project clean",
        )
        bind_tooltip_hover(inplace_cb, inplace_tooltip, self)

        self.skip_cleanup_var = tk.BooleanVar(value=False)
        skip_cleanup_cb = ttk.Checkbutton(
            checkboxes_frame,
            text="Skip cleanup (keep project copies)",
            variable=self.skip_cleanup_var,
        )
        skip_cleanup_cb.pack(anchor=tk.W)

        skip_cleanup_tooltip = Tooltip(
            skip_cleanup_cb,
            "Warning: Enabling this may result in significant disk space usage\n"
            "as project copies are retained after execution.",
        )
        bind_tooltip_hover(skip_cleanup_cb, skip_cleanup_tooltip, self)

        suggestions_frame = ttk.LabelFrame(options_outer, text="Apply Suggestions", padding=5)
        suggestions_frame.pack(fill=tk.X, padx=5, pady=5)

        self.suggestions_mode_var = tk.StringVar(value="none")
        self._autotuner_prefix_auto_value: str = ""

        def _on_suggestions_mode_change(*args: Any) -> None:
            mode = self.suggestions_mode_var.get()
            if mode == "autotuner":
                self._autotuner_prefix_auto_value = "auto"
                self.label_prefix_var.set("auto")
            else:
                if self.label_prefix_var.get() == self._autotuner_prefix_auto_value:
                    self.label_prefix_var.set("")
                self._autotuner_prefix_auto_value = ""
            if hasattr(self, "execute_suggestion_selector"):
                self.execute_suggestion_selector.set_enabled(mode == "manual")

        self.suggestions_mode_var.trace_add("write", _on_suggestions_mode_change)

        rb_none = ttk.Radiobutton(
            suggestions_frame,
            text="None (apply no suggestions)",
            variable=self.suggestions_mode_var,
            value="none",
        )
        rb_none.pack(anchor=tk.W)

        rb_manual = ttk.Radiobutton(
            suggestions_frame,
            text="Apply manually selected suggestions",
            variable=self.suggestions_mode_var,
            value="manual",
            state="disabled",
        )
        rb_manual.pack(anchor=tk.W)
        self.apply_suggestions_rb = rb_manual

        suggestions_info_row = ttk.Frame(suggestions_frame)
        suggestions_info_row.pack(fill=tk.X, pady=(3, 0))

        self.suggestions_count_label = ttk.Label(
            suggestions_info_row, text="No suggestions available", foreground="gray", font=widgets.FONT_CAPTION
        )
        self.suggestions_count_label.pack(side=tk.LEFT, padx=(20, 10))

        self.browse_edit_suggestions_button = widgets.create_button(
            suggestions_info_row,
            text="Browse / Edit →",
            command=self._open_suggestion_browser,
            state="disabled",
        )
        self.browse_edit_suggestions_button.pack(side=tk.LEFT)

        self.execute_suggestion_selector = SuggestionSelector(
            suggestions_frame,
            self.arguments.dot_dp,
            "execute",
            on_change=self._update_execute_suggestion_count,
        )
        self.execute_suggestion_selector.pack(fill=tk.X, padx=(20, 5), pady=(3, 0))

        rb_autotuner = ttk.Radiobutton(
            suggestions_frame,
            text="Apply autotuner-selected suggestions",
            variable=self.suggestions_mode_var,
            value="autotuner",
            state="disabled",
        )
        rb_autotuner.pack(anchor=tk.W, pady=(5, 0))
        self.apply_autotuner_suggestions_rb = rb_autotuner

        autotuner_info_row = ttk.Frame(suggestions_frame)
        autotuner_info_row.pack(fill=tk.X, pady=(3, 0))

        self.autotuner_suggestions_info_label = ttk.Label(
            autotuner_info_row, text="No autotuner results available", foreground="gray", font=widgets.FONT_CAPTION
        )
        self.autotuner_suggestions_info_label.pack(side=tk.LEFT, padx=(20, 10))

        def on_run() -> None:
            self._run_execution()

        def on_stop() -> None:
            self._stop_execution()  # type: ignore

        def on_prepare_pattern_detection() -> None:
            self._prepare_pattern_detection()

        # Horizontal divider separating the action buttons from the settings above.
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(8, 0))

        run_button_frame = ttk.Frame(left_frame)
        run_button_frame.pack(fill=tk.X, padx=0, pady=0)

        self.run_button = widgets.primary_button(run_button_frame, text="Run", command=on_run, state="disabled")
        self.run_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.stop_execution_button = widgets.danger_button(
            run_button_frame, text="Stop", command=on_stop, state="disabled"
        )
        self.stop_execution_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.prepare_pattern_detection_button = widgets.create_button(
            run_button_frame, text="Prepare Pattern Detection", command=on_prepare_pattern_detection, state="disabled"
        )
        self.prepare_pattern_detection_button.pack(side=tk.LEFT, padx=5, pady=5)
        _prepare_tooltip = Tooltip(
            self.prepare_pattern_detection_button,
            "Runs the selected configuration in 'dp' mode with 'inplace' enabled.",
        )
        bind_tooltip_hover(self.prepare_pattern_detection_button, _prepare_tooltip, self)

        # Right panel - output
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame)

        output_frame = ttk.LabelFrame(right_frame, text="Output")
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        from discopop_library.ProjectManager.gui.widgets import create_styled_output_console

        self.output_text = create_styled_output_console(output_frame)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        def _on_output_mousewheel(event: Any) -> object:
            self.output_text.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        self.output_text.bind("<MouseWheel>", _on_output_mousewheel)
        self.output_text.bind("<Button-4>", lambda e: self.output_text.yview_scroll(-1, "units"))
        self.output_text.bind("<Button-5>", lambda e: self.output_text.yview_scroll(1, "units"))

        _bind_scroll(options_outer)
        self._refresh_suggestion_selection_display()

    def _update_execute_suggestion_count(self) -> None:
        """Update the 'N of M selected' label from the Execute-tab selector."""
        if not hasattr(self, "suggestions_count_label") or not hasattr(self, "execute_suggestion_selector"):
            return
        total = len(self.execute_suggestion_selector.get_available_ids())
        selected = len(self.execute_suggestion_selector.get_selected_ids())
        if total == 0:
            self.suggestions_count_label.config(text="No suggestions available", foreground="gray")
        else:
            fg = "black" if selected > 0 else "gray"
            self.suggestions_count_label.config(text=f"{selected} of {total} selected", foreground=fg)

    def _refresh_suggestion_selection_display(self) -> None:
        if not hasattr(self, "suggestions_count_label"):
            return

        if hasattr(self, "execute_suggestion_selector"):
            self.execute_suggestion_selector.refresh()
        total = (
            len(self.execute_suggestion_selector.get_available_ids())
            if hasattr(self, "execute_suggestion_selector")
            else 0
        )

        self._update_execute_suggestion_count()
        if total == 0:
            self.apply_suggestions_rb.config(state="disabled")
            if self.suggestions_mode_var.get() == "manual":
                self.suggestions_mode_var.set("none")
            self.browse_edit_suggestions_button.config(state="disabled")
        else:
            self.apply_suggestions_rb.config(state="normal")
            self.browse_edit_suggestions_button.config(state="normal")

        if hasattr(self, "execute_suggestion_selector"):
            self.execute_suggestion_selector.set_enabled(total > 0 and self.suggestions_mode_var.get() == "manual")

        if hasattr(self, "autotuner_suggestions_info_label"):
            results_path = os.path.join(self.arguments.dot_dp, "auto_tuner", "results.json")
            config_key = getattr(self, "current_config", None) or ""
            autotuner_ids: list[str] = []
            autotuner_executed = os.path.exists(results_path)
            if autotuner_executed and config_key:
                try:
                    with open(results_path, "r") as f:
                        results_data = json.load(f)
                    autotuner_ids = sorted(
                        [str(s) for s in results_data.get(config_key, {}).get("applied_suggestions", [])],
                        key=lambda x: int(x) if x.isdigit() else x,
                    )
                except (json.JSONDecodeError, IOError):
                    pass
            if autotuner_ids:
                self.autotuner_suggestions_info_label.config(
                    text="Suggestion IDs: " + ", ".join(autotuner_ids), foreground="black"
                )
            elif autotuner_executed and config_key:
                self.autotuner_suggestions_info_label.config(text="No suggestions selected", foreground="gray")
            else:
                self.autotuner_suggestions_info_label.config(text="Autotuner not yet executed", foreground="gray")

            if hasattr(self, "apply_autotuner_suggestions_rb"):
                if autotuner_executed and config_key:
                    self.apply_autotuner_suggestions_rb.config(state="normal")
                else:
                    self.apply_autotuner_suggestions_rb.config(state="disabled")
                    if self.suggestions_mode_var.get() == "autotuner":
                        self.suggestions_mode_var.set("none")

        if hasattr(self, "_refresh_autotuning_suggestions_display"):
            self._refresh_autotuning_suggestions_display()
