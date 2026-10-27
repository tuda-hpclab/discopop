# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Hotspot Detection tab: run measurements and present the analysis.

The measurement flow (instrument, measure, merge the runs, analyze) is in ``services/hotspot_session.py``, the
texts and rows shown here are in ``services/hotspot_view.py``; this mixin only owns the Tk widgets.
"""

from __future__ import annotations

import functools
import logging
import os
import queue
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.services.project_state import HotspotsChanged
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession
from discopop_library.ProjectManager.services import hotspot_view
from discopop_library.ProjectManager.gui.job_adapter import TkJobAdapter
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.hotspot_build import (
    BUILD_CURRENT,
)
from discopop_library.ProjectManager.services.vscode import (
    VSCODE_NOT_FOUND_MESSAGE,
    find_code_executable,
    open_file_at,
)
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.detail_bar import DetailBar
from discopop_library.ProjectManager.gui.mixins.helpers import (
    ask_yes_no,
    show_error,
    show_warning,
)
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui import chart_embedding as embedding
from discopop_library.ProjectManager.plots import hotspot_charts, hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import (
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

# Chart types offered by the "+" tab: default state plus a title stem.
_PLOT_TYPES: Dict[str, Dict[str, Any]] = {
    "quadrant": {"label": "Hotness quadrant", "stem": "Quadrant"},
    "bars": {"label": "Top-N runtime bars", "stem": "Bars"},
    "profile": {"label": "Per-region run profile", "stem": "Profile"},
}
_ADD_TAB_TEXT = "  ＋  "
_DETAIL_BAR_WIDTH = 300
_DETAIL_PLACEHOLDER = hotspot_view.DETAIL_PLACEHOLDER

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}

_REGION_COLUMNS = hotspot_view.REGION_COLUMNS
_RUN_COLUMNS = hotspot_view.RUN_COLUMNS


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
    _hotspot_job: Optional[WorkRunner] = None

    # ── construction ───────────────────────────────────────────────────────────

    def _build_hotspot_panel(self, parent: tk.Widget) -> None:
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
        return hotspot_view.region_choice_label(region)

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
        return hotspot_view.region_detail_fields(region)

    def _open_hotspot_region_in_vscode(self, region: Optional[HotspotRegion]) -> None:
        if region is None:
            return
        code_executable = find_code_executable()
        if code_executable is None:
            show_error(self, "VSCode Not Found", VSCODE_NOT_FOUND_MESSAGE)
            return
        if not os.path.exists(region.key.path):
            show_warning(
                self,
                "File Not Found",
                f"The recorded source path no longer exists:\n{region.key.path}",
            )
            return
        try:
            open_file_at(code_executable, region.key.path, region.key.line)
        except OSError as e:
            show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")

    # ── data loading and display ───────────────────────────────────────────────

    def _load_hotspot_region_keys(self, *, merged: bool = False) -> Dict[int, hotspot_data.RegionKey]:
        return self._hotspot_session().load_region_keys(merged=merged)

    def _hotspot_session(self) -> HotspotSession:
        return HotspotSession(self.arguments)

    def _load_hotspot_log(self) -> MeasurementLog:
        return self._hotspot_session().load_log()

    def _refresh_hotspot_results(self) -> None:
        """Reload Hotspots.json and the run log, then refresh every view."""
        results = self._hotspot_session().load_results()
        self._hotspot_regions = results.regions
        self._hotspot_runs = results.runs

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
        self._hotspot_regions_sort = hotspot_view.next_sort(self._hotspot_regions_sort, column)
        self._populate_hotspot_regions_tree()

    def _visible_hotspot_regions(self) -> List[HotspotRegion]:
        allowed = None
        if self.hotspot_hotness_filter_vars is not None:
            allowed = {hotness for hotness, var in self.hotspot_hotness_filter_vars.items() if var.get()}
        kind = self.hotspot_kind_filter_var.get() if self.hotspot_kind_filter_var is not None else "all"
        return hotspot_view.visible_regions(self._hotspot_regions or [], allowed, kind, self._hotspot_regions_sort)

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
                values=hotspot_view.region_row(region),
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
            if hotspot_view.run_failed(run):
                tags.append("failed")
            tree.insert(
                "",
                "end",
                values=hotspot_view.run_row(run),
                tags=tuple(tags),
            )

    # ── prerequisites and button states ────────────────────────────────────────

    def _hotspot_current_config(self) -> Optional[str]:
        """The selected configuration, tolerating the panel being built first.

        ``ConfigManagerApp`` assigns ``current_config`` only after it has built the
        tabs, so the initial refresh runs before the attribute exists.
        """
        return getattr(self, "current_config", None)

    def _hotspot_build_state(self) -> Tuple[str, str]:
        """Whether the current build can serve another run directly, and why not."""
        return self._hotspot_session().build_state(self._hotspot_current_config())

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
        summary = hotspot_view.measurement_summary(state, detail, runs, self._hotspot_regions or [])

        if self.hotspot_build_label is not None:
            build_color = widgets.STATUS_OK if summary.build_ok else widgets.STATUS_STOP
            self.hotspot_build_label.config(text=summary.build_text, foreground=build_color)
        if self.hotspot_runs_label is not None:
            self.hotspot_runs_label.config(text=summary.runs_text, foreground="black")
        if self.hotspot_hotness_label is not None:
            self.hotspot_hotness_label.config(
                text=summary.hotness_text, foreground="black" if summary.has_regions else "gray"
            )
        if self.hotspot_warning_label is not None:
            if summary.warnings:
                self.hotspot_warning_label.config(text="\n".join(summary.warnings))
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
            self.hotspot_clear_button.config(
                state="normal" if idle and self._hotspot_session().has_data() else "disabled"
            )

    def _update_hotspot_config_display(self) -> None:
        """Refresh the parts of the tab that depend on the selected configuration."""
        self._update_hotspot_ui()

    # ── running measurements ───────────────────────────────────────────────────

    def _hotspot_append_output(self, text: str) -> None:
        """Append to the output console; main thread only."""
        if self.hotspot_output_text is None:
            return
        self.hotspot_output_text.config(state=tk.NORMAL)
        self.hotspot_output_text.insert(tk.END, text)
        self.hotspot_output_text.see(tk.END)
        self.hotspot_output_text.config(state="disabled")

    def _run_hotspot_job(self, work: Callable[[WorkContext], bool]) -> None:
        """Run ``work`` on a worker thread and show what it reports; ``_on_hotspot_work_complete`` ends it."""
        events: "queue.Queue[WorkEvent]" = queue.Queue()
        job = WorkRunner(work, events)
        self._hotspot_job = job
        TkJobAdapter(self, events, lambda event: self._on_hotspot_event(job, event)).start()
        job.start()

    def _on_hotspot_event(self, job: WorkRunner, event: WorkEvent) -> None:
        """Handle one event of the hotspot work; runs on the Tk main thread."""
        if isinstance(event, WorkOutput):
            self._hotspot_append_output(event.text)
        elif isinstance(event, WorkStatus):
            self.status_label.config(text=event.text, foreground=_STATUS_COLORS[event.kind])
        elif isinstance(event, WorkFinished):
            if event.error is not None:  # a crash of the work must not leave the UI stuck
                logger.error("hotspot work failed: %s", event.error)
                self._hotspot_append_output(f"\nError: {event.error}\n")
            self._hotspot_job = None
            self._on_hotspot_work_complete(bool(event.result) and event.error is None, job.cancel_requested)

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

        self.hotspot_running = True
        self._update_hotspot_ui()
        if self.hotspot_run_button is not None:
            self.hotspot_run_button.config(state="disabled", text="⟳ Running...")
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="normal")
        self._clear_hotspot_output()
        self.status_label.config(text="⏳ Hotspot measurement in progress...", foreground=widgets.STATUS_BUSY)

        session = self._hotspot_session()
        request = session.make_request(
            self.current_config,
            needs_compile=needs_compile,
            repetitions=repetitions if execute_runs else 0,
            timeouts=(
                self.timeout_execution_var.get(),
                self.timeout_compilation_var.get(),
                self.timeout_validation_var.get(),
            ),
        )
        self._run_hotspot_job(lambda ctx: session.run(ctx, request))

    def _rerun_hotspot_analysis(self) -> None:
        if self.hotspot_running:
            show_error(self, "Already Running", "A hotspot measurement is already running.")
            return
        self.hotspot_running = True
        self._update_hotspot_ui()
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="normal")
        self._clear_hotspot_output()
        self.status_label.config(text="⏳ Hotspot analysis in progress...", foreground=widgets.STATUS_BUSY)

        self._run_hotspot_job(self._hotspot_session().invoke_analyzer)

    def _on_hotspot_work_complete(self, success: bool, cancelled: bool) -> None:
        self.hotspot_running = False
        if self.hotspot_run_button is not None:
            self.hotspot_run_button.config(text="Run Measurement")
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="disabled")

        self._refresh_hotspot_results()
        # the analyzer's output gates the Autotuning tab's hotspot types
        self.project_state.publish(HotspotsChanged())

        if cancelled:
            self._set_status("Hotspot measurement stopped", fg=widgets.STATUS_STOP, reset_delay=3000)
        elif success:
            self._set_status("Hotspot measurement completed", fg=widgets.STATUS_OK, reset_delay=3000)
        else:
            self._set_status("Hotspot measurement failed", fg=widgets.STATUS_FAIL, reset_delay=3000)

    def _stop_hotspot_measurement(self) -> None:
        job = self._hotspot_job
        if job is not None:
            job.cancel()
        if self.hotspot_stop_button is not None:
            self.hotspot_stop_button.config(state="disabled")
        self.status_label.config(text="Stopping hotspot measurement...", foreground=widgets.STATUS_STOP)

    # ── clearing ───────────────────────────────────────────────────────────────

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
        self._hotspot_session().delete_hotspot_dir()
        self._clear_hotspot_output()
        self._refresh_hotspot_results()
        self.project_state.publish(HotspotsChanged())
        self._set_status("Hotspot measurements cleared", reset_delay=3000)
