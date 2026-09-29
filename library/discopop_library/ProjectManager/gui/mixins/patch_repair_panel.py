# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Patch Repair tab: fixing suggestions whose patch does not compile.

Sits between Pattern Detection and Autotuning, which is where it belongs in the
workflow: the patches exist by then, and a suggestion that does not build is one the
tuner can only ever record as a failure.

The panel is a close sibling of the Autotuning tab -- same scrollable settings column,
same console -- with two differences that come from what the tool does. The backend and
model selectors are built from the ``llm_backends`` registry rather than hardcoded, so a
new agent reaches the GUI without touching this file; and the right-hand side shows a
results table and a patch diff instead of a plot, because a repair is judged by reading
it, not by watching a number converge.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.PatchRepairArguments import DEFAULT_HOTSPOT_TYPES
from discopop_library.PatchRepair.results import PROGRESS_PREFIX
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.mixins.helpers import Tooltip, clean_ansi_output, show_error
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.plots.data import split_progress_events
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.gui.widgets import (
    apply_diff_highlighting,
    caption_label,
    create_code_view,
    create_styled_output_console,
    heading_label,
)

logger_name = "PatchRepairPanel"

# The settings column is built at 650px; captions wrap a little inside that so an
# explanation is never clipped at the pane edge, where it reads as a truncated sentence.
CAPTION_WRAP = 600
# ...and an indented caption has to wrap earlier still, by more than its own indent: a
# label whose natural width lands just under the wrap length is laid out on one line and
# then clipped by the indent, which looks exactly like the bug the wrapping prevents.
INDENTED_CAPTION_WRAP = 540

# Status values as results.json records them, with the text and colour the table shows.
STATUS_DISPLAY = {
    "repaired": ("Repaired", widgets.STATUS_OK),
    "ok": ("Compiles", widgets.STATUS_IDLE),
    "failed": ("Not repaired", widgets.STATUS_FAIL),
    "not_applied": ("Patch not applicable", widgets.STATUS_FAIL),
    # Its own row rather than a failure: no model ever judged this suggestion, so the
    # run says nothing about whether it could have been repaired.
    "agent_unreachable": ("Agent unreachable", widgets.STATUS_STOP),
    "skipped": ("Skipped", widgets.STATUS_IDLE),
}


