# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import functools
import json
import os
import textwrap
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.detail_bar import DetailBar
from discopop_library.ProjectManager.gui.widgets import danger_button
from discopop_library.ProjectManager.gui.plots import embedding, mode_style, report_charts
from discopop_library.ProjectManager.gui.plots.data import ExecutionRecord, parse_execution_results

# Chart types offered by the "+" tab. Each entry: default state + a title stem.
_PLOT_TYPES: Dict[str, Dict[str, Any]] = {
    "pareto": {"label": "Trade-off scatter", "stem": "Scatter"},
    "scaling": {"label": "Thread scaling", "stem": "Scaling"},
    "spbars": {"label": "Speedup / efficiency bars", "stem": "Bars"},
    "rtbars": {"label": "Runtime bars", "stem": "Runtime"},
}
_ADD_TAB_TEXT = "  ＋  "
_DETAIL_BAR_WIDTH = 280
_DETAIL_PLACEHOLDER = "Click a point, line, or bar\nto see its details here."


class ReportPanelMixin(ConfigManagerMixinBase):
    # notebook + plot-tab bookkeeping
    report_notebook: Optional[ttk.Notebook] = None
    _report_plot_tabs: Optional[Dict[str, Dict[str, Any]]] = None
    _report_add_tab: Optional[tk.Widget] = None
    _report_prev_tab: Optional[str] = None
    _report_plot_counter: int = 0

    def _build_report_panel(self, parent: tk.Widget) -> None:
        button_frame = ttk.Frame(parent)
        button_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        def on_reset_execution_results() -> None:
            if ask_yes_no(
                self,
                "Confirm Reset",
                "Are you sure you want to reset execution results?\nThis will delete all execution data and reports.",
            ):
                self._reset_execution_results()

        def on_reset_project() -> None:
            if ask_yes_no(
                self,
                "Confirm Reset",
                "Are you sure you want to reset the entire project?\nThis will delete all data except the configuration files.",
            ):
                self._reset_project_data()

        danger_button(button_frame, text="Reset Execution Results", command=on_reset_execution_results).pack(
            side=tk.LEFT, padx=5
        )
        danger_button(button_frame, text="Reset Project", command=on_reset_project).pack(side=tk.LEFT, padx=5)

        self.generate_report_button = widgets.primary_button(
            button_frame, text="Generate PDF Report", state="disabled", command=self._generate_report
        )
        self.generate_report_button.pack(side=tk.LEFT, padx=5)
        self.view_report_button = widgets.create_button(
            button_frame, text="View Report PDF", state="disabled", command=self._view_report
        )
        self.view_report_button.pack(side=tk.LEFT, padx=5)

        self.reload_report_button = widgets.create_button(
            button_frame, text="⟳ Reload", command=self._update_report_display
        )
        self.reload_report_button.pack(side=tk.RIGHT, padx=5)

        # Results notebook: a permanent Table tab, on-demand plot tabs, and a
        # trailing "+" tab that opens the add-plot menu.
        self.report_notebook = ttk.Notebook(parent)
        self.report_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._report_plot_tabs = {}

        table_tab = ttk.Frame(self.report_notebook)
        self.report_notebook.add(table_tab, text="Table")
        self._build_report_table(table_tab)

        self._report_add_tab = ttk.Frame(self.report_notebook)
        self.report_notebook.add(self._report_add_tab, text=_ADD_TAB_TEXT)

        self.report_notebook.bind("<<NotebookTabChanged>>", self._on_report_tab_changed)

        # open with a trade-off scatter shown by default
        self._add_report_plot("pareto")

    # ── the permanent Table tab ────────────────────────────────────────────────

    def _build_report_table(self, parent: tk.Widget) -> None:
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        columns = (
            "Config",
            "Script",
            "Setting",
            "Label",
            "Applied Suggestions",
            "Not Applied",
            "Threads",
            "Status",
            "Time",
            "Speedup",
            "Efficiency",
        )
        self.report_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", yscrollcommand=vsb.set, xscrollcommand=hsb.set
        )
        column_widths = {
            "Config": 90,
            "Script": 100,
            "Setting": 70,
            "Label": 85,
            "Applied Suggestions": 90,
            "Not Applied": 90,
            "Threads": 65,
            "Status": 70,
            "Time": 65,
            "Speedup": 75,
            "Efficiency": 75,
        }
        for col in columns:
            self.report_tree.heading(col, text=col)
            self.report_tree.column(col, width=column_widths.get(col, 100), anchor="w", stretch=True)

        self.report_tree.tag_configure("evenrow", background=widgets.TREE_EVEN_ROW)
        self.report_tree.tag_configure("oddrow", background=widgets.TREE_ODD_ROW)
        # validity / best-row emphasis
        self.report_tree.tag_configure("failed", foreground=widgets.STATUS_FAIL)
        # a skipped run (suggestions not applied) is neither a failure nor a result:
        # give it its own emphasis so it cannot be confused with either
        self.report_tree.tag_configure(
            "not_applied",
            foreground=mode_style.status_color(mode_style.NOT_APPLIED_STATUS),
            background="#f3e6f7",
        )
        self.report_tree.tag_configure("best", background="#d6ebd5")

        self.report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self.report_tree.yview)
        hsb.config(command=self.report_tree.xview)

        def _on_tree_mousewheel(event: Any) -> object:
            self.report_tree.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        self.report_tree.bind("<MouseWheel>", _on_tree_mousewheel)
        self.report_tree.bind("<Button-4>", lambda e: self.report_tree.yview_scroll(-1, "units"))
        self.report_tree.bind("<Button-5>", lambda e: self.report_tree.yview_scroll(1, "units"))

    def _load_execution_records(self) -> List[ExecutionRecord]:
        path = os.path.join(self.arguments.project_dir, "execution_results.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r") as f:
                return parse_execution_results(json.load(f))
        except (json.JSONDecodeError, OSError):
            return []

    def _update_report_display(self) -> None:
        """Refresh the table and any open plot tabs from execution_results.json."""
        records = self._load_execution_records()
        self._populate_report_table(records)
        self._refresh_report_charts(records)

    def _populate_report_table(self, records: List[ExecutionRecord]) -> None:
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)

        # best (highest speedup) valid record per config, for highlighting
        best_ids: Dict[str, int] = {}
        best_speedup: Dict[str, float] = {}
        for idx, r in enumerate(records):
            if (
                r.valid
                and r.speedup is not None
                and (r.config not in best_speedup or r.speedup > best_speedup[r.config])
            ):
                best_speedup[r.config] = r.speedup
                best_ids[r.config] = idx

        prev_config = prev_script = prev_setting = None
        for idx, r in enumerate(records):
            row_index = len(self.report_tree.get_children())
            tags: List[str] = ["evenrow" if row_index % 2 == 0 else "oddrow"]
            if r.application_failed:
                tags.append("not_applied")
            elif not r.valid:
                tags.append("failed")
            if best_ids.get(r.config) == idx:
                tags.append("best")

            config_str = r.config if r.config != prev_config else ""
            script_str = r.script if (r.config != prev_config or r.script != prev_script) else ""
            setting_str = r.mode if (r.config, r.script, r.mode) != (prev_config, prev_script, prev_setting) else ""
            prev_config, prev_script, prev_setting = r.config, r.script, r.mode

            status = report_charts.record_status_text(r)
            not_applied_str = (
                textwrap.shorten(str(r.failed_suggestions or r.requested_suggestions), width=20, placeholder="...]")
                if r.application_failed
                else "-"
            )
            self.report_tree.insert(
                "",
                "end",
                values=(
                    config_str,
                    script_str,
                    setting_str,
                    r.label,
                    textwrap.shorten(str(r.applied_suggestions), width=20, placeholder="...]"),
                    not_applied_str,
                    str(r.thread_count),
                    status,
                    # a skipped run has no runtime to show
                    str(r.time) if r.has_measurement else "-",
                    "-" if r.speedup is None else str(round(r.speedup, 3)),
                    "-" if r.efficiency is None else str(round(r.efficiency, 3)),
                ),
                tags=tuple(tags),
            )

    # ── the "+" tab and plot tabs ───────────────────────────────────────────────

    def _on_report_tab_changed(self, _event: Any) -> None:
        """When the trailing '+' tab is selected, open the menu and bounce back."""
        assert self.report_notebook is not None
        current = self.report_notebook.select()
        add_tab_id = str(self._report_add_tab) if self._report_add_tab is not None else None
        if current == add_tab_id:
            # restore the previously active tab so "+" never stays selected
            if self._report_prev_tab and self._report_prev_tab in self.report_notebook.tabs():
                self.report_notebook.select(self._report_prev_tab)
            else:
                self.report_notebook.select(0)
            self._open_add_plot_menu()
        else:
            self._report_prev_tab = current

    def _open_add_plot_menu(self) -> None:
        assert self.report_notebook is not None
        menu = tk.Menu(self.report_notebook, tearoff=0)
        for key, meta in _PLOT_TYPES.items():
            menu.add_command(label=str(meta["label"]), command=functools.partial(self._add_report_plot, key))
        x = self.report_notebook.winfo_pointerx()
        y = self.report_notebook.winfo_pointery()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _add_report_plot(self, plot_type: str) -> None:
        assert self.report_notebook is not None and self._report_plot_tabs is not None
        self._report_plot_counter += 1
        stem = _PLOT_TYPES[plot_type]["stem"]
        title = f"{stem} {self._report_plot_counter}"

        tab = ttk.Frame(self.report_notebook)
        # insert before the trailing "+" tab
        insert_index = self.report_notebook.index(str(self._report_add_tab))
        self.report_notebook.insert(insert_index, tab, text=title)

        state: Dict[str, Any] = {"type": plot_type, "controls": {}}
        # Control strip (selectors + close) pinned below the plot + detail bar.
        strip = ttk.Frame(tab)
        strip.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)
        self._build_plot_controls(strip, tab, state)

        # Above the strip: the plot on the left, an always-visible detail bar on
        # the right showing whichever point/line/bar was last clicked -- kept
        # visible (rather than a popup window) so the view stays stable. A
        # PanedWindow (rather than a plain frame) lets the user drag the bar
        # wider or narrower.
        content = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        plot_frame = ttk.Frame(content)
        figure, canvas, _ = embedding.create_canvas(plot_frame)
        state["figure"] = figure
        state["canvas"] = canvas
        state["plot_frame"] = plot_frame
        content.add(plot_frame, stretch="always")

        detail = DetailBar(content, placeholder=_DETAIL_PLACEHOLDER)
        state["detail"] = detail
        content.add(detail, minsize=160, width=_DETAIL_BAR_WIDTH, stretch="never")

        self._report_plot_tabs[str(tab)] = state
        self.report_notebook.select(tab)
        self._render_plot_tab(state)

    # ── the always-visible detail bar ───────────────────────────────────────────

    def _on_plot_record_selected(self, state: Dict[str, Any], record: ExecutionRecord) -> None:
        fields = [
            ("Config", record.config),
            ("Mode", record.mode),
            ("Suggestions", str(record.applied_suggestions) if record.applied_suggestions else "(none)"),
            ("Threads", str(record.thread_count)),
            ("Runtime", f"{record.time:.3f} s" if record.has_measurement else "not executed"),
            ("Status", report_charts.record_status_text(record)),
        ]
        if record.application_failed:
            fields.append(
                (
                    "Not applied",
                    str(record.failed_suggestions or record.requested_suggestions) or "(unknown)",
                )
            )
        if record.speedup is not None:
            fields.append(("Speedup", f"{record.speedup:.3f}×"))
        if record.efficiency is not None:
            fields.append(("Efficiency", f"{record.efficiency:.3f}"))
        fields.append(("Script", record.script))
        fields.append(("Label", record.label or "(unnamed)"))
        state["detail"].show_fields(fields)

    def _build_plot_controls(self, strip: tk.Widget, tab: tk.Widget, state: Dict[str, Any]) -> None:
        plot_type = state["type"]
        configs = ["all"] + sorted({r.config for r in self._load_execution_records()})

        def add_combo(label: str, key: str, values: List[str], default: str) -> None:
            ttk.Label(strip, text=label + ":").pack(side=tk.LEFT, padx=(14, 6))
            var = tk.StringVar(value=default)
            combo = ttk.Combobox(
                strip, textvariable=var, values=values, state="readonly", width=max(8, len(default) + 2)
            )
            combo.pack(side=tk.LEFT, padx=(0, 6))
            combo.bind("<<ComboboxSelected>>", lambda _e: self._render_plot_tab(state))
            state["controls"][key] = var

        def add_check(label: str, key: str, default: bool) -> None:
            var = tk.BooleanVar(value=default)
            ttk.Checkbutton(strip, text=label, variable=var, command=lambda: self._render_plot_tab(state)).pack(
                side=tk.LEFT, padx=6
            )
            state["controls"][key] = var

        if plot_type == "pareto":
            add_combo("X", "x", ["efficiency", "speedup", "threads"], "efficiency")
            add_combo("Y", "y", ["speedup", "efficiency", "runtime"], "speedup")
            add_combo("Config", "config", configs, "all")
            add_check("Frontier", "frontier", True)
            add_check("Valid only", "valid_only", False)
        elif plot_type == "scaling":
            add_combo("Metric", "metric", ["speedup", "runtime", "efficiency"], "speedup")
            add_combo("Config", "config", configs, "all")
            add_check("Ideal", "ideal", True)
        # bar charts have a fixed metric (spbars=speedup, rtbars=runtime); no controls

        danger_button(strip, text="✕", command=lambda: self._close_report_plot(tab)).pack(side=tk.RIGHT, padx=4)

    def _render_plot_tab(self, state: Dict[str, Any]) -> None:
        records = [r for r in self._load_execution_records() if r.script == "execute.sh"]
        figure = state["figure"]
        controls = state["controls"]
        plot_type = state["type"]
        on_select = functools.partial(self._on_plot_record_selected, state)
        if plot_type == "pareto":
            report_charts.render_pareto(
                figure,
                records,
                x_metric=controls["x"].get(),
                y_metric=controls["y"].get(),
                config_filter=controls["config"].get(),
                valid_only=controls["valid_only"].get(),
                show_frontier=controls["frontier"].get(),
                on_select=on_select,
            )
        elif plot_type == "scaling":
            report_charts.render_scaling(
                figure,
                records,
                metric=controls["metric"].get(),
                config_filter=controls["config"].get(),
                show_ideal=controls["ideal"].get(),
                on_select=on_select,
            )
        elif plot_type == "spbars":
            report_charts.render_bars(figure, records, metric="speedup", on_select=on_select)
        elif plot_type == "rtbars":
            report_charts.render_bars(figure, records, metric="runtime", on_select=on_select)
        embedding.redraw(state["canvas"])
        if state.get("plot_frame") is not None:
            embedding.force_resize_redraw(state["plot_frame"])

    def _close_report_plot(self, tab: tk.Widget) -> None:
        assert self.report_notebook is not None and self._report_plot_tabs is not None
        self._report_plot_tabs.pop(str(tab), None)
        self.report_notebook.forget(tab)
        self.report_notebook.select(0)

    def _refresh_report_charts(self, records: Optional[List[ExecutionRecord]] = None) -> None:
        if not self._report_plot_tabs:
            return
        for state in list(self._report_plot_tabs.values()):
            self._render_plot_tab(state)
