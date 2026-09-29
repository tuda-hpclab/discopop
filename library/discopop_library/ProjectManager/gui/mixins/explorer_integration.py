# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from discopop_library.ProjectManager.gui.mixins.helpers import Tooltip, show_error, clean_ansi_output
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.plots import hotspot_data
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.gui.widgets import (
    create_styled_output_console,
    heading_label,
    caption_label,
    error_label,
)

logger = logging.getLogger("ExplorerIntegration")

# Selectable interpretations of the profiled dependency data, as (value, label) pairs.
# "no_states" runs the explorer with --ignore-dependency-states, i.e. it discards the
# callpath state markers the profiler recorded in dynamic_dependencies.txt.
DETECTION_MODES = [
    ("default", "default (full states)"),
    ("no_states", "no_states (states ignored)"),
]
DEFAULT_DETECTION_MODE = "default"
NO_STATES_DETECTION_MODE = "no_states"


class ExplorerIntegrationMixin(ConfigManagerMixinBase):
    explorer_running = False
    explorer_output_text: Optional[scrolledtext.ScrolledText] = None
    explorer_run_button: Optional[RoundedButton] = None
    explorer_stop_button: Optional[RoundedButton] = None
    browse_suggestions_button: Optional[RoundedButton] = None
    show_in_vscode_button: Optional[RoundedButton] = None
    no_suggestions_label: Optional[ttk.Label] = None
    prerequisite_info_label: Optional[ttk.Label] = None
    hotspot_hint_frame: Optional[ttk.LabelFrame] = None
    pattern_types_vars: Optional[Dict[str, tk.BooleanVar]] = None
    detection_mode_var: Optional[tk.StringVar] = None
    jobs_var: Optional[tk.StringVar] = None
    collect_stats_var: Optional[tk.BooleanVar] = None
    visualize_var: Optional[tk.BooleanVar] = None
    explorer_visualization_frame: Optional[tk.Frame] = None
    explorer_visualization_placeholder: Optional[ttk.Label] = None
    pattern_detection_output_tabs: Optional[ttk.Notebook] = None
    _pattern_detection_tab_tooltip: Optional[Tooltip] = None
    _pattern_detection_tab_tooltip_timer: Optional[str] = None
    _pattern_detection_tab_tooltip_active_tab: Optional[int] = None
    _explorer_process: Optional["subprocess.Popen[str]"] = None
    _explorer_stopped: bool = False

    def _build_pattern_detection_panel(self, parent: tk.Widget) -> None:
        self.pattern_detection_output_tabs = ttk.Notebook(parent)
        self.pattern_detection_output_tabs.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        detection_tab = ttk.Frame(self.pattern_detection_output_tabs)
        self.pattern_detection_output_tabs.add(detection_tab, text="Detection")

        main_paned = tk.PanedWindow(detection_tab, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Left panel - settings
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, minsize=650, width=650)

        # Hotspot hint: an always-packed container that stays empty (and therefore
        # invisible) while hotspot results exist, so the hint can be shown and hidden
        # without disturbing the packing order of the frames below it.
        hotspot_hint_container = ttk.Frame(left_frame)
        hotspot_hint_container.pack(fill=tk.X, padx=0, pady=0)
        self._build_hotspot_hint(hotspot_hint_container)

        # Settings frame
        settings_frame = ttk.LabelFrame(left_frame, text="Settings", padding=5)
        settings_frame.pack(fill=tk.X, padx=5, pady=5)

        # Pattern types selection
        patterns_frame = ttk.Frame(settings_frame)
        patterns_frame.pack(fill=tk.X, pady=5)

        heading_label(patterns_frame, "Pattern Types:").pack(side=tk.LEFT, padx=5)

        self.pattern_types_vars = {}
        for pattern in ["reduction", "doall", "task"]:
            var = tk.BooleanVar(value=pattern in ["reduction", "doall"])
            self.pattern_types_vars[pattern] = var
            cb = ttk.Checkbutton(patterns_frame, text=pattern, variable=var)
            cb.pack(side=tk.LEFT, padx=5)

        # Interpretation of the profiled dependency data
        detection_mode_frame = ttk.Frame(settings_frame)
        detection_mode_frame.pack(fill=tk.X, pady=5)

        heading_label(detection_mode_frame, "Dependency Data:").pack(side=tk.TOP, anchor=tk.W, padx=5)

        # below the label and stacked vertically, so the options read as a list
        detection_mode_choices = ttk.Frame(detection_mode_frame)
        detection_mode_choices.pack(side=tk.TOP, anchor=tk.W, padx=15)

        self.detection_mode_var = tk.StringVar(value=DEFAULT_DETECTION_MODE)
        for mode_value, mode_label in DETECTION_MODES:
            ttk.Radiobutton(
                detection_mode_choices,
                text=mode_label,
                variable=self.detection_mode_var,
                value=mode_value,
            ).pack(side=tk.TOP, anchor=tk.W)

        caption_label(
            settings_frame,
            "'no_states' ignores the profiler's callpath state markers, which also reclassifies the\n"
            "affected dependencies from dynamic to static. Re-running detection in either mode\n"
            "replaces the existing suggestions.",
        ).pack(anchor=tk.W, padx=10)

        # Jobs selection
        jobs_frame = ttk.Frame(settings_frame)
        jobs_frame.pack(fill=tk.X, pady=5)

        ttk.Label(jobs_frame, text="Threads:", font=widgets.FONT_BODY).pack(side=tk.LEFT, padx=5)
        self.jobs_var = tk.StringVar(value=widgets.THREAD_AUTO)
        jobs_combo = widgets.thread_selector(jobs_frame, self.jobs_var)
        jobs_combo.pack(side=tk.LEFT, padx=5)
        caption_label(jobs_frame, "(auto = unlimited; custom counts can be typed)").pack(side=tk.LEFT, padx=5)

        # Visualization option
        visualize_frame = ttk.Frame(settings_frame)
        visualize_frame.pack(fill=tk.X, pady=5)

        self.visualize_var = tk.BooleanVar(value=False)
        visualize_cb = ttk.Checkbutton(visualize_frame, text="Show graph visualization", variable=self.visualize_var)
        visualize_cb.pack(side=tk.LEFT, padx=5)
        caption_label(
            visualize_frame,
            "(runs in-process; UI is unresponsive while detection runs)",
        ).pack(side=tk.LEFT, padx=5)

        # Buttons frame
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, padx=0, pady=0)

        self.explorer_run_button = widgets.primary_button(
            button_frame, text="Run Pattern Detection", command=self._run_pattern_detection, state="disabled"
        )
        self.explorer_run_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.explorer_stop_button = widgets.danger_button(
            button_frame, text="Stop", command=self._stop_pattern_detection, state="disabled"
        )
        self.explorer_stop_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Second row of buttons
        button_frame_row2 = ttk.Frame(left_frame)
        button_frame_row2.pack(fill=tk.X, padx=0, pady=0)

        self.show_in_vscode_button = widgets.create_button(
            button_frame_row2, text="Show Suggestions in VSCode", command=self._open_in_vscode, state="disabled"
        )
        self.show_in_vscode_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Third row of buttons
        button_frame_row3 = ttk.Frame(left_frame)
        button_frame_row3.pack(fill=tk.X, padx=0, pady=0)

        self.browse_suggestions_button = widgets.create_button(
            button_frame_row3, text="Browse Suggestions", command=self._open_suggestion_browser, state="disabled"
        )
        self.browse_suggestions_button.pack(side=tk.LEFT, padx=5, pady=5)

        # No suggestions notification label
        self.no_suggestions_label = error_label(left_frame, "No patterns found.")
        self.no_suggestions_label.pack(anchor=tk.W, padx=5, pady=(5, 0))

        # Right panel - output
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame)

        output_frame = ttk.LabelFrame(right_frame, text="Output")
        output_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.explorer_output_text = create_styled_output_console(output_frame)
        self.explorer_output_text.pack(fill=tk.BOTH, expand=True)

        # Graph Visualization tab - top-level, spans the full panel width
        visualization_tab = ttk.Frame(self.pattern_detection_output_tabs)
        self.pattern_detection_output_tabs.add(visualization_tab, text="Graph Visualization")

        self.explorer_visualization_frame = tk.Frame(visualization_tab)
        self.explorer_visualization_frame.pack(fill=tk.BOTH, expand=True)

        self.explorer_visualization_placeholder = caption_label(
            self.explorer_visualization_frame,
            "Run pattern detection with 'Show graph visualization' enabled to see graphs here.",
        )
        self.explorer_visualization_placeholder.pack(expand=True)

        self._update_pattern_detection_ui()
        self._setup_pattern_detection_tab_tooltip()

    def _build_hotspot_hint(self, parent: tk.Widget) -> None:
        """Build the (initially hidden) 'no hotspot results' hint block."""
        self.hotspot_hint_frame = ttk.LabelFrame(parent, text="Hotspot Information", padding=5)

        ttk.Label(
            self.hotspot_hint_frame,
            text="⚠ No Hotspot Detection results available.",
            font=widgets.FONT_BODY,
            foreground=widgets.STATUS_STOP,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=5)

        caption_label(
            self.hotspot_hint_frame,
            "Pattern detection restricts its analysis to the hot parts of the program when hotspot\n"
            "information is available. Measuring hotspots first is therefore recommended: the\n"
            "filtering it enables can speed up this step significantly.",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=5, pady=(2, 4))

        widgets.create_button(
            self.hotspot_hint_frame,
            text="Go to Hotspot Detection",
            command=lambda: self.right_tabs.select(self.hotspot_tab_index),
        ).pack(anchor=tk.W, padx=5, pady=(0, 2))

    def _update_hotspot_hint(self) -> None:
        """Show the hint exactly while the explorer would find no hotspots to filter with."""
        if self.hotspot_hint_frame is None:
            return
        if hotspot_data.hotspots_available_for_explorer(self.arguments.dot_dp):
            self.hotspot_hint_frame.pack_forget()
        else:
            self.hotspot_hint_frame.pack(fill=tk.X, padx=5, pady=(5, 0))

    def _setup_pattern_detection_tab_tooltip(self) -> None:
        tooltip_text = (
            "Prerequisites not met:\n"
            "Profiling data not found.\n"
            "Execute a configuration in 'dp' mode with 'inplace' enabled first."
        )
        self._pattern_detection_tab_tooltip = Tooltip(self.right_tabs, tooltip_text)

        def on_motion(event: Any) -> None:
            try:
                result = self.right_tabs.tk.call(str(self.right_tabs), "identify", "tab", event.x, event.y)
                tab_under_cursor: Optional[int] = int(result) if result != "" else None
            except Exception:
                tab_under_cursor = None

            if tab_under_cursor == self._pattern_detection_tab_tooltip_active_tab:
                return

            _hide_tooltip()

            if tab_under_cursor == self.pattern_detection_tab_index:
                if not self._check_explorer_prerequisites():
                    self._pattern_detection_tab_tooltip_active_tab = tab_under_cursor
                    assert self._pattern_detection_tab_tooltip is not None
                    self._pattern_detection_tab_tooltip_timer = self.after(  # type: ignore
                        500, self._pattern_detection_tab_tooltip.showtip, event.x_root, event.y_root + 20
                    )

        def _hide_tooltip() -> None:
            if self._pattern_detection_tab_tooltip_timer:
                self.after_cancel(self._pattern_detection_tab_tooltip_timer)  # type: ignore
                self._pattern_detection_tab_tooltip_timer = None
            if self._pattern_detection_tab_tooltip is not None:
                self._pattern_detection_tab_tooltip.hidetip()
            self._pattern_detection_tab_tooltip_active_tab = None

        def on_leave(event: Any) -> None:
            _hide_tooltip()

        self.right_tabs.bind("<Motion>", on_motion, add="+")
        self.right_tabs.bind("<Leave>", on_leave, add="+")

    def _update_pattern_detection_ui(self) -> None:
        ready = self._check_explorer_prerequisites()

        self._update_hotspot_hint()

        if self.explorer_run_button is not None:
            self.explorer_run_button.config(state="normal" if ready else "disabled")

        # Count suggestions the same way as in execute_panel.py for consistency
        patch_gen_dir = os.path.join(self.arguments.dot_dp, "patch_generator")
        total_suggestions = 0
        if os.path.isdir(patch_gen_dir):
            for sid in os.listdir(patch_gen_dir):
                sid_dir = os.path.join(patch_gen_dir, sid)
                if os.path.isdir(sid_dir):
                    total_suggestions += sum(1 for f in os.listdir(sid_dir) if f.endswith(".patch"))

        browse_ready = total_suggestions > 0
        if self.browse_suggestions_button is not None:
            self.browse_suggestions_button.config(state="normal" if browse_ready else "disabled")
        if self.show_in_vscode_button is not None:
            self.show_in_vscode_button.config(state="normal" if browse_ready else "disabled")

        detection_executed = self._check_pattern_detection_executed()
        patterns_found = self._check_patterns_found()
        if self.no_suggestions_label is not None:
            if detection_executed and not patterns_found:
                self.no_suggestions_label.pack(anchor=tk.W, padx=5, pady=(5, 0))
            else:
                self.no_suggestions_label.pack_forget()

        self._update_pattern_detection_tab_state(ready)
        self._update_autotuning_tab_state(ready and browse_ready)
        if hasattr(self, "_update_autotuning_ui"):
            self._update_autotuning_ui()
        # freshly generated patches are what the Patch Repair tab works on
        if hasattr(self, "_update_patch_repair_ui"):
            self._update_patch_repair_ui()

    def _check_browse_suggestions_available(self) -> bool:
        patch_gen_dir = os.path.join(self.arguments.dot_dp, "patch_generator")
        if not os.path.isdir(patch_gen_dir):
            return False
        for entry in os.listdir(patch_gen_dir):
            sid_dir = os.path.join(patch_gen_dir, entry)
            if os.path.isdir(sid_dir):
                patch_count = sum(1 for f in os.listdir(sid_dir) if f.endswith(".patch"))
                if patch_count > 0:
                    return True
        return False

    def _open_suggestion_browser(self) -> None:
        from discopop_library.ProjectManager.gui.suggestion_browser import SuggestionBrowserDialog

        SuggestionBrowserDialog(
            self,
            self.arguments.dot_dp,
        )

    def _open_in_vscode(self) -> None:
        # The DiscoPoP VSCode extension activates on a workspace that *contains* a
        # .discopop directory (activation event "workspaceContains:**/.discopop")
        # and then focuses its sidebar view. We therefore open the project root
        # (the parent of the .discopop directory), not the .discopop dir itself.
        dot_dp = os.path.abspath(self.arguments.dot_dp)
        project_root = os.path.dirname(dot_dp)

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

        try:
            subprocess.Popen(
                [code_executable, project_root],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")
            return

        # Opening the folder alone only focuses the DiscoPoP sidebar on a *fresh*
        # window (activation runs once). If the folder is already open, re-running
        # `code` just refocuses the window without re-firing activation. Dispatching
        # a URI to the extension's UriHandler focuses the sidebar on every
        # invocation, so the button behaves consistently regardless of window state.
        # The dotDiscopop/projectPath query tells the extension which configuration
        # to select (creating a ViewOnly configuration for it if none exists).
        focus_uri = (
            "vscode://TUDarmstadt-LaboratoryforParallelProgramming.discopop/focus"
            f"?dotDiscopop={quote(dot_dp, safe='')}&projectPath={quote(project_root, safe='')}"
        )
        try:
            subprocess.Popen(
                [code_executable, "--open-url", focus_uri],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            # Best-effort: the folder is already opening; only the auto-focus is lost.
            pass

        self.status_label.config(text="Opening project in VSCode...", foreground=widgets.STATUS_BUSY)
        self.after(3000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore

    def _ignore_dependency_states(self) -> bool:
        """Whether the selected detection mode discards the callpath state markers."""
        return self.detection_mode_var is not None and self.detection_mode_var.get() == NO_STATES_DETECTION_MODE

    def _check_explorer_prerequisites(self) -> bool:
        profiler_dir = os.path.join(self.arguments.dot_dp, "profiler")
        return os.path.isdir(profiler_dir)

    def _check_patterns_found(self) -> bool:
        import json

        patterns_file = os.path.join(self.arguments.dot_dp, "explorer", "patterns.json")
        if not os.path.exists(patterns_file):
            return False
        try:
            with open(patterns_file, "r") as f:
                data = json.load(f)
            patterns = data.get("patterns", {})
            return any(
                patterns.get(key, []) for key in ["optimizer_output", "merged_pattern", "task", "do_all", "reduction"]
            )
        except (json.JSONDecodeError, IOError):
            return False

    def _check_pattern_detection_executed(self) -> bool:
        explorer_dir = os.path.join(self.arguments.dot_dp, "explorer")
        return os.path.isdir(explorer_dir)

    def _run_pattern_detection(self) -> None:
        if not self._check_explorer_prerequisites():
            show_error(
                self,
                "Prerequisites Not Met",
                "Profiling data not found.\nPlease execute a configuration in 'dp' mode with 'inplace' enabled first.",
            )
            return

        if self.explorer_running:
            show_error(self, "Already Running", "Pattern detection is already running.")
            return

        self.explorer_running = True
        self._explorer_stopped = False
        if self.explorer_run_button is not None:
            self.explorer_run_button.config(state="disabled", text="⟳ Running...")

        visualize = self.visualize_var is not None and self.visualize_var.get()

        if self.explorer_stop_button is not None:
            # a visualized run blocks the main thread, so it cannot be interrupted by a button click
            self.explorer_stop_button.config(state="disabled" if visualize else "normal")

        if self.no_suggestions_label is not None:
            self.no_suggestions_label.pack_forget()

        self.status_label.config(text="⏳ Pattern detection in progress...", foreground=widgets.STATUS_BUSY)

        if self.explorer_output_text is not None:
            self.explorer_output_text.config(state=tk.NORMAL)
            self.explorer_output_text.delete("1.0", tk.END)
            self.explorer_output_text.config(state="disabled")

        def append_output(text: str) -> None:
            if self.explorer_output_text is not None:
                self.explorer_output_text.config(state=tk.NORMAL)
                self.explorer_output_text.insert(tk.END, text)
                self.explorer_output_text.see(tk.END)
                self.explorer_output_text.config(state="disabled")

        def thread_safe_append(text: str) -> None:
            self.after(0, lambda: append_output(text))  # type: ignore

        if visualize:
            assert self.pattern_detection_output_tabs is not None
            self.pattern_detection_output_tabs.select(1)
            # let the "Running..." button state redraw before the blocking call starts
            self.after(50, lambda: self._run_pattern_detection_in_process(append_output))  # type: ignore
            return

        def thread_func() -> None:
            try:
                thread_safe_append("Starting pattern detection...\n")
                self._invoke_explorer(thread_safe_append)
                self.after(0, lambda: self._on_pattern_detection_complete())  # type: ignore
            except Exception as e:
                thread_safe_append(f"\nError: {str(e)}\n")
                self.after(0, lambda: self._on_pattern_detection_complete(error=True))  # type: ignore

        thread = threading.Thread(target=thread_func, daemon=True)
        thread.start()

    def _run_pattern_detection_in_process(self, output_callback: Callable[[str], None]) -> None:
        output_callback("Starting pattern detection...\n")
        error = False
        try:
            self._invoke_explorer_in_process(output_callback)
        except Exception as e:
            output_callback(f"\nError: {str(e)}\n")
            error = True
        self._on_pattern_detection_complete(error=error)
        # The visualizer builds its matplotlib canvases while the Tk event loop is
        # blocked by the in-process explorer run, so they were drawn before their
        # widgets had a real size. Force geometry to settle and re-render now, once
        # the event loop is running again, so the graphs appear without a manual
        # window resize.
        self.after(0, self._refresh_visualization_layout)  # type: ignore

    def _refresh_visualization_layout(self) -> None:
        frame = self.explorer_visualization_frame
        if frame is None:
            return
        try:
            # process pending geometry work so widgets report their final size
            frame.update_idletasks()
        except tk.TclError:
            return
        self._redraw_embedded_canvases(frame)

    def _redraw_embedded_canvases(self, widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            self._redraw_embedded_canvases(child)
        # matplotlib's FigureCanvasTkAgg widget is a tk Canvas that re-renders the
        # figure at the correct resolution in its <Configure> handler. Synthesizing
        # that event with the widget's now-correct size triggers the redraw that a
        # manual window resize would otherwise be needed for.
        if widget.winfo_class() == "Canvas":
            width = widget.winfo_width()
            height = widget.winfo_height()
            if width > 1 and height > 1:
                try:
                    widget.event_generate("<Configure>", width=width, height=height)
                except tk.TclError:
                    pass

    def _get_missing_required_explorer_files(self, project_path: str) -> List[str]:
        required_files = [
            os.path.join(project_path, "profiler", "Data.xml"),
            os.path.join(project_path, "profiler", "dynamic_dependencies.txt"),
            os.path.join(project_path, "profiler", "loop_counter_output.txt"),
            os.path.join(project_path, "profiler", "reduction.txt"),
            os.path.join(project_path, "FileMapping.txt"),
        ]
        return [f for f in required_files if not os.path.exists(f)]

    def _invoke_explorer(self, output_callback: Callable[[str], None]) -> None:
        dot_discopop = self.arguments.dot_dp
        project_path = dot_discopop

        output_callback("Loading explorer configuration...\n")

        missing_files = self._get_missing_required_explorer_files(project_path)
        if missing_files:
            output_callback("\nMissing required files:\n")
            for file_path in missing_files:
                output_callback(f"  - {file_path}\n")
            raise RuntimeError("Missing required profiling data files")

        assert self.pattern_types_vars is not None
        assert self.jobs_var is not None

        selected_patterns = [pattern for pattern, var in self.pattern_types_vars.items() if var.get()]
        enable_patterns = ",".join(selected_patterns) if selected_patterns else "reduction,doall"
        jobs_value = widgets.thread_value(self.jobs_var)
        ignore_states = self._ignore_dependency_states()

        output_callback("Configuration:\n")
        output_callback(f"  Patterns: {enable_patterns}\n")
        output_callback(f"  Threads: {jobs_value}\n")
        output_callback(
            f"  Dependency data: {NO_STATES_DETECTION_MODE if ignore_states else DEFAULT_DETECTION_MODE}\n\n"
        )

        cmd = [
            sys.executable,
            "-m",
            "discopop_explorer",
            #            "--path",
            #            project_path,
            "--enable-patterns",
            enable_patterns,
            "--log",
            "WARNING",
        ]

        if jobs_value != "auto":
            cmd.extend(["-j", jobs_value])

        if ignore_states:
            cmd.append("--ignore-dependency-states")

        output_callback("Running pattern detection...\n\n")

        self._explorer_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=project_path,
            start_new_session=True,
        )

        assert self._explorer_process.stdout is not None
        for line in self._explorer_process.stdout:
            cleaned = clean_ansi_output(line.rstrip("\n"))
            if cleaned:
                output_callback(cleaned + "\n")

        self._explorer_process.wait()
        returncode = self._explorer_process.returncode
        self._explorer_process = None

        if returncode != 0:
            raise RuntimeError(f"Explorer exited with return code {returncode}")

        if not self._explorer_stopped:
            output_callback("\nPattern detection completed.\n")

    def _invoke_explorer_in_process(self, output_callback: Callable[[str], None]) -> None:
        project_path = self.arguments.dot_dp

        output_callback("Loading explorer configuration...\n")

        missing_files = self._get_missing_required_explorer_files(project_path)
        if missing_files:
            output_callback("\nMissing required files:\n")
            for file_path in missing_files:
                output_callback(f"  - {file_path}\n")
            raise RuntimeError("Missing required profiling data files")

        assert self.pattern_types_vars is not None
        assert self.jobs_var is not None
        assert self.explorer_visualization_frame is not None

        selected_patterns = [pattern for pattern, var in self.pattern_types_vars.items() if var.get()]
        enable_patterns = ",".join(selected_patterns) if selected_patterns else "reduction,doall"
        jobs_value = widgets.thread_value(self.jobs_var)
        ignore_states = self._ignore_dependency_states()

        output_callback("Configuration:\n")
        output_callback(f"  Patterns: {enable_patterns}\n")
        output_callback(f"  Threads: {jobs_value}\n")
        output_callback(f"  Dependency data: {NO_STATES_DETECTION_MODE if ignore_states else DEFAULT_DETECTION_MODE}\n")
        output_callback("  Graph visualization: enabled\n\n")

        # discard widgets from a previous visualized run; WithSidebar always builds
        # a fresh layout into the given frame and never clears prior content itself
        for child in self.explorer_visualization_frame.winfo_children():
            child.destroy()

        argv = [
            "--path",
            project_path,
            "--enable-patterns",
            enable_patterns,
            "--log",
            "WARNING",
            "--visualize",
        ]
        if jobs_value != "auto":
            argv.extend(["-j", jobs_value])
        if ignore_states:
            argv.append("--ignore-dependency-states")

        # lazy import: discopop_explorer is only needed for this in-process path,
        # mirroring discopop_explorer's own lazy import of discopop_gui
        from discopop_explorer.__main__ import parse_args
        from discopop_explorer.discopop_explorer import run as run_explorer

        arguments = parse_args(argv)
        arguments.visualize_on = self.explorer_visualization_frame

        class _TkConsoleWriter:
            def __init__(self, callback: Callable[[str], None], widget: Any) -> None:
                self._callback = callback
                self._widget = widget

            def write(self, text: str) -> None:
                if text:
                    self._callback(text)
                    self._widget.update_idletasks()

            def flush(self) -> None:
                pass

            def isatty(self) -> bool:
                # libraries like tqdm probe isatty() to decide whether to emit
                # terminal control codes; this replacement is not a terminal
                return False

        output_callback("Running pattern detection...\n\n")

        old_stdout = sys.stdout
        sys.stdout = _TkConsoleWriter(output_callback, self)  # type: ignore[assignment]
        try:
            run_explorer(arguments)
        except SystemExit as e:
            raise RuntimeError(f"Explorer exited unexpectedly (code {e.code})") from e
        finally:
            sys.stdout = old_stdout

        if not self._explorer_stopped:
            output_callback("\nPattern detection completed.\n")

    def _update_pattern_detection_tab_state(self, enabled: bool) -> None:
        try:
            if enabled:
                self.right_tabs.tab(self.pattern_detection_tab_index, state="normal")
            else:
                self.right_tabs.tab(self.pattern_detection_tab_index, state="disabled")
        except tk.TclError:
            pass

    def _update_autotuning_tab_state(self, enabled: bool) -> None:
        try:
            if not hasattr(self, "autotuning_tab_index"):
                return
            if enabled:
                self.right_tabs.tab(self.autotuning_tab_index, state="normal")
            else:
                self.right_tabs.tab(self.autotuning_tab_index, state="disabled")
        except tk.TclError:
            pass

    def _on_pattern_detection_complete(self, error: bool = False) -> None:
        self.explorer_running = False

        if self.explorer_run_button is not None:
            self.explorer_run_button.config(state="normal", text="Run Pattern Detection")

        if self.explorer_stop_button is not None:
            self.explorer_stop_button.config(state="disabled")

        self._update_pattern_detection_ui()
        self._refresh_suggestion_selection_display()

        if not error:
            self.status_label.config(text="Pattern detection completed successfully", foreground=widgets.STATUS_OK)
            self.after(3000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore
        else:
            self.status_label.config(text="Pattern detection failed", foreground=widgets.STATUS_FAIL)
            self.after(3000, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore

    def _stop_pattern_detection(self) -> None:
        self._explorer_stopped = True
        if self._explorer_process is not None:
            try:
                os.killpg(os.getpgid(self._explorer_process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                self._explorer_process.terminate()
        if self.explorer_stop_button is not None:
            self.explorer_stop_button.config(state="disabled")
        self.status_label.config(text="Stopping pattern detection...", foreground=widgets.STATUS_STOP)
