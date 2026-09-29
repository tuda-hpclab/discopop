# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Hotspot Detection tab: run measurements and present the analysis.

Accumulating runs is the whole point of the tab: ``ratio`` measures how a region's
runtime varies with the input, and each configuration's ``execute.sh`` is its own
input, so a single run leaves ``ratio`` at exactly ``0.5`` everywhere and hotness
degenerates to "above-average runtime". Measuring several configurations is
therefore what makes the analysis meaningful -- and configurations generally differ
in their ``compile.sh``, so this must work across instrumented builds.

Raw region ids cannot carry that across builds. ``HotspotDetection.cpp`` appends to
``cs_id.txt`` and resumes numbering from ``temp.txt``, so a second compile gives the
same source region a second id, and the runtime -- which sizes its output by
counting ``cs_id.txt``'s lines -- writes ``0.0`` for every region belonging to a
build other than its own. Handing that directly to the analyzer, which joins purely
by id, is what destroys the YES/MAYBE/NO distinction: ``roundMin`` turns those zeros
into ``1e-6`` and ``ratio`` collapses to ~1.0 for everything.

So ids are never used to combine anything. Each run's measurements are resolved to
build-independent :class:`~...hotspot_data.RegionKey`\\ s (source path, line, kind,
name) as soon as it completes and stored that way in the sidecar; before analysis
all accumulated runs are renumbered into one canonical id space
(:func:`~...hotspot_data.write_merged_analysis_input`) in which a region absent from
a run is *omitted* rather than zeroed, so the analyzer averages it over the runs
where it actually exists. Nothing is discarded on recompile; clearing is manual.
"""

from __future__ import annotations

import copy
import datetime
import functools
import logging
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import replace
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.detail_bar import DetailBar
from discopop_library.ProjectManager.gui.mixins.helpers import (
    ask_yes_no,
    clean_ansi_output,
    show_error,
    show_warning,
)
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.plots import demangle, embedding, hotspot_charts, hotspot_data
from discopop_library.ProjectManager.gui.plots.hotspot_data import (
    HOTNESS_MAYBE,
    HOTNESS_NO,
    HOTNESS_ORDER,
    HOTNESS_YES,
    KIND_FUNCTION,
    KIND_LOOP,
    HotspotRegion,
    MeasurementLog,
    MeasurementRun,
)
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.gui.widgets import caption_label, create_styled_output_console, heading_label

logger = logging.getLogger("HotspotPanel")

HOTSPOT_ANALYZER = "discopop_hotspot_analyzer"

# Chart types offered by the "+" tab: default state plus a title stem.
_PLOT_TYPES: Dict[str, Dict[str, Any]] = {
    "quadrant": {"label": "Hotness quadrant", "stem": "Quadrant"},
    "bars": {"label": "Top-N runtime bars", "stem": "Bars"},
    "profile": {"label": "Per-region run profile", "stem": "Profile"},
}
_ADD_TAB_TEXT = "  ＋  "
_DETAIL_BAR_WIDTH = 300
_DETAIL_PLACEHOLDER = "Click a code region in a\nchart or the table to see\nits details here."

# Build states, as reported by _hotspot_build_state.
BUILD_NONE = "none"
BUILD_CURRENT = "current"
BUILD_STALE = "stale"
BUILD_MISMATCH = "mismatch"

# Source extensions considered when deciding whether a build went stale.
_SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx")
# Directories never worth walking for source mtimes.
_PRUNED_DIRS = {".git", ".discopop", "build", "venv", "__pycache__", "node_modules", ".mypy_cache"}

_REGION_COLUMNS: Tuple[Tuple[str, int], ...] = (
    ("Hotness", 90),
    ("Kind", 80),
    ("Location", 200),
    ("Name", 160),
    ("Avg (s)", 95),
    ("Share", 75),
    ("Min (s)", 95),
    ("Max (s)", 95),
    ("Ratio", 70),
    ("Runs", 60),
)

_RUN_COLUMNS: Tuple[Tuple[str, int], ...] = (
    ("Run", 55),
    ("Configuration", 170),
    ("Recorded at", 160),
    ("Time (s)", 90),
    ("Status", 90),
    ("Regions", 80),
)


class HotspotPanelMixin(ConfigManagerMixinBase):
    hotspot_running = False
    hotspot_output_text: Optional[scrolledtext.ScrolledText] = None
    hotspot_run_button: Optional[RoundedButton] = None
    hotspot_stop_button: Optional[RoundedButton] = None
    hotspot_reinstrument_button: Optional[RoundedButton] = None
    hotspot_analyze_button: Optional[RoundedButton] = None
    hotspot_clear_button: Optional[RoundedButton] = None
    hotspot_config_label: Optional[ttk.Label] = None
    hotspot_build_label: Optional[ttk.Label] = None
    hotspot_runs_label: Optional[ttk.Label] = None
    hotspot_hotness_label: Optional[ttk.Label] = None
    hotspot_warning_label: Optional[ttk.Label] = None
    hotspot_repetitions_var: Optional[tk.IntVar] = None
    hotspot_notebook: Optional[ttk.Notebook] = None
    hotspot_regions_tree: Optional[ttk.Treeview] = None
    hotspot_runs_tree: Optional[ttk.Treeview] = None
    hotspot_kind_filter_var: Optional[tk.StringVar] = None
    hotspot_hotness_filter_vars: Optional[Dict[str, tk.BooleanVar]] = None
    _hotspot_regions: Optional[List[HotspotRegion]] = None
    _hotspot_runs: Optional[List[MeasurementRun]] = None
    _hotspot_regions_detail: Optional[DetailBar] = None
    _hotspot_regions_selection: Optional[HotspotRegion] = None
    _hotspot_regions_sort: Optional[Tuple[str, bool]] = None
    _hotspot_plot_tabs: Optional[Dict[str, Dict[str, Any]]] = None
    _hotspot_add_tab: Optional[tk.Widget] = None
    _hotspot_prev_tab: Optional[str] = None
    _hotspot_plot_counter: int = 0
    _hotspot_process: Optional["subprocess.Popen[bytes]"] = None
    _hotspot_analysis_process: Optional["subprocess.Popen[str]"] = None
    _hotspot_stop_event: Optional[threading.Event] = None

    # ── construction ───────────────────────────────────────────────────────────

    def _build_hotspot_panel(self, parent: tk.Widget) -> None:
        self._hotspot_stop_event = threading.Event()
        self._hotspot_plot_tabs = {}
        self.hotspot_notebook = ttk.Notebook(parent)
        self.hotspot_notebook.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        measurement_tab = ttk.Frame(self.hotspot_notebook)
        self.hotspot_notebook.add(measurement_tab, text="Measurement")
        self._build_hotspot_measurement_tab(measurement_tab)

        runs_tab = ttk.Frame(self.hotspot_notebook)
        self.hotspot_notebook.add(runs_tab, text="Runs")
        self._build_hotspot_runs_tab(runs_tab)

        regions_tab = ttk.Frame(self.hotspot_notebook)
        self.hotspot_notebook.add(regions_tab, text="Regions")
        self._build_hotspot_regions_tab(regions_tab)

        self._hotspot_add_tab = ttk.Frame(self.hotspot_notebook)
        self.hotspot_notebook.add(self._hotspot_add_tab, text=_ADD_TAB_TEXT)
        self.hotspot_notebook.bind("<<NotebookTabChanged>>", self._on_hotspot_tab_changed)

        # Open with the quadrant chart shown, mirroring the Report tab opening on
        # a trade-off scatter.
        self._add_hotspot_plot("quadrant")
        self.hotspot_notebook.select(0)
        self._refresh_hotspot_results()

    def _build_hotspot_measurement_tab(self, parent: tk.Widget) -> None:
        main_paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, minsize=650, width=650)

        settings_frame = ttk.LabelFrame(left_frame, text="Measurement", padding=5)
        settings_frame.pack(fill=tk.X, padx=5, pady=5)

        config_row = ttk.Frame(settings_frame)
        config_row.pack(fill=tk.X, pady=3)
        heading_label(config_row, "Configuration:").pack(side=tk.LEFT, padx=5)
        self.hotspot_config_label = caption_label(config_row, "(none selected)")
        self.hotspot_config_label.pack(side=tk.LEFT, padx=5)

        repetitions_row = ttk.Frame(settings_frame)
        repetitions_row.pack(fill=tk.X, pady=3)
        ttk.Label(repetitions_row, text="Repetitions:", width=14, anchor=tk.W).pack(side=tk.LEFT, padx=5)
        self.hotspot_repetitions_var = tk.IntVar(value=1)
        ttk.Spinbox(
            repetitions_row, from_=1, to=20, textvariable=self.hotspot_repetitions_var, width=6, state="readonly"
        ).pack(side=tk.LEFT)

        caption_label(
            settings_frame,
            "Hotness combines two criteria: average runtime, and how strongly a region's runtime\n"
            "varies across runs (ratio). Repeating one configuration only narrows measurement\n"
            "noise -- to make the ratio meaningful, measure several configurations, i.e. several\n"
            "inputs. Timeouts are taken from the Execute tab.",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=10, pady=(0, 4))

        status_frame = ttk.LabelFrame(left_frame, text="Status", padding=5)
        status_frame.pack(fill=tk.X, padx=5, pady=5)

        self.hotspot_build_label = ttk.Label(status_frame, text="", font=widgets.FONT_BODY)
        self.hotspot_build_label.pack(anchor=tk.W, padx=5)
        self.hotspot_runs_label = ttk.Label(status_frame, text="", font=widgets.FONT_BODY)
        self.hotspot_runs_label.pack(anchor=tk.W, padx=5)
        self.hotspot_hotness_label = ttk.Label(status_frame, text="", font=widgets.FONT_BODY)
        self.hotspot_hotness_label.pack(anchor=tk.W, padx=5)
        self.hotspot_warning_label = ttk.Label(
            status_frame, text="", font=widgets.FONT_BODY, foreground=widgets.STATUS_STOP, justify=tk.LEFT
        )

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(8, 0))

        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, padx=0, pady=0)
        self.hotspot_run_button = widgets.primary_button(
            button_frame, text="Run Measurement", command=self._run_hotspot_measurement, state="disabled"
        )
        self.hotspot_run_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.hotspot_stop_button = widgets.danger_button(
            button_frame, text="Stop", command=self._stop_hotspot_measurement, state="disabled"
        )
        self.hotspot_stop_button.pack(side=tk.LEFT, padx=5, pady=5)

        button_frame_row2 = ttk.Frame(left_frame)
        button_frame_row2.pack(fill=tk.X, padx=0, pady=0)
        self.hotspot_reinstrument_button = widgets.create_button(
            button_frame_row2, text="Re-instrument", command=self._reinstrument_hotspots, state="disabled"
        )
        self.hotspot_reinstrument_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.hotspot_analyze_button = widgets.create_button(
            button_frame_row2, text="Re-run Analysis", command=self._rerun_hotspot_analysis, state="disabled"
        )
        self.hotspot_analyze_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.hotspot_clear_button = widgets.danger_button(
            button_frame_row2, text="Clear Measurements", command=self._clear_hotspot_measurements, state="disabled"
        )
        self.hotspot_clear_button.pack(side=tk.LEFT, padx=5, pady=5)

        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame)
        output_frame = ttk.LabelFrame(right_frame, text="Output")
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.hotspot_output_text = create_styled_output_console(output_frame)
        self.hotspot_output_text.pack(fill=tk.BOTH, expand=True)

    def _build_hotspot_runs_tab(self, parent: tk.Widget) -> None:
        caption_label(
            parent,
            "Each run is one execution of the instrumented binary. Runs recorded outside this tab\n"
            "(Execute tab in 'hd' mode, CLI, MCP server) show as (external).",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=10, pady=(8, 4))

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.hotspot_runs_tree = self._build_tree(tree_frame, _RUN_COLUMNS)

    def _build_hotspot_regions_tab(self, parent: tk.Widget) -> None:
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 2))

        ttk.Label(filter_frame, text="Hotness:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=(0, 4))
        self.hotspot_hotness_filter_vars = {}
        for hotness in HOTNESS_ORDER:
            var = tk.BooleanVar(value=True)
            self.hotspot_hotness_filter_vars[hotness] = var
            ttk.Checkbutton(filter_frame, text=hotness, variable=var, command=self._populate_hotspot_regions_tree).pack(
                side=tk.LEFT, padx=2
            )

        ttk.Label(filter_frame, text="Kind:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=(14, 4))
        self.hotspot_kind_filter_var = tk.StringVar(value="all")
        kind_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.hotspot_kind_filter_var,
            values=["all", KIND_LOOP, KIND_FUNCTION],
            state="readonly",
            width=10,
        )
        kind_combo.pack(side=tk.LEFT)
        kind_combo.bind("<<ComboboxSelected>>", lambda _e: self._populate_hotspot_regions_tree())

        content = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(content)
        self.hotspot_regions_tree = self._build_tree(tree_frame, _REGION_COLUMNS, sortable=True)
        self.hotspot_regions_tree.bind("<<TreeviewSelect>>", self._on_hotspot_region_row_selected)
        content.add(tree_frame, stretch="always")

        detail = self._make_hotspot_detail_bar(content, lambda: self._hotspot_regions_selection)
        self._hotspot_regions_detail = detail
        content.add(detail, minsize=160, width=_DETAIL_BAR_WIDTH, stretch="never")

    def _build_tree(
        self, parent: tk.Widget, columns: Sequence[Tuple[str, int]], sortable: bool = False
    ) -> ttk.Treeview:
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(parent, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        names = [name for name, _width in columns]
        tree = ttk.Treeview(parent, columns=names, show="headings", yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        for name, width in columns:
            if sortable:
                tree.heading(name, text=name, command=functools.partial(self._sort_hotspot_regions_by, name))
            else:
                tree.heading(name, text=name)
            tree.column(name, width=width, anchor="w", stretch=True)

        tree.tag_configure("evenrow", background=widgets.TREE_EVEN_ROW)
        tree.tag_configure("oddrow", background=widgets.TREE_ODD_ROW)
        tree.tag_configure(HOTNESS_YES, foreground=hotspot_charts.hotness_color(HOTNESS_YES))
        tree.tag_configure(HOTNESS_MAYBE, foreground=hotspot_charts.hotness_color(HOTNESS_MAYBE))
        tree.tag_configure(HOTNESS_NO, foreground=hotspot_charts.hotness_color(HOTNESS_NO))
        tree.tag_configure("failed", foreground=widgets.STATUS_FAIL)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)

        tree.bind("<MouseWheel>", lambda e: tree.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        tree.bind("<Button-4>", lambda e: tree.yview_scroll(-1, "units"))
        tree.bind("<Button-5>", lambda e: tree.yview_scroll(1, "units"))
        return tree

    def _make_hotspot_detail_bar(self, parent: tk.Widget, current: Callable[[], Optional[HotspotRegion]]) -> DetailBar:
        """A detail bar plus a "show in VSCode" action bound to ``current()``."""
        detail = DetailBar(parent, placeholder=_DETAIL_PLACEHOLDER)
        detail.add_action(
            "Show in VSCode",
            lambda: self._open_hotspot_region_in_vscode(current()),
            enabled=lambda: current() is not None,
        )
        return detail

    # ── the "+" tab and chart tabs ─────────────────────────────────────────────

    def _on_hotspot_tab_changed(self, _event: Any) -> None:
        """When the trailing '+' tab is selected, open the menu and bounce back."""
        assert self.hotspot_notebook is not None
        current = self.hotspot_notebook.select()
        add_tab_id = str(self._hotspot_add_tab) if self._hotspot_add_tab is not None else None
        if current == add_tab_id:
            if self._hotspot_prev_tab and self._hotspot_prev_tab in self.hotspot_notebook.tabs():
                self.hotspot_notebook.select(self._hotspot_prev_tab)
            else:
                self.hotspot_notebook.select(0)
            self._open_add_hotspot_plot_menu()
        else:
            self._hotspot_prev_tab = current

    def _open_add_hotspot_plot_menu(self) -> None:
        assert self.hotspot_notebook is not None
        menu = tk.Menu(self.hotspot_notebook, tearoff=0)
        for key, meta in _PLOT_TYPES.items():
            menu.add_command(label=str(meta["label"]), command=functools.partial(self._add_hotspot_plot, key))
        try:
            menu.tk_popup(self.hotspot_notebook.winfo_pointerx(), self.hotspot_notebook.winfo_pointery())
        finally:
            menu.grab_release()

    def _add_hotspot_plot(self, plot_type: str) -> None:
        assert self.hotspot_notebook is not None and self._hotspot_plot_tabs is not None
        self._hotspot_plot_counter += 1
        title = f"{_PLOT_TYPES[plot_type]['stem']} {self._hotspot_plot_counter}"

        tab = ttk.Frame(self.hotspot_notebook)
        insert_index = self.hotspot_notebook.index(str(self._hotspot_add_tab))
        self.hotspot_notebook.insert(insert_index, tab, text=title)

        state: Dict[str, Any] = {"type": plot_type, "controls": {}, "selection": None}

        strip = ttk.Frame(tab)
        strip.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)

        content = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        plot_frame = ttk.Frame(content)
        figure, canvas, _ = embedding.create_canvas(plot_frame)
        state["figure"] = figure
        state["canvas"] = canvas
        state["plot_frame"] = plot_frame
        content.add(plot_frame, stretch="always")

        detail = self._make_hotspot_detail_bar(content, lambda: state["selection"])
        state["detail"] = detail
        content.add(detail, minsize=160, width=_DETAIL_BAR_WIDTH, stretch="never")

        # Built after `state` exists so the controls can render into it.
        self._build_hotspot_plot_controls(strip, tab, state)

        self._hotspot_plot_tabs[str(tab)] = state
        self.hotspot_notebook.select(tab)
        self._render_hotspot_plot_tab(state)

    def _build_hotspot_plot_controls(self, strip: tk.Widget, tab: tk.Widget, state: Dict[str, Any]) -> None:
        plot_type = state["type"]

        if plot_type == "bars":
            ttk.Label(strip, text="Show top:").pack(side=tk.LEFT, padx=(14, 6))
            var = tk.StringVar(value=str(hotspot_charts.DEFAULT_TOP_N))
            combo = ttk.Combobox(
                strip, textvariable=var, values=list(hotspot_charts.TOP_N_CHOICES), state="readonly", width=6
            )
            combo.pack(side=tk.LEFT, padx=(0, 6))
            combo.bind("<<ComboboxSelected>>", lambda _e: self._render_hotspot_plot_tab(state))
            state["controls"]["top_n"] = var
        elif plot_type == "profile":
            # Selection is per-tab (as on the Report tab), so this chart carries its
            # own region picker rather than following another tab's selection.
            ttk.Label(strip, text="Region:").pack(side=tk.LEFT, padx=(14, 6))
            var = tk.StringVar(value="")
            combo = ttk.Combobox(strip, textvariable=var, values=[], state="readonly", width=44)
            combo.pack(side=tk.LEFT, padx=(0, 6))
            combo.bind("<<ComboboxSelected>>", lambda _e: self._render_hotspot_plot_tab(state))
            state["controls"]["region"] = var
            state["region_combo"] = combo

        widgets.danger_button(strip, text="✕", command=lambda: self._close_hotspot_plot(tab)).pack(
            side=tk.RIGHT, padx=4
        )

    def _close_hotspot_plot(self, tab: tk.Widget) -> None:
        assert self.hotspot_notebook is not None and self._hotspot_plot_tabs is not None
        self._hotspot_plot_tabs.pop(str(tab), None)
        self.hotspot_notebook.forget(tab)
        self.hotspot_notebook.select(0)

    def _render_hotspot_plot_tab(self, state: Dict[str, Any]) -> None:
        regions = self._hotspot_regions or []
        figure = state["figure"]
        plot_type = state["type"]
        on_select = functools.partial(self._on_hotspot_plot_region_selected, state)

        if plot_type == "quadrant":
            hotspot_charts.render_quadrant(figure, regions, on_select=on_select)
        elif plot_type == "bars":
            try:
                top_n = int(state["controls"]["top_n"].get())
            except (KeyError, ValueError):
                top_n = hotspot_charts.DEFAULT_TOP_N
            hotspot_charts.render_top_bars(figure, regions, top_n=top_n, on_select=on_select)
        elif plot_type == "profile":
            hotspot_charts.render_run_profile(figure, self._resolve_profile_region(state), on_select=on_select)

        embedding.redraw(state["canvas"])
        if state.get("plot_frame") is not None:
            embedding.force_resize_redraw(state["plot_frame"])

    def _resolve_profile_region(self, state: Dict[str, Any]) -> Optional[HotspotRegion]:
        """The region the profile tab's picker selects, defaulting to the hottest."""
        regions = self._hotspot_regions or []
        if not regions:
            return None
        combo = state.get("region_combo")
        var = state["controls"].get("region")
        if combo is None or var is None:
            return regions[0]

        labels = [self._region_choice_label(region) for region in regions]
        if list(combo.cget("values")) != labels:
            combo.config(values=labels)
        if var.get() not in labels:
            # regions are sorted hottest-first, so this picks the hottest
            var.set(labels[0])
        return regions[labels.index(var.get())]

    def _region_choice_label(self, region: HotspotRegion) -> str:
        name = f"  {hotspot_charts.region_display_name(region)}" if region.key.name else ""
        return f"{region.key.location}{name}  ({region.avg:.4f}s, {region.hotness})"

    # ── selection ──────────────────────────────────────────────────────────────

    def _on_hotspot_plot_region_selected(self, state: Dict[str, Any], region: HotspotRegion) -> None:
        state["selection"] = region
        state["detail"].show_fields(self._region_detail_fields(region))

    def _on_hotspot_region_row_selected(self, _event: Any) -> None:
        if self.hotspot_regions_tree is None or self._hotspot_regions_detail is None:
            return
        selection = self.hotspot_regions_tree.selection()
        regions = self._hotspot_regions or []
        if not selection:
            return
        serialized = self.hotspot_regions_tree.item(selection[0], "tags")
        # the region's serialized key is stashed as the last tag
        key = serialized[-1] if serialized else ""
        match = next((region for region in regions if region.key.serialize() == key), None)
        self._hotspot_regions_selection = match
        if match is None:
            self._hotspot_regions_detail.show_placeholder()
        else:
            self._hotspot_regions_detail.show_fields(self._region_detail_fields(match))

    def _region_detail_fields(self, region: HotspotRegion) -> List[Tuple[str, str]]:
        runtimes = ", ".join(f"{value:.6f}" for value in region.runtimes) or "(none recorded)"
        fields = [
            ("Kind", region.key.kind),
            ("Name", hotspot_charts.region_display_name(region) if region.key.name else "(unnamed loop)"),
            ("File", region.key.path),
            ("Line", str(region.key.line)),
            ("Hotness", region.hotness),
            ("Average runtime", f"{region.avg:.6f} s"),
            ("Share of total", f"{region.share * 100:.2f} %"),
            ("Min / max", f"{region.minimum:.6f} s / {region.maximum:.6f} s"),
            ("Ratio", f"{region.ratio:.4f}"),
            ("Runs measured", str(len(region.runtimes))),
            ("Runtime per run", runtimes),
        ]
        if len(region.runtimes) < 2:
            fields.append(("Note", "Only one run: the ratio is fixed at 0.5 and carries no information."))
        return fields

    def _open_hotspot_region_in_vscode(self, region: Optional[HotspotRegion]) -> None:
        if region is None:
            return
        code_executable = shutil.which("code")
        if code_executable is None:
            show_error(
                self,
                "VSCode Not Found",
                "Could not find the 'code' command on your PATH.\n\n"
                "Install Visual Studio Code and, from within VSCode, run "
                "'Shell Command: Install \"code\" command in PATH' to enable this feature.",
            )
            return
        if not os.path.exists(region.key.path):
            show_warning(
                self,
                "File Not Found",
                f"The recorded source path no longer exists:\n{region.key.path}",
            )
            return
        try:
            subprocess.Popen(
                [code_executable, "--goto", f"{region.key.path}:{region.key.line}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")

    # ── data loading and display ───────────────────────────────────────────────

    def _load_hotspot_region_keys(self, *, merged: bool = False) -> Dict[int, hotspot_data.RegionKey]:
        """Resolve region ids to source locations.

        Two id spaces exist and must not be confused. ``private/cs_id.txt`` is the
        profiler's, in which the raw ``hotspot_result_<N>.txt`` files are written;
        ``merged/cs_id.txt`` is the canonical one spanning all builds, in which
        ``Hotspots.json`` is expressed. Pass ``merged=True`` for the latter.
        """
        dot_dp = self.arguments.dot_dp
        path = hotspot_data.merged_cs_id_path(dot_dp) if merged else hotspot_data.cs_id_path(dot_dp)
        cs_id_text = self._read_text(path)
        if cs_id_text is None:
            return {}
        file_mapping_text = self._read_text(os.path.join(dot_dp, "FileMapping.txt")) or ""
        return hotspot_data.resolve_keys(
            hotspot_data.parse_cs_id(cs_id_text),
            hotspot_data.parse_file_mapping(file_mapping_text),
        )

    def _read_text(self, path: str) -> Optional[str]:
        try:
            with open(path, "r") as f:
                return f.read()
        except OSError:
            return None

    def _load_hotspot_log(self) -> MeasurementLog:
        data = hotspot_data.load_json_file(hotspot_data.sidecar_path(self.arguments.dot_dp))
        return hotspot_data.deserialize_log(data) if data is not None else MeasurementLog()

    def _save_hotspot_log(self, log: MeasurementLog) -> None:
        import json

        path = hotspot_data.sidecar_path(self.arguments.dot_dp)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(hotspot_data.serialize_log(log), f, indent=4, sort_keys=True)
        except OSError as e:
            logger.warning("could not write the hotspot measurement log: %s", e)

    def _refresh_hotspot_results(self) -> None:
        """Reload Hotspots.json and the run log, then refresh every view."""
        dot_dp = self.arguments.dot_dp
        keys = self._load_hotspot_region_keys(merged=True)
        hotspots = hotspot_data.load_json_file(hotspot_data.hotspots_json_path(dot_dp))
        self._hotspot_regions = hotspot_data.parse_hotspots_json(hotspots, keys) if hotspots is not None else []
        # one batched demangler call, rather than one per rendered row
        demangle.prefetch(region.key.name for region in self._hotspot_regions if region.key.name)

        log = self._load_hotspot_log()
        indices = hotspot_data.result_file_indices(hotspot_data.private_dir(dot_dp))
        self._hotspot_runs = hotspot_data.merge_external_runs(log, indices)

        # A selection from a previous analysis may no longer exist.
        self._hotspot_regions_selection = None
        if self._hotspot_regions_detail is not None:
            self._hotspot_regions_detail.show_placeholder()

        self._populate_hotspot_regions_tree()
        self._populate_hotspot_runs_tree()
        for state in list((self._hotspot_plot_tabs or {}).values()):
            state["selection"] = None
            state["detail"].show_placeholder()
            self._render_hotspot_plot_tab(state)
        self._update_hotspot_ui()
        # Results appearing (or being cleared) flips the "no hotspot results" hint in the
        # Pattern Detection tab. That panel is built after this one, so the very first
        # refresh happens before its widgets exist.
        self._update_hotspot_hint()

    def _sort_hotspot_regions_by(self, column: str) -> None:
        current = self._hotspot_regions_sort
        descending = not (current is not None and current[0] == column and current[1])
        self._hotspot_regions_sort = (column, descending)
        self._populate_hotspot_regions_tree()

    def _visible_hotspot_regions(self) -> List[HotspotRegion]:
        regions = list(self._hotspot_regions or [])
        if self.hotspot_hotness_filter_vars is not None:
            allowed = {hotness for hotness, var in self.hotspot_hotness_filter_vars.items() if var.get()}
            regions = [region for region in regions if region.hotness in allowed]
        if self.hotspot_kind_filter_var is not None and self.hotspot_kind_filter_var.get() != "all":
            kind = self.hotspot_kind_filter_var.get()
            regions = [region for region in regions if region.key.kind == kind]

        if self._hotspot_regions_sort is not None:
            column, descending = self._hotspot_regions_sort
            keys: Dict[str, Callable[[HotspotRegion], Any]] = {
                "Hotness": lambda r: (
                    HOTNESS_ORDER.index(r.hotness) if r.hotness in HOTNESS_ORDER else len(HOTNESS_ORDER)
                ),
                "Kind": lambda r: r.key.kind,
                "Location": lambda r: (r.key.path, r.key.line),
                "Name": lambda r: r.key.name.lower(),
                "Avg (s)": lambda r: r.avg,
                "Share": lambda r: r.share,
                "Min (s)": lambda r: r.minimum,
                "Max (s)": lambda r: r.maximum,
                "Ratio": lambda r: r.ratio,
                "Runs": lambda r: len(r.runtimes),
            }
            key_func = keys.get(column)
            if key_func is not None:
                regions.sort(key=key_func, reverse=descending)
        return regions

    def _populate_hotspot_regions_tree(self) -> None:
        tree = self.hotspot_regions_tree
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)

        for index, region in enumerate(self._visible_hotspot_regions()):
            tags = [
                "evenrow" if index % 2 == 0 else "oddrow",
                region.hotness,
                # the serialized key travels as the final tag so a row click can
                # recover its region without a parallel index
                region.key.serialize(),
            ]
            tree.insert(
                "",
                "end",
                values=(
                    f"● {region.hotness}",
                    region.key.kind,
                    region.key.location,
                    hotspot_charts.region_display_name(region) if region.key.name else "-",
                    f"{region.avg:.6f}",
                    f"{region.share * 100:.2f} %",
                    f"{region.minimum:.6f}",
                    f"{region.maximum:.6f}",
                    f"{region.ratio:.4f}",
                    str(len(region.runtimes)),
                ),
                tags=tuple(tags),
            )

    def _populate_hotspot_runs_tree(self) -> None:
        tree = self.hotspot_runs_tree
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)

        for index, run in enumerate(self._hotspot_runs or []):
            tags = ["evenrow" if index % 2 == 0 else "oddrow"]
            if run.code not in (None, 0):
                tags.append("failed")
            if run.code is None:
                status = "—"
            elif run.code == 0:
                status = "✓ ok"
            else:
                status = f"✗ code {run.code}"
            tree.insert(
                "",
                "end",
                values=(
                    str(run.index),
                    run.config if run.config is not None else "(external)",
                    run.timestamp or "—",
                    "—" if run.time is None else f"{run.time:.3f}",
                    status,
                    str(len(run.regions)) if run.regions else "—",
                ),
                tags=tuple(tags),
            )

    # ── prerequisites and button states ────────────────────────────────────────

    def _hotspot_current_config(self) -> Optional[str]:
        """The selected configuration, tolerating the panel being built first.

        ``ConfigManagerApp`` assigns ``current_config`` only after it has built the
        tabs, so the initial refresh runs before the attribute exists.
        """
        return getattr(self, "current_config", None)

    def _current_region_fingerprint(self) -> Optional[str]:
        keys = self._load_hotspot_region_keys()
        return hotspot_data.region_fingerprint(keys.values()) if keys else None

    def _newest_source_mtime(self) -> Optional[float]:
        """Newest mtime among the project's C/C++ sources, or ``None`` if none found."""
        newest: Optional[float] = None
        for root, dirnames, filenames in os.walk(self.arguments.project_root):
            dirnames[:] = [d for d in dirnames if d not in _PRUNED_DIRS and not d.startswith(".")]
            for filename in filenames:
                if not filename.endswith(_SOURCE_SUFFIXES):
                    continue
                try:
                    mtime = os.path.getmtime(os.path.join(root, filename))
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
        return newest

    def _hotspot_compile_script_differs(self) -> bool:
        """Whether the selected configuration needs its own instrumented build."""
        current_config = self._hotspot_current_config()
        log = self._load_hotspot_log()
        if not current_config or not log.compile_script:
            return False
        expected = resolve_compile_script_path(self.arguments.project_config_dir, current_config)
        return os.path.abspath(expected) != os.path.abspath(log.compile_script)

    def _hotspot_build_state(self) -> Tuple[str, str]:
        """Whether the current build can serve another run directly, and why not.

        A non-current state only means a recompile is needed first; it no longer
        implies losing anything, since runs from separate builds are combined by
        source location. ``BUILD_MISMATCH`` is the one case that warrants a
        warning: the region set changed under the accumulated runs, which for a
        source edit means their line numbers may no longer refer to the same code.
        """
        dot_dp = self.arguments.dot_dp
        cs_id = hotspot_data.cs_id_path(dot_dp)
        if not os.path.exists(cs_id):
            return (BUILD_NONE, "No instrumented build yet.")

        try:
            build_mtime = os.path.getmtime(cs_id)
        except OSError:
            return (BUILD_NONE, "No instrumented build yet.")
        newest_source = self._newest_source_mtime()
        if newest_source is not None and newest_source > build_mtime:
            return (
                BUILD_MISMATCH,
                "Sources changed since the instrumented build was made.",
            )

        if self._hotspot_compile_script_differs():
            return (
                BUILD_STALE,
                "This configuration uses a different compile.sh, so it will be instrumented separately.",
            )
        return (BUILD_CURRENT, "")

    def _update_hotspot_ui(self) -> None:
        if self.hotspot_config_label is None:
            return

        current_config = self._hotspot_current_config()
        if current_config:
            self.hotspot_config_label.config(text=current_config, foreground="black")
        else:
            self.hotspot_config_label.config(text="(none selected)", foreground="gray")

        state, detail = self._hotspot_build_state()
        runs = self._hotspot_runs or []
        regions = self._hotspot_regions or []

        build_text = {
            BUILD_CURRENT: "Instrumented build: current",
            BUILD_NONE: "Instrumented build: none (will be compiled)",
            BUILD_STALE: "Instrumented build: this configuration will be instrumented separately",
            BUILD_MISMATCH: "Instrumented build: stale (will be recompiled)",
        }[state]
        build_color = widgets.STATUS_OK if state == BUILD_CURRENT else widgets.STATUS_STOP
        if self.hotspot_build_label is not None:
            self.hotspot_build_label.config(text=build_text, foreground=build_color)

        if self.hotspot_runs_label is not None:
            external = sum(1 for run in runs if run.is_external)
            suffix = f" ({external} external)" if external else ""
            self.hotspot_runs_label.config(text=f"Accumulated runs: {len(runs)}{suffix}", foreground="black")

        if self.hotspot_hotness_label is not None:
            if regions:
                counts = hotspot_data.hotness_counts(regions)
                text = (
                    f"Code regions: {len(regions)}   "
                    f"YES {counts[HOTNESS_YES]} / MAYBE {counts[HOTNESS_MAYBE]} / NO {counts[HOTNESS_NO]}"
                )
            else:
                text = "Code regions: no analysis results yet"
            self.hotspot_hotness_label.config(text=text, foreground="black" if regions else "gray")

        if self.hotspot_warning_label is not None:
            warnings: List[str] = []
            if state == BUILD_MISMATCH and runs:
                warnings.append(
                    f"⚠ {detail}\n  The {len(runs)} recorded run(s) are kept, but regions that moved are\n"
                    "  matched by source line and may no longer line up. Use 'Clear Measurements'\n"
                    "  to start over if the sources changed substantially."
                )
            if len(runs) == 1:
                warnings.append(
                    "⚠ Only one run accumulated: every ratio is 0.5, so hotness reduces to\n"
                    "  'above-average runtime'. Measure another configuration to fix this."
                )
            if warnings:
                self.hotspot_warning_label.config(text="\n".join(warnings))
                self.hotspot_warning_label.pack(anchor=tk.W, padx=5, pady=(4, 0))
            else:
                self.hotspot_warning_label.pack_forget()

        idle = not self.hotspot_running
        has_config = bool(current_config)
        if self.hotspot_run_button is not None:
            self.hotspot_run_button.config(state="normal" if idle and has_config else "disabled")
        if self.hotspot_reinstrument_button is not None:
            self.hotspot_reinstrument_button.config(state="normal" if idle and has_config else "disabled")
        if self.hotspot_analyze_button is not None:
            self.hotspot_analyze_button.config(state="normal" if idle and runs else "disabled")
        if self.hotspot_clear_button is not None:
            has_data = os.path.isdir(hotspot_data.hotspot_dir(self.arguments.dot_dp))
            self.hotspot_clear_button.config(state="normal" if idle and has_data else "disabled")

    def _update_hotspot_config_display(self) -> None:
        """Refresh the parts of the tab that depend on the selected configuration."""
        self._update_hotspot_ui()

    # ── running measurements ───────────────────────────────────────────────────

    def _hotspot_emit(self, text: str) -> None:
        """Append to the output console; safe to call from a worker thread."""

        def append() -> None:
            if self.hotspot_output_text is None:
                return
            self.hotspot_output_text.config(state=tk.NORMAL)
            self.hotspot_output_text.insert(tk.END, text)
            self.hotspot_output_text.see(tk.END)
            self.hotspot_output_text.config(state="disabled")

        self.after(0, append)  # type: ignore

    def _clear_hotspot_output(self) -> None:
        if self.hotspot_output_text is None:
            return
        self.hotspot_output_text.config(state=tk.NORMAL)
        self.hotspot_output_text.delete("1.0", tk.END)
        self.hotspot_output_text.config(state="disabled")

    def _run_hotspot_measurement(self) -> None:
        self._start_hotspot_work(execute_runs=True)

    def _reinstrument_hotspots(self) -> None:
        self._start_hotspot_work(execute_runs=False, force_compile=True)

    def _start_hotspot_work(self, *, execute_runs: bool, force_compile: bool = False) -> None:
        if self.hotspot_running:
            show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        if not self.current_config:
            show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return

        state, _detail = self._hotspot_build_state()
        needs_compile = force_compile or state != BUILD_CURRENT

        repetitions = 1
        if execute_runs and self.hotspot_repetitions_var is not None:
            try:
                repetitions = max(1, self.hotspot_repetitions_var.get())
            except (tk.TclError, ValueError):
                repetitions = 1

        assert self._hotspot_stop_event is not None
        self._hotspot_stop_event.clear()
        self.hotspot_running = True
        self._update_hotspot_ui()
        if self.hotspot_run_button is not None:
            self.hotspot_run_button.config(state="disabled", text="⟳ Running...")
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="normal")
        self._clear_hotspot_output()
        self.status_label.config(text="⏳ Hotspot measurement in progress...", foreground=widgets.STATUS_BUSY)

        config_name = self.current_config
        config_path = os.path.join(self.config_dir, config_name)
        compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, config_name)
        settings_path = os.path.join(self.arguments.project_config_dir, "hd_settings.json")

        args_copy = copy.copy(self.arguments)
        args_copy.execute_inplace = True
        args_copy.skip_cleanup = False
        args_copy.label_prefix = ""
        args_copy.apply_suggestions = None
        args_copy.log_level = "INFO"
        args_copy.timeout_execution = self.timeout_execution_var.get()
        args_copy.timeout_compilation = self.timeout_compilation_var.get()
        args_copy.timeout_validation = self.timeout_validation_var.get()

        def thread_func() -> None:
            success = False
            try:
                success = self._hotspot_worker(
                    config_name=config_name,
                    config_path=config_path,
                    compile_sh=compile_sh,
                    settings_path=settings_path,
                    args_copy=args_copy,
                    needs_compile=needs_compile,
                    repetitions=repetitions if execute_runs else 0,
                )
            except Exception as e:  # a worker crash must not leave the UI stuck
                logger.exception("hotspot measurement failed")
                self._hotspot_emit(f"\nError: {e}\n")
            self.after(0, lambda: self._on_hotspot_work_complete(success))  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

    def _hotspot_worker(
        self,
        *,
        config_name: str,
        config_path: str,
        compile_sh: str,
        settings_path: str,
        args_copy: Any,
        needs_compile: bool,
        repetitions: int,
    ) -> bool:
        """Compile if needed, execute ``repetitions`` runs, then analyze.

        Runs on a worker thread; every UI touch goes through ``self.after``.
        """
        assert self._hotspot_stop_event is not None
        dot_dp = self.arguments.dot_dp

        if not os.path.exists(settings_path):
            self._hotspot_emit(f"hd_settings.json not found at {settings_path}\n")
            return False

        log = self._load_hotspot_log()

        if needs_compile:
            # The accumulated runs are deliberately kept. The pass appends to
            # cs_id.txt and resumes numbering from temp.txt, so the new build's
            # regions get fresh ids alongside the old ones and the runtime picks the
            # next free hotspot_result_<N>.txt -- nothing that the previous runs
            # refer to is overwritten. The analysis joins them by source location.
            if log.runs:
                self._hotspot_emit(f"Keeping the {len(log.runs)} accumulated run(s); they will be combined.\n")

            self.after(0, lambda: self.status_label.config(text="⏳ Instrumenting...", foreground=widgets.STATUS_BUSY))  # type: ignore
            self._hotspot_emit(f"Compiling '{config_name}' in 'hd' mode (inplace)...\n")
            result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                settings_path,
                compile_sh,
                1,
                args_copy.timeout_compilation,
                process_started_callback=self._register_hotspot_process,
            )
            self._hotspot_process = None
            if result is None or result[0] != 0:
                code = result[0] if result else "None"
                self._hotspot_emit(f"Instrumentation failed (return code: {code})\n")
                return False
            _code, elapsed, stdout, stderr = result
            self._hotspot_emit(f"Instrumentation succeeded ({elapsed:.2f}s)\n")
            if stdout:
                self._hotspot_emit(f"stdout: {stdout}\n")
            if stderr:
                self._hotspot_emit(f"stderr: {stderr}\n")

            fingerprint = self._current_region_fingerprint()
            if fingerprint is None:
                self._hotspot_emit(
                    "Warning: no code regions were instrumented (cs_id.txt is missing or empty).\n"
                    "Check that the configuration compiles with the hotspot detection wrappers.\n"
                )
            log.region_fingerprint = fingerprint
            log.instrumented_at = _timestamp()
            log.compile_script = os.path.abspath(compile_sh)
            self._save_hotspot_log(log)

        if self._hotspot_stop_event.is_set():
            self._hotspot_emit("Stopped by user.\n")
            return False

        keys = self._load_hotspot_region_keys()
        private = hotspot_data.private_dir(dot_dp)

        for repetition in range(repetitions):
            if self._hotspot_stop_event.is_set():
                self._hotspot_emit("Stopped by user.\n")
                return False

            label = f" ({repetition + 1}/{repetitions})" if repetitions > 1 else ""
            self.after(0, lambda: self.status_label.config(text="⏳ Measuring...", foreground=widgets.STATUS_BUSY))  # type: ignore
            self._hotspot_emit(f"\nExecuting '{config_name}'{label}...\n")

            before = set(hotspot_data.result_file_indices(private))
            result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                settings_path,
                os.path.join(config_path, "execute.sh"),
                1,
                args_copy.timeout_execution,
                process_started_callback=self._register_hotspot_process,
            )
            self._hotspot_process = None
            if result is None:
                self._hotspot_emit("Execution failed (no result)\n")
                return False
            code, elapsed, stdout, stderr = result
            if code != 0:
                self._hotspot_emit(f"Execution failed (return code: {code})\n")
                if stderr:
                    self._hotspot_emit(f"stderr: {stderr}\n")
                return False
            self._hotspot_emit(f"Execution succeeded ({elapsed:.2f}s)\n")
            if stdout:
                self._hotspot_emit(f"stdout: {stdout}\n")

            after = set(hotspot_data.result_file_indices(private))
            new_indices = sorted(after - before)
            if not new_indices:
                self._hotspot_emit(
                    "Warning: the binary ran but produced no hotspot_result_*.txt file.\n"
                    "It is probably not instrumented -- use Re-instrument.\n"
                )
                return False

            for index in new_indices:
                log.runs.append(
                    MeasurementRun(
                        index=index,
                        config=config_name,
                        timestamp=_timestamp(),
                        time=elapsed,
                        code=code,
                        regions=self._resolve_run_regions(private, index, keys),
                    )
                )
                self._hotspot_emit(f"Recorded run {index}.\n")
            self._save_hotspot_log(log)

        if self._hotspot_stop_event.is_set():
            self._hotspot_emit("Stopped by user.\n")
            return False

        return self._invoke_hotspot_analyzer()

    def _resolve_run_regions(
        self, private: str, index: int, keys: Dict[int, hotspot_data.RegionKey]
    ) -> Dict[str, float]:
        """One run's measurements, keyed by resolved region key rather than id."""
        text = self._read_text(os.path.join(private, f"hotspot_result_{index}.txt"))
        if text is None:
            return {}
        regions: Dict[str, float] = {}
        for csid, runtime in hotspot_data.parse_hotspot_result(text).items():
            key = keys.get(csid)
            # Regions that never ran dominate the file and carry no information.
            if key is not None and runtime > 0:
                regions[key.serialize()] = runtime
        return regions

    def _register_hotspot_process(self, process: "subprocess.Popen[bytes]") -> None:
        self._hotspot_process = process

    def _rerun_hotspot_analysis(self) -> None:
        if self.hotspot_running:
            show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        assert self._hotspot_stop_event is not None
        self._hotspot_stop_event.clear()
        self.hotspot_running = True
        self._update_hotspot_ui()
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="normal")
        self._clear_hotspot_output()
        self.status_label.config(text="⏳ Hotspot analysis in progress...", foreground=widgets.STATUS_BUSY)

        def thread_func() -> None:
            success = False
            try:
                success = self._invoke_hotspot_analyzer()
            except Exception as e:
                logger.exception("hotspot analysis failed")
                self._hotspot_emit(f"\nError: {e}\n")
            self.after(0, lambda: self._on_hotspot_work_complete(success))  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

    def _runs_for_analysis(self) -> List[MeasurementRun]:
        """The accumulated runs, each with its per-region measurements resolved.

        Read from the sidecar rather than from ``self._hotspot_runs``: that
        attribute mirrors the *rendered* state and is only refreshed once the
        worker finishes, so a measurement in progress would analyze the runs as
        they were before it started.

        Runs the GUI recorded itself already carry ``regions``; externally
        produced ones (Execute tab, CLI, MCP server) are resolved from their raw
        result file here so they contribute to the analysis like any other run.
        """
        dot_dp = self.arguments.dot_dp
        private = hotspot_data.private_dir(dot_dp)
        log = self._load_hotspot_log()
        keys = self._load_hotspot_region_keys()
        runs: List[MeasurementRun] = []
        for run in hotspot_data.merge_external_runs(log, hotspot_data.result_file_indices(private)):
            if not run.regions:
                run = replace(run, regions=self._resolve_run_regions(private, run.index, keys))
            if run.regions:
                runs.append(run)
        return runs

    def _invoke_hotspot_analyzer(self) -> bool:
        """Run ``discopop_hotspot_analyzer`` over the accumulated runs.

        The analyzer is not pointed at ``private/`` directly. Region ids there are
        only unique within one instrumented build, so runs from two configurations
        would be joined by ids that mean different things. Instead every
        accumulated run is renumbered into one canonical id space keyed by source
        location (:func:`hotspot_data.write_merged_analysis_input`) and the
        analyzer reads that -- which is what lets several configurations be
        combined into one hotness verdict.

        Executed as a subprocess because the analyzer chdirs into the profiling
        data directory and does not restore the working directory afterwards.
        """
        dot_dp = self.arguments.dot_dp
        private = hotspot_data.private_dir(dot_dp)

        if not os.path.isdir(private):
            self._hotspot_emit(f"\nAnalysis skipped: no profiling data found at {private}\n")
            return False
        runs = self._runs_for_analysis()
        if not runs:
            self._hotspot_emit("\nAnalysis skipped: no accumulated runs with measurements.\n")
            return False

        file_mapping = hotspot_data.parse_file_mapping(self._read_text(os.path.join(dot_dp, "FileMapping.txt")) or "")
        merged = hotspot_data.merged_dir(dot_dp)
        try:
            region_count = hotspot_data.write_merged_analysis_input(runs, file_mapping, merged)
        except OSError as e:
            self._hotspot_emit(f"\nAnalysis skipped: could not write merged analysis input: {e}\n")
            return False
        if not region_count:
            self._hotspot_emit("\nAnalysis skipped: the accumulated runs contain no known code regions.\n")
            return False
        configs = sorted({run.config for run in runs if run.config})
        self._hotspot_emit(
            f"\nMerged {len(runs)} run(s) over {region_count} code region(s)"
            + (f" from configuration(s): {', '.join(configs)}\n" if configs else "\n")
        )

        my_env = os.environ.copy()
        venv_bin = os.path.dirname(sys.executable)
        if venv_bin not in my_env.get("PATH", ""):
            my_env["PATH"] = venv_bin + os.pathsep + my_env.get("PATH", "")
        analyzer = shutil.which(HOTSPOT_ANALYZER, path=my_env["PATH"])
        if analyzer is None:
            self._hotspot_emit(f"\nAnalysis skipped: {HOTSPOT_ANALYZER} not found on PATH.\n")
            return False

        self.after(0, lambda: self.status_label.config(text="⏳ Analyzing...", foreground=widgets.STATUS_BUSY))  # type: ignore
        self._hotspot_emit(f"Running hotspot analysis over {len(runs)} accumulated run(s)...\n")

        self._hotspot_analysis_process = subprocess.Popen(
            [analyzer, "--input-dir", hotspot_data.MERGED_DIRNAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=dot_dp,
            env=my_env,
            start_new_session=True,
        )
        process = self._hotspot_analysis_process
        assert process.stdout is not None
        for line in process.stdout:
            cleaned = clean_ansi_output(line.rstrip("\n"))
            if cleaned:
                self._hotspot_emit(cleaned + "\n")
        process.wait()
        returncode = process.returncode
        self._hotspot_analysis_process = None

        if returncode != 0:
            self._hotspot_emit(f"Hotspot analysis failed (return code: {returncode})\n")
            return False
        self._hotspot_emit("Hotspot analysis complete.\n")
        return True

    def _on_hotspot_work_complete(self, success: bool) -> None:
        self.hotspot_running = False
        if self.hotspot_run_button is not None:
            self.hotspot_run_button.config(text="Run Measurement")
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="disabled")

        self._refresh_hotspot_results()
        # the analyzer's output gates the Autotuning tab's hotspot types
        if hasattr(self, "_update_autotuning_ui"):
            self._update_autotuning_ui()

        assert self._hotspot_stop_event is not None
        if self._hotspot_stop_event.is_set():
            self._set_status("Hotspot measurement stopped", fg=widgets.STATUS_STOP, reset_delay=3000)
        elif success:
            self._set_status("Hotspot measurement completed", fg=widgets.STATUS_OK, reset_delay=3000)
        else:
            self._set_status("Hotspot measurement failed", fg=widgets.STATUS_FAIL, reset_delay=3000)

    def _stop_hotspot_measurement(self) -> None:
        if self._hotspot_stop_event is not None:
            self._hotspot_stop_event.set()
        if self._hotspot_process is not None:
            try:
                self._hotspot_process.terminate()
            except OSError:
                pass
        if self._hotspot_analysis_process is not None:
            try:
                self._hotspot_analysis_process.terminate()
            except OSError:
                pass
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="disabled")
        self.status_label.config(text="Stopping hotspot measurement...", foreground=widgets.STATUS_STOP)

    # ── clearing ───────────────────────────────────────────────────────────────

    def _delete_hotspot_dir(self) -> None:
        """Remove ``.discopop/hotspot_detection/``.

        Deliberately leaves ``.discopop/FileMapping.txt`` alone: it is shared with
        the ``dp`` flow, and keeping it preserves the file ids that already-resolved
        region keys refer to.
        """
        target = hotspot_data.hotspot_dir(self.arguments.dot_dp)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)

    def _clear_hotspot_measurements(self) -> None:
        if self.hotspot_running:
            show_error(self, "Measurement Running", "Stop the running measurement first.")
            return
        run_count = len(self._hotspot_runs or [])
        if not ask_yes_no(
            self,
            "Clear Measurements",
            f"Delete the accumulated hotspot measurements ({run_count} run(s)) and the analysis results?\n\n"
            "The instrumented build stays in place, but the next measurement will re-instrument.",
        ):
            return
        self._delete_hotspot_dir()
        self._clear_hotspot_output()
        self._refresh_hotspot_results()
        self._set_status("Hotspot measurements cleared", reset_delay=3000)


def _timestamp() -> str:
    """Local wall-clock time, to the second, for the run log."""
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")