class PatchRepairPanelMixin(ConfigManagerMixinBase):
    patch_repair_running = False
    patch_repair_output_text: Optional[scrolledtext.ScrolledText] = None
    patch_repair_run_button: Optional[RoundedButton] = None
    patch_repair_stop_button: Optional[RoundedButton] = None
    patch_repair_config_label: Optional[ttk.Label] = None
    patch_repair_hotspot_types_vars: Optional[Dict[str, tk.BooleanVar]] = None
    patch_repair_backend_var: Optional[tk.StringVar] = None
    patch_repair_model_var: Optional[tk.StringVar] = None
    patch_repair_model_combo: Optional[ttk.Combobox] = None
    patch_repair_prompts_var: Optional[tk.StringVar] = None
    patch_repair_retries_var: Optional[tk.StringVar] = None
    patch_repair_timeout_var: Optional[tk.StringVar] = None
    patch_repair_dry_run_var: Optional[tk.BooleanVar] = None
    patch_repair_log_level_var: Optional[tk.StringVar] = None
    patch_repair_budget_label: Optional[ttk.Label] = None
    patch_repair_backend_hint: Optional[ttk.Label] = None
    patch_repair_summary_label: Optional[ttk.Label] = None
    patch_repair_tree: Optional[ttk.Treeview] = None
    patch_repair_diff_original: Optional[tk.Text] = None
    patch_repair_diff_repaired: Optional[tk.Text] = None
    patch_repair_file_var: Optional[tk.StringVar] = None
    patch_repair_file_combo: Optional[ttk.Combobox] = None
    patch_repair_diff_source_label: Optional[ttk.Label] = None
    patch_repair_selector: Optional[SuggestionSelector] = None
    _patch_repair_process: Optional["subprocess.Popen[str]"] = None
    # results.json as it currently stands, keyed by suggestion id (as a string).
    _patch_repair_records: Dict[str, Dict[str, Any]] = {}

    # -- construction ------------------------------------------------------------

    def _build_patch_repair_panel(self, parent: tk.Widget) -> None:
        main_paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, minsize=650, width=650)

        options_outer, bind_scroll = self._build_scrollable_column(left_frame)

        self._build_patch_repair_settings(options_outer)
        self._build_patch_repair_agent_settings(options_outer)
        self._build_patch_repair_scope(options_outer)

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(8, 0))

        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, padx=0, pady=0)
        self.patch_repair_run_button = widgets.primary_button(
            button_frame, text="Run Patch Repair", command=self._run_patch_repair, state="disabled"
        )
        self.patch_repair_run_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.patch_repair_stop_button = widgets.danger_button(
            button_frame, text="Stop", command=self._stop_patch_repair, state="disabled"
        )
        self.patch_repair_stop_button.pack(side=tk.LEFT, padx=5, pady=5)

        summary_frame = ttk.LabelFrame(left_frame, text="Outcome", padding=5)
        summary_frame.pack(fill=tk.X, padx=5, pady=5)
        self.patch_repair_summary_label = caption_label(
            summary_frame, "(not run yet)", justify=tk.LEFT, wraplength=CAPTION_WRAP
        )
        self.patch_repair_summary_label.pack(anchor=tk.W)

        self._build_patch_repair_results(main_paned)

        bind_scroll(options_outer)
        self._update_patch_repair_ui()
        self._load_patch_repair_results_from_file()
        # no results.json yet means the table stayed empty and nothing rendered the
        # diff panes, which would leave them blank rather than saying why
        self._show_patch_repair_diff()

    def _build_scrollable_column(self, parent: tk.Widget) -> "tuple[ttk.Frame, Callable[[tk.Widget], None]]":
        """The scrollable settings column shared with the Autotuning tab."""
        scroll_container = ttk.Frame(parent)
        scroll_container.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(scroll_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas = tk.Canvas(scroll_container, highlightthickness=0, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=canvas.yview)

        options_outer = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=options_outer, anchor=tk.NW)

        options_outer.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))

        def on_mousewheel(event: Any) -> object:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def bind_scroll(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", on_mousewheel)
            widget.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
            for child in widget.winfo_children():
                bind_scroll(child)  # type: ignore[arg-type]

        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        return options_outer, bind_scroll

    def _build_patch_repair_settings(self, parent: tk.Widget) -> None:
        settings_frame = ttk.LabelFrame(parent, text="Settings", padding=5)
        settings_frame.pack(fill=tk.X, padx=5, pady=5)

        config_row = ttk.Frame(settings_frame)
        config_row.pack(fill=tk.X, pady=3)
        heading_label(config_row, "Configuration:").pack(side=tk.LEFT, padx=5)
        self.patch_repair_config_label = caption_label(config_row, "(none selected)")
        self.patch_repair_config_label.pack(side=tk.LEFT, padx=5)

        hotspot_frame = ttk.Frame(settings_frame)
        hotspot_frame.pack(fill=tk.X, pady=5)
        heading_label(hotspot_frame, "Hotspot Types:").pack(anchor=tk.W, padx=5)
        row = ttk.Frame(hotspot_frame)
        row.pack(fill=tk.X)
        # NO is unchecked by default: a cold suggestion contributes negligibly to the
        # runtime, so repairing it spends agent tokens and build time on code that will
        # never be worth parallelizing.
        default_types = [t.strip() for t in DEFAULT_HOTSPOT_TYPES.split(",")]
        self.patch_repair_hotspot_types_vars = {}
        for htype in ["yes", "maybe", "no"]:
            var = tk.BooleanVar(value=htype in default_types)
            self.patch_repair_hotspot_types_vars[htype] = var
            ttk.Checkbutton(row, text=htype.upper(), variable=var).pack(side=tk.LEFT, padx=20)
        caption_label(
            hotspot_frame,
            "NO suggestions are skipped by default to save time and agent cost. "
            "Without hotspot results every suggestion counts as YES.",
            wraplength=CAPTION_WRAP,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=5)

        loglevel_frame = ttk.Frame(settings_frame)
        loglevel_frame.pack(fill=tk.X, pady=5)
        ttk.Label(loglevel_frame, text="Log Level:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.patch_repair_log_level_var = tk.StringVar(value="INFO")
        ttk.Combobox(
            loglevel_frame,
            textvariable=self.patch_repair_log_level_var,
            values=widgets.LOG_LEVEL_VALUES,
            state="readonly",
            width=10,
        ).pack(side=tk.LEFT, padx=5)

        self.patch_repair_dry_run_var = tk.BooleanVar(value=False)
        dry_run_frame = ttk.Frame(settings_frame)
        dry_run_frame.pack(fill=tk.X, pady=5)
        ttk.Checkbutton(
            dry_run_frame, text="Dry run (do not modify the patches)", variable=self.patch_repair_dry_run_var
        ).pack(anchor=tk.W, padx=5)
        caption_label(
            dry_run_frame,
            "A repair is still built to check it, so a patch file is written and put back; "
            "it ends the run exactly as it started.",
            wraplength=INDENTED_CAPTION_WRAP,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=25)

    def _build_patch_repair_agent_settings(self, parent: tk.Widget) -> None:
        agent_frame = ttk.LabelFrame(parent, text="LLM Agent", padding=5)
        agent_frame.pack(fill=tk.X, padx=5, pady=5)

        backend_row = ttk.Frame(agent_frame)
        backend_row.pack(fill=tk.X, pady=3)
        ttk.Label(backend_row, text="Backend:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        # Built from the registry, so a newly added agent reaches the GUI without a
        # change here.
        backends = llm_backends.available_backends()
        installed = llm_backends.first_installed_backend()
        self.patch_repair_backend_var = tk.StringVar(value=installed or (backends[0] if backends else ""))
        backend_combo = ttk.Combobox(
            backend_row, textvariable=self.patch_repair_backend_var, values=backends, state="readonly", width=16
        )
        backend_combo.pack(side=tk.LEFT, padx=5)
        backend_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_patch_repair_backend_changed())

        self.patch_repair_backend_hint = caption_label(agent_frame, "", wraplength=CAPTION_WRAP, justify=tk.LEFT)
        self.patch_repair_backend_hint.pack(anchor=tk.W, padx=5)

        model_row = ttk.Frame(agent_frame)
        model_row.pack(fill=tk.X, pady=3)
        ttk.Label(model_row, text="Model:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.patch_repair_model_var = tk.StringVar(value="")
        # Editable, not read-only: a backend's model list depends on which providers are
        # authenticated and is not always exhaustive, so a model missing from it must
        # still be typeable.
        self.patch_repair_model_combo = ttk.Combobox(model_row, textvariable=self.patch_repair_model_var, width=42)
        self.patch_repair_model_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        caption_label(agent_frame, "Leave empty to use the backend's own default model.").pack(anchor=tk.W, padx=5)

        timeout_row = ttk.Frame(agent_frame)
        timeout_row.pack(fill=tk.X, pady=3)
        ttk.Label(timeout_row, text="Agent timeout (s):", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.patch_repair_timeout_var = tk.StringVar(value="300")
        ttk.Spinbox(
            timeout_row, from_=10, to=3600, increment=10, textvariable=self.patch_repair_timeout_var, width=8
        ).pack(side=tk.LEFT, padx=5)

        budget_frame = ttk.Frame(agent_frame)
        budget_frame.pack(fill=tk.X, pady=3)
        ttk.Label(budget_frame, text="Prompts:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.patch_repair_prompts_var = tk.StringVar(value="2")
        ttk.Spinbox(
            budget_frame,
            from_=1,
            to=10,
            textvariable=self.patch_repair_prompts_var,
            width=5,
            command=self._update_patch_repair_budget,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Label(budget_frame, text="Retries:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=(15, 5))
        self.patch_repair_retries_var = tk.StringVar(value="2")
        ttk.Spinbox(
            budget_frame,
            from_=0,
            to=10,
            textvariable=self.patch_repair_retries_var,
            width=5,
            command=self._update_patch_repair_budget,
        ).pack(side=tk.LEFT, padx=5)

        self.patch_repair_budget_label = caption_label(agent_frame, "")
        self.patch_repair_budget_label.pack(anchor=tk.W, padx=5)
        caption_label(
            agent_frame,
            "A prompt is an independent attempt with a fresh context; a retry is a "
            "follow-up turn in the same conversation, told what was wrong.",
            wraplength=CAPTION_WRAP,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=5)

        self._on_patch_repair_backend_changed()
        self._update_patch_repair_budget()

    def _build_patch_repair_scope(self, parent: tk.Widget) -> None:
        scope_frame = ttk.LabelFrame(parent, text="Suggestion Scope", padding=5)
        scope_frame.pack(fill=tk.X, padx=5, pady=5)
        caption_label(scope_frame, "Suggestions to consider (the hotspot filter applies on top):").pack(
            anchor=tk.W, padx=5
        )
        self.patch_repair_selector = SuggestionSelector(
            scope_frame,
            self.arguments.dot_dp,
            "patch_repair_scope",
        )
        self.patch_repair_selector.pack(fill=tk.X, padx=5)

    def _build_patch_repair_results(self, parent: tk.PanedWindow) -> None:
        right_frame = ttk.Frame(parent)
        parent.add(right_frame)

        notebook = ttk.Notebook(right_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        results_tab = ttk.Frame(notebook)
        notebook.add(results_tab, text="📋 Results")
        columns = ("suggestion", "hotspot", "status", "files", "attempts", "error")
        tree = ttk.Treeview(results_tab, columns=columns, show="headings", selectmode="browse")
        for column, heading, width, stretch in (
            ("suggestion", "Suggestion", 80, False),
            ("hotspot", "Hotspot", 60, False),
            ("status", "Status", 120, False),
            ("files", "Files", 60, False),
            ("attempts", "Attempts", 65, False),
            # The first error is the widest and least essential column: it takes
            # whatever room is left, and the full text is in the console and in
            # results.json rather than only here.
            ("error", "First error", 240, True),
        ):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor=tk.W, stretch=stretch)
        tree_scroll = ttk.Scrollbar(results_tab, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree_hscroll = ttk.Scrollbar(results_tab, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=tree_hscroll.set)
        tree_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.bind("<<TreeviewSelect>>", lambda _e: self._on_patch_repair_row_selected())
        self.patch_repair_tree = tree

        diff_tab = ttk.Frame(notebook)
        notebook.add(diff_tab, text="🔀 Patch")
        file_row = ttk.Frame(diff_tab)
        file_row.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(file_row, text="File:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        # A suggestion's patch set can hold several files, and a repair may have changed
        # only some of them, so which file is being shown has to be selectable.
        self.patch_repair_file_var = tk.StringVar(value="")
        self.patch_repair_file_combo = ttk.Combobox(
            file_row, textvariable=self.patch_repair_file_var, state="readonly", width=30
        )
        self.patch_repair_file_combo.pack(side=tk.LEFT, padx=5)
        self.patch_repair_file_combo.bind("<<ComboboxSelected>>", lambda _e: self._show_patch_repair_diff())
        # Which suggestion is shown here is the one selected in the Results tab; without
        # saying so, an empty pane reads as "there is nothing to show".
        self.patch_repair_diff_source_label = caption_label(file_row, "")
        self.patch_repair_diff_source_label.pack(side=tk.LEFT, padx=10)

        # Stacked rather than side by side: what a repair changes is almost always the
        # pragma, which is the longest line in the patch. Two half-width panes push it
        # off both their right edges, so the one thing worth comparing is the one thing
        # that needs horizontal scrolling to see.
        panes = tk.PanedWindow(diff_tab, orient=tk.VERTICAL, sashrelief=tk.RAISED)
        panes.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # stretch="always" on both panes: without it the first child takes its requested
        # height and the second is pushed past the edge, so the side the repair produced
        # -- the one worth reading -- would be invisible until the sash is dragged.
        # create_code_view rather than the log console the rest of the panel uses: a
        # diff must not be word-wrapped (a wrapped line's continuation looks like a
        # context line) and is worth colouring, which that viewer already does.
        original_frame = ttk.Frame(panes)
        panes.add(original_frame, stretch="always", height=260)
        heading_label(original_frame, "Generated patch (before repair)").pack(anchor=tk.W)
        self.patch_repair_diff_original = create_code_view(original_frame)
        repaired_frame = ttk.Frame(panes)
        panes.add(repaired_frame, stretch="always", height=260)
        heading_label(repaired_frame, "Patch in use (after repair)").pack(anchor=tk.W)
        self.patch_repair_diff_repaired = create_code_view(repaired_frame)

        console_tab = ttk.Frame(notebook)
        notebook.add(console_tab, text="🖥 Console")
        self.patch_repair_output_text = create_styled_output_console(console_tab)
        self.patch_repair_output_text.pack(fill=tk.BOTH, expand=True)

    # -- state -------------------------------------------------------------------

    def _on_patch_repair_backend_changed(self) -> None:
        """Refresh the model list and say so when the selected agent is not installed."""
        if self.patch_repair_backend_var is None or self.patch_repair_backend_hint is None:
            return
        name = self.patch_repair_backend_var.get()
        try:
            module = llm_backends.get(name)
        except KeyError:
            self.patch_repair_backend_hint.config(text="Unknown backend: " + name, foreground=widgets.STATUS_FAIL)
            return

        if not module.available():
            self.patch_repair_backend_hint.config(
                text=str(getattr(module, "INSTALL_HINT", "")) or (name + " could not be run."),
                foreground=widgets.STATUS_FAIL,
            )
            if self.patch_repair_model_combo is not None:
                self.patch_repair_model_combo["values"] = []
            return

        version = module.version() or ""
        self.patch_repair_backend_hint.config(
            text=(version + " -- " if version else "") + str(getattr(module, "DESCRIPTION", "")).split("\n")[0],
            foreground=widgets.STATUS_IDLE,
        )
        if self.patch_repair_model_combo is not None:
            # Listing models runs the agent's own command, which can take a moment; a
            # failure leaves the list empty and the field still typeable.
            self.patch_repair_model_combo["values"] = module.list_models()

    def _update_patch_repair_budget(self) -> None:
        """Show what the current dials cost, since that is what they are for."""
        if self.patch_repair_budget_label is None:
            return
        prompts = _as_int(self.patch_repair_prompts_var, 2)
        retries = _as_int(self.patch_repair_retries_var, 2)
        total = prompts * (1 + retries)
        self.patch_repair_budget_label.config(
            text="At most "
            + str(prompts)
            + " x (1 + "
            + str(retries)
            + ") = "
            + str(total)
            + " agent calls per suggestion.",
            foreground=widgets.STATUS_IDLE,
        )

    def _update_patch_repair_config_display(self) -> None:
        if getattr(self, "patch_repair_config_label", None) is None:
            return
        assert self.patch_repair_config_label is not None
        # The panel is built before the configuration list has selected anything, so
        # current_config does not exist yet on the first call.
        config = getattr(self, "current_config", None)
        if config:
            self.patch_repair_config_label.config(text=config, foreground="black")
        else:
            self.patch_repair_config_label.config(text="(none selected)", foreground="gray")

    def _update_patch_repair_ui(self) -> None:
        """Enable the run button only once there are patches to repair."""
        self._update_patch_repair_config_display()
        if self.patch_repair_run_button is None:
            return
        ready = self._patch_repair_prerequisites_met()
        if self.patch_repair_running:
            return
        self.patch_repair_run_button.config(state="normal" if ready else "disabled")
        if self.patch_repair_selector is not None:
            self.patch_repair_selector.refresh()

    def _patch_repair_prerequisites_met(self) -> bool:
        """Patches must exist: without them there is nothing to build and nothing to fix."""
        patch_generator_dir = os.path.join(self.arguments.dot_dp, "patch_generator")
        if not os.path.isdir(patch_generator_dir):
            return False
        has_patches = any(entry.isdigit() for entry in os.listdir(patch_generator_dir))
        return has_patches and bool(getattr(self, "current_config", None))

    # -- running -----------------------------------------------------------------

    def _run_patch_repair(self) -> None:
        if self.patch_repair_running:
            show_error(self, "Already Running", "Patch repair is already running.")
            return
        if not getattr(self, "current_config", None):
            show_error(self, "No Configuration Selected", "Please select a configuration first.")
            return

        self.patch_repair_running = True
        if self.patch_repair_run_button is not None:
            self.patch_repair_run_button.config(state="disabled", text="⟳ Running...")
        if self.patch_repair_stop_button is not None:
            self.patch_repair_stop_button.config(state="normal")
        self.status_label.config(text="⏳ Patch repair in progress...", foreground=widgets.STATUS_BUSY)

        if self.patch_repair_output_text is not None:
            self.patch_repair_output_text.config(state=tk.NORMAL)
            self.patch_repair_output_text.delete("1.0", tk.END)
            self.patch_repair_output_text.config(state="disabled")
        self._patch_repair_records = {}
        self._refresh_patch_repair_table()

        def append_output(text: str) -> None:
            if self.patch_repair_output_text is not None:
                self.patch_repair_output_text.config(state=tk.NORMAL)
                self.patch_repair_output_text.insert(tk.END, text)
                self.patch_repair_output_text.see(tk.END)
                self.patch_repair_output_text.config(state="disabled")

        def thread_safe_append(text: str) -> None:
            self.after(0, lambda: append_output(text))  # type: ignore

        def thread_func() -> None:
            try:
                thread_safe_append("Starting patch repair...\n")
                self._invoke_patch_repair(thread_safe_append)
                self.after(0, lambda: self._on_patch_repair_complete())  # type: ignore
            except Exception as error:
                message = str(error)
                thread_safe_append("\nError: " + message + "\n")
                self.after(0, lambda: self._on_patch_repair_complete(error=True))  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

    def _invoke_patch_repair(self, output_callback: Callable[[str], None]) -> None:
        assert self.patch_repair_hotspot_types_vars is not None

        dot_discopop = self.arguments.dot_dp
        selected_types = [name for name, var in self.patch_repair_hotspot_types_vars.items() if var.get()]
        hotspot_types = ",".join(selected_types) if selected_types else DEFAULT_HOTSPOT_TYPES

        command = [
            sys.executable,
            "-m",
            "discopop_library.PatchRepair",
            "--dot-dp-path",
            dot_discopop,
            "-c",
            self.current_config or "tiny",
            "-ht",
            hotspot_types,
            "--prompts",
            str(_as_int(self.patch_repair_prompts_var, 2)),
            "--retries",
            str(_as_int(self.patch_repair_retries_var, 2)),
            "--agent-timeout",
            str(_as_int(self.patch_repair_timeout_var, 300)),
            "--log",
            self.patch_repair_log_level_var.get() if self.patch_repair_log_level_var is not None else "INFO",
        ]
        if self.patch_repair_backend_var is not None and self.patch_repair_backend_var.get():
            command += ["--backend", self.patch_repair_backend_var.get()]
        if self.patch_repair_model_var is not None and self.patch_repair_model_var.get().strip():
            command += ["--model", self.patch_repair_model_var.get().strip()]
        if self.patch_repair_dry_run_var is not None and self.patch_repair_dry_run_var.get():
            command.append("--dry-run")
        if self.patch_repair_selector is not None and not self.patch_repair_selector.is_all_selected():
            selected = self.patch_repair_selector.get_selected_ids()
            command += ["-s", ",".join(selected)]
            output_callback("Restricting to suggestion IDs: " + (", ".join(selected) or "(none)") + "\n")

        output_callback("Configuration:\n")
        output_callback("  Configuration: " + str(self.current_config) + "\n")
        output_callback("  Hotspot Types: " + hotspot_types + "\n")
        output_callback(
            "  Backend: "
            + (self.patch_repair_backend_var.get() if self.patch_repair_backend_var is not None else "")
            + "\n"
        )
        output_callback(
            "  Model: "
            + ((self.patch_repair_model_var.get() if self.patch_repair_model_var is not None else "") or "(default)")
            + "\n\n"
        )

        # A subprocess, never in-process: the tool drives the autotuner and an external
        # agent, and its console output would otherwise fight the Tk main loop.
        self._patch_repair_process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=dot_discopop,
        )
        assert self._patch_repair_process.stdout is not None
        for line in self._patch_repair_process.stdout:
            events, residual = split_progress_events(line, PROGRESS_PREFIX)
            for event in events:
                self.after(0, lambda e=event: self._on_patch_repair_progress(e))  # type: ignore
            cleaned = clean_ansi_output(residual.rstrip("\n"))
            if cleaned:
                output_callback(cleaned + "\n")
        self._patch_repair_process.wait()

        returncode = self._patch_repair_process.returncode
        self._patch_repair_process = None
        if returncode != 0:
            raise RuntimeError("Patch repair exited with return code " + str(returncode))
        output_callback("\nPatch repair completed.\n")

    def _on_patch_repair_progress(self, event: Dict[str, Any]) -> None:
        """Update the table and the summary from one structured progress event."""
        kind = str(event.get("event") or "")
        if kind == "suggestion":
            suggestion_id = str(event.get("suggestion_id"))
            self._patch_repair_records[suggestion_id] = dict(event)
            self._refresh_patch_repair_table()
        elif kind == "discovery":
            failing = event.get("failing") or []
            built = event.get("built") or []
            self._set_patch_repair_summary(
                str(len(built)) + " compile, " + str(len(failing)) + " do not — repairing " + str(len(failing)) + "...",
                widgets.STATUS_BUSY,
            )
            if not event.get("reference_built", True):
                self._set_patch_repair_summary(
                    "The project does not build without any suggestion applied. Fix the build first.",
                    widgets.STATUS_FAIL,
                )
        elif kind == "done":
            repaired = int(event.get("repaired") or 0)
            failed = int(event.get("failed") or 0)
            colour = widgets.STATUS_OK if repaired and not failed else widgets.STATUS_IDLE
            if failed and not repaired:
                colour = widgets.STATUS_FAIL
            self._set_patch_repair_summary(
                str(repaired)
                + " repaired, "
                + str(failed)
                + " not repaired, "
                + str(event.get("considered") or 0)
                + " considered.",
                colour,
            )

    def _stop_patch_repair(self) -> None:
        if self._patch_repair_process is not None:
            # SIGINT rather than terminate(): the tool finishes the suggestion it is on
            # and writes results.json, instead of leaving a half-written patch behind.
            self._patch_repair_process.send_signal(signal.SIGINT)
        if self.patch_repair_stop_button is not None:
            self.patch_repair_stop_button.config(state="disabled")
        self.status_label.config(text="Stopping patch repair...", foreground=widgets.STATUS_STOP)

    def _on_patch_repair_complete(self, error: bool = False) -> None:
        self.patch_repair_running = False
        # results.json is the authoritative record: rebuild from it so the table is
        # complete even if a live event was missed.
        self._load_patch_repair_results_from_file()

        if self.patch_repair_run_button is not None:
            self.patch_repair_run_button.config(state="normal", text="Run Patch Repair")
        if self.patch_repair_stop_button is not None:
            self.patch_repair_stop_button.config(state="disabled")

        if error:
            self.status_label.config(text="Patch repair failed", foreground=widgets.STATUS_FAIL)
            self.after(4000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore
            return

        repaired = sum(1 for r in self._patch_repair_records.values() if r.get("status") == "repaired")
        if repaired:
            self.status_label.config(
                text="Patch repair completed - " + str(repaired) + " patch set(s) repaired",
                foreground=widgets.STATUS_OK,
            )
        else:
            self.status_label.config(text="Patch repair completed", foreground=widgets.STATUS_IDLE)
        self.after(6000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore

        # a repaired patch changes what the tuner and the report show
        for refresh in ("_refresh_autotuning_suggestions_display", "_update_report_display"):
            if hasattr(self, refresh):
                getattr(self, refresh)()

    # -- results display ---------------------------------------------------------

    def _load_patch_repair_results_from_file(self) -> None:
        path = os.path.join(self.arguments.dot_dp, "patch_repair", "results.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                document = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        suggestions = document.get("suggestions")
        if isinstance(suggestions, dict):
            self._patch_repair_records = {str(k): dict(v) for k, v in suggestions.items()}
            self._refresh_patch_repair_table()

    def _refresh_patch_repair_table(self) -> None:
        tree = self.patch_repair_tree
        if tree is None:
            return
        previous = tree.selection()
        for row in tree.get_children():
            tree.delete(row)
        for suggestion_id in sorted(self._patch_repair_records, key=_as_sort_key):
            record = self._patch_repair_records[suggestion_id]
            status = str(record.get("status") or "")
            label, _colour = STATUS_DISPLAY.get(status, (status or "unknown", widgets.STATUS_IDLE))
            changed = record.get("changed_files") or []
            files = record.get("files") or []
            tree.insert(
                "",
                tk.END,
                iid=suggestion_id,
                values=(
                    suggestion_id,
                    str(record.get("hotspot_type") or ""),
                    label,
                    (str(len(changed)) + " / " + str(len(files))) if files else "-",
                    str(record.get("attempts") or 0),
                    str(record.get("first_error") or ""),
                ),
                tags=(status,),
            )
        for status, (_label, colour) in STATUS_DISPLAY.items():
            tree.tag_configure(status, foreground=colour)
        self._select_default_patch_repair_row(previous)

    def _select_default_patch_repair_row(self, previous: "tuple[str, ...]") -> None:
        """Keep the selected row across a refresh, or open on the most interesting one.

        The Patch tab renders whichever suggestion is selected here, so an unselected
        table leaves that tab blank -- and rebuilding the table on every progress event
        would otherwise drop the selection the user just made.
        """
        tree = self.patch_repair_tree
        if tree is None:
            return
        rows = tree.get_children()
        if not rows:
            self._on_patch_repair_row_selected()
            return
        for row in previous:
            if row in rows:
                tree.selection_set(row)
                tree.see(row)
                self._on_patch_repair_row_selected()
                return
        # a repaired patch is what the run was for, so show one if there is one
        preferred = next(
            (r for r in rows if str(self._patch_repair_records.get(r, {}).get("status")) == "repaired"), rows[0]
        )
        tree.selection_set(preferred)
        tree.see(preferred)
        self._on_patch_repair_row_selected()

    def _patch_files_on_disk(self, suggestion_id: str) -> List[str]:
        """File ids of the patches stored for a suggestion.

        A suggestion that already compiled, or whose patches never applied, is recorded
        without a file list, because no repair ever loaded its patch set. Its patches are
        on disk nonetheless, and are still the thing worth reading.
        """
        directory = os.path.join(self.arguments.dot_dp, "patch_generator", suggestion_id)
        try:
            entries = os.listdir(directory)
        except OSError:
            return []
        return sorted((e[: -len(".patch")] for e in entries if e.endswith(".patch")), key=_as_sort_key)

    def _on_patch_repair_row_selected(self) -> None:
        tree = self.patch_repair_tree
        if tree is None or self.patch_repair_file_combo is None or self.patch_repair_file_var is None:
            return
        selection = tree.selection()
        if not selection:
            self.patch_repair_file_combo["values"] = []
            self.patch_repair_file_var.set("")
            self._show_patch_repair_diff()
            return
        record = self._patch_repair_records.get(selection[0], {})
        files = [str(f) for f in (record.get("files") or [])]
        if not files:
            files = self._patch_files_on_disk(selection[0])
        changed = {str(f) for f in (record.get("changed_files") or [])}
        # Mark the files a repair actually rewrote, so a multi-file set does not have to
        # be inspected file by file to find the one that changed.
        labels = [("file " + f + (" (changed)" if f in changed else "")) for f in files]
        self.patch_repair_file_combo["values"] = labels
        if labels:
            preferred = next((label for label in labels if "(changed)" in label), labels[0])
            self.patch_repair_file_var.set(preferred)
        else:
            self.patch_repair_file_var.set("")
        self._show_patch_repair_diff()

    def _show_patch_repair_diff(self) -> None:
        tree = self.patch_repair_tree
        if tree is None or self.patch_repair_diff_original is None or self.patch_repair_diff_repaired is None:
            return
        selection = tree.selection()
        if not selection:
            message = (
                "(select a suggestion in the Results tab)"
                if self._patch_repair_records
                else "(no results yet: run patch repair)"
            )
            self._set_patch_repair_diff_source("")
            _fill_console(self.patch_repair_diff_original, message)
            _fill_console(self.patch_repair_diff_repaired, message)
            return
        suggestion_id = selection[0]
        self._set_patch_repair_diff_source("Suggestion " + suggestion_id)
        file_label = self.patch_repair_file_var.get() if self.patch_repair_file_var is not None else ""
        file_id = file_label.replace("file ", "").replace(" (changed)", "").strip()
        if not file_id:
            message = "(no patch files found for suggestion " + suggestion_id + ")"
            _fill_console(self.patch_repair_diff_original, message)
            _fill_console(self.patch_repair_diff_repaired, message)
            return

        dot_dp = self.arguments.dot_dp
        # The backup holds the patch as the generator produced it; it exists only for a
        # suggestion a repair actually touched.
        backup = os.path.join(dot_dp, "patch_repair", "backups", suggestion_id, file_id + ".patch")
        current = os.path.join(dot_dp, "patch_generator", suggestion_id, file_id + ".patch")
        _fill_console(self.patch_repair_diff_original, _read_or(backup, "(no backup: this patch was never modified)"))
        _fill_console(self.patch_repair_diff_repaired, _read_or(current, "(no patch found)"))

    def _set_patch_repair_diff_source(self, text: str) -> None:
        if self.patch_repair_diff_source_label is not None:
            self.patch_repair_diff_source_label.config(text=text)

    def _set_patch_repair_summary(self, text: str, colour: str) -> None:
        if self.patch_repair_summary_label is not None:
            self.patch_repair_summary_label.config(text=text, foreground=colour)


def _as_int(var: Optional[tk.StringVar], default: int) -> int:
    if var is None:
        return default
    try:
        return int(str(var.get()).strip())
    except (TypeError, ValueError):
        return default


def _as_sort_key(suggestion_id: str) -> "tuple[int, str]":
    """Numeric order where possible, so 10 does not sort before 2."""
    try:
        return (int(suggestion_id), "")
    except ValueError:
        return (1 << 30, suggestion_id)


def _read_or(path: str, fallback: str) -> str:
    try:
        with open(path, "r", newline="") as f:
            return f.read()
    except OSError:
        return fallback


def _fill_console(console: tk.Text, text: str) -> None:
    console.config(state=tk.NORMAL)
    console.delete("1.0", tk.END)
    console.insert(tk.END, text)
    console.config(state="disabled")
    apply_diff_highlighting(console)
