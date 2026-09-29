# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Optional
from ttkthemes import ThemedStyle  # type: ignore

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.utilities.initializeFiles import (
    initialize_configuration_files,
)
from discopop_library.ProjectManager.configurations.execution_time import DEFAULT_EXECUTION_TIME_REGEX
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import create_styled_output_console, heading_label
from discopop_library.ProjectManager.gui.mixins.helpers import (
    Tooltip,
    bind_tooltip_hover,
    show_error,
    enable_text_context_menu,
)
from discopop_library.ProjectManager.gui.mixins.execute_panel import ExecutePanelMixin
from discopop_library.ProjectManager.gui.mixins.report_panel import ReportPanelMixin
from discopop_library.ProjectManager.gui.mixins.config_list import ConfigListMixin
from discopop_library.ProjectManager.gui.mixins.file_editor import FileEditorMixin
from discopop_library.ProjectManager.gui.mixins.compilation_editor import CompilationEditorMixin
from discopop_library.ProjectManager.gui.mixins.config_crud import ConfigCrudMixin
from discopop_library.ProjectManager.gui.mixins.execution import ExecutionMixin
from discopop_library.ProjectManager.gui.mixins.report import ReportMixin
from discopop_library.ProjectManager.gui.mixins.help_dialogs import HelpDialogsMixin
from discopop_library.ProjectManager.gui.mixins.wizard_launcher import WizardLauncherMixin
from discopop_library.ProjectManager.gui.mixins.explorer_integration import ExplorerIntegrationMixin
from discopop_library.ProjectManager.gui.mixins.hotspot_panel import HotspotPanelMixin
from discopop_library.ProjectManager.gui.mixins.autotuning_panel import AutotuningPanelMixin
from discopop_library.ProjectManager.gui.mixins.patch_repair_panel import PatchRepairPanelMixin
from discopop_library.ProjectManager.gui.widgets import CATPPUCCIN_CYAN


class ConfigManagerApp(  # type: ignore
    ExecutePanelMixin,
    ReportPanelMixin,
    ConfigListMixin,
    FileEditorMixin,
    CompilationEditorMixin,
    ConfigCrudMixin,
    ExecutionMixin,
    ReportMixin,
    HelpDialogsMixin,
    WizardLauncherMixin,
    ExplorerIntegrationMixin,
    HotspotPanelMixin,
    PatchRepairPanelMixin,
    AutotuningPanelMixin,
    tk.Tk,
):
    def __init__(self, arguments: ProjectManagerArguments, was_initialized: bool = False) -> None:
        super().__init__()
        self.title("DiscoPoP Project Manager")
        self._set_window_icon()
        self.geometry("1600x1000")
        self.minsize(1400, 800)
        self.arguments = arguments
        self.was_initialized = was_initialized

        self.config_dir = arguments.project_config_dir
        self.tooltip: Optional[Tooltip] = None

        self._setup_styles()

        # --- BOTTOM BAR: Status (pack first to keep it at bottom) ---
        bottom_frame = ttk.Frame(self, height=45)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
        bottom_frame.pack_propagate(False)

        self.status_label = ttk.Label(bottom_frame, text="Ready", foreground=widgets.STATUS_IDLE)
        self.status_label.pack(side=tk.LEFT, padx=10, pady=5)

        # Show the path to the currently used .discopop folder, aligned with the status bar.
        # The text is truncated to at most half of the bottom bar's width; the full path is
        # available via a mouse-over tooltip.
        self.dot_dp_path = self.arguments.dot_dp
        self.dot_dp_label = ttk.Label(
            bottom_frame,
            text=self.dot_dp_path,
            foreground=widgets.STATUS_IDLE,
        )
        self.dot_dp_label.pack(side=tk.RIGHT, padx=10, pady=5)

        self._dot_dp_font = tkfont.nametofont(str(self.dot_dp_label.cget("font")) or "TkDefaultFont")
        self._dot_dp_tooltip = Tooltip(self.dot_dp_label, self.dot_dp_path)
        bind_tooltip_hover(self.dot_dp_label, self._dot_dp_tooltip, self)
        bottom_frame.bind("<Configure>", self._update_dot_dp_label)

        # Main layout: PanedWindow with left (configs) and right (editor/execute/report)
        self.paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=18, sashpad=3)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # --- LEFT PANEL: Configuration List ---
        left_frame = ttk.Frame(self.paned)
        left_frame.pack_propagate(False)
        self.paned.add(left_frame, width=280, minsize=220)

        label = heading_label(left_frame, "Run Configs", title=True)
        label.pack(side=tk.TOP, padx=5, pady=5)

        self.listbox = tk.Listbox(
            left_frame,
            selectmode=tk.SINGLE,
            selectbackground=widgets.LISTBOX_SELECT_BG,
            selectforeground=widgets.LISTBOX_SELECT_FG,
            activestyle="none",
        )
        self.listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self._on_config_selected)
        self.listbox.bind("<Button-3>", self._on_config_right_click)

        button_frame = ttk.Frame(left_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        self.new_button = widgets.primary_button(button_frame, text="+ New", command=self._new_config)
        self.new_button.pack(side=tk.TOP, fill=tk.X, pady=2)

        self.edit_compilation_button = widgets.create_button(
            button_frame, text="Edit Compilation", command=self._open_compilation_editor
        )
        self.edit_compilation_button.pack(side=tk.TOP, fill=tk.X, pady=2)

        # --- RIGHT PANEL: Tab switcher (Editor / Execute / Report) ---
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, minsize=600)

        self.right_tabs = ttk.Notebook(right_frame)
        self.right_tabs.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Editor tab
        editor_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(editor_frame, text="Editor")
        self.editor_tab_index = self.right_tabs.index(editor_frame)

        # Execute tab
        execute_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(execute_frame, text="Execute")
        self.execute_tab_index = self.right_tabs.index(execute_frame)

        # Report tab
        report_tab_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(report_tab_frame, text="Report")
        self._build_report_panel(report_tab_frame)

        # Hotspot Detection tab (left of Pattern Detection: hotspots are measured
        # before, and feed into, the optimizer and the autotuner)
        hotspot_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(hotspot_frame, text="Hotspot Detection")
        self.hotspot_tab_index = self.right_tabs.index(hotspot_frame)
        self._build_hotspot_panel(hotspot_frame)

        # Pattern Detection tab
        pattern_detection_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(pattern_detection_frame, text="Pattern Detection")
        self.pattern_detection_tab_index = self.right_tabs.index(pattern_detection_frame)
        self._build_pattern_detection_panel(pattern_detection_frame)

        # Patch Repair tab (between Pattern Detection and Autotuning: the patches exist
        # by now, and a suggestion that does not build is one the tuner can only ever
        # record as a failure)
        patch_repair_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(patch_repair_frame, text="Patch Repair")
        self.patch_repair_tab_index = self.right_tabs.index(patch_repair_frame)
        self._build_patch_repair_panel(patch_repair_frame)

        # Autotuning tab
        autotuning_frame = ttk.Frame(self.right_tabs)
        self.right_tabs.add(autotuning_frame, text="Autotuning")
        self.autotuning_tab_index = self.right_tabs.index(autotuning_frame)
        self._build_autotuning_panel(autotuning_frame)
        self._update_pattern_detection_ui()

        # Content frames for execute.sh and the optional per-configuration scripts
        # (compile.sh override, validate.sh, compile_validate.sh override)
        self.text_areas: dict[str, tk.Text] = {}
        self.modified_files: dict[str, bool] = {}

        # Bottom bar with buttons — packed before the notebook so it always reserves its natural height
        bottom_editor_frame = ttk.Frame(editor_frame)
        bottom_editor_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        # Buttons on the left side
        self.save_button = widgets.primary_button(bottom_editor_frame, text="Save (Ctrl+S)", command=self._save_config)
        self.save_button.pack(side=tk.LEFT, padx=5)

        self.editor_notebook = ttk.Notebook(editor_frame)
        self.editor_notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- execute.sh tab ---
        execute_sh_frame = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(execute_sh_frame, text="execute.sh")

        execute_header_frame = ttk.Frame(execute_sh_frame)
        execute_header_frame.pack(fill=tk.X, padx=5, pady=5)

        execute_help_label = heading_label(execute_header_frame, "Execution script")
        execute_help_label.pack(side=tk.LEFT)

        execute_help_button = widgets.create_button(
            execute_header_frame, text="Help", command=self._show_execute_sh_help
        )
        execute_help_button.pack(side=tk.RIGHT, padx=5)

        # packed before the text area so it always reserves its natural height
        self._build_execution_time_settings(execute_sh_frame)

        execute_text_frame = ttk.Frame(execute_sh_frame)
        execute_text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        execute_scrollbar = ttk.Scrollbar(execute_text_frame)
        execute_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        execute_text_area = widgets.create_script_editor(execute_text_frame, yscrollcommand=execute_scrollbar.set)
        execute_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        execute_scrollbar.config(command=execute_text_area.yview)
        enable_text_context_menu(execute_text_area)

        self.text_areas["execute.sh"] = execute_text_area
        self.modified_files["execute.sh"] = False

        # --- compile.sh override tab ---
        compile_sh_frame = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(compile_sh_frame, text="compile.sh (override)")

        compile_header_frame = ttk.Frame(compile_sh_frame)
        compile_header_frame.pack(fill=tk.X, padx=5, pady=5)

        compile_help_label = heading_label(compile_header_frame, "Compilation script override")
        compile_help_label.pack(side=tk.LEFT)

        compile_help_button = widgets.create_button(
            compile_header_frame, text="Help", command=self._show_compile_sh_help
        )
        compile_help_button.pack(side=tk.RIGHT, padx=5)

        self.compile_override_button = widgets.create_button(
            compile_header_frame, text="Add Override", command=self._toggle_compile_override
        )
        self.compile_override_button.pack(side=tk.RIGHT, padx=5)

        compile_text_frame = ttk.Frame(compile_sh_frame)
        compile_text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        compile_scrollbar = ttk.Scrollbar(compile_text_frame)
        compile_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        compile_text_area = widgets.create_script_editor(compile_text_frame, yscrollcommand=compile_scrollbar.set)
        compile_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        compile_scrollbar.config(command=compile_text_area.yview)
        enable_text_context_menu(compile_text_area)

        self.text_areas["compile.sh"] = compile_text_area
        self.modified_files["compile.sh"] = False

        # --- validate.sh tab (optional, per-configuration) ---
        validate_sh_frame = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(validate_sh_frame, text="validate.sh")

        validate_header_frame = ttk.Frame(validate_sh_frame)
        validate_header_frame.pack(fill=tk.X, padx=5, pady=5)

        validate_help_label = heading_label(validate_header_frame, "Output validation script")
        validate_help_label.pack(side=tk.LEFT)

        validate_help_button = widgets.create_button(
            validate_header_frame, text="Help", command=self._show_validate_sh_help
        )
        validate_help_button.pack(side=tk.RIGHT, padx=5)

        self.validate_script_button = widgets.create_button(
            validate_header_frame, text="Add validate.sh", command=self._toggle_validate_script
        )
        self.validate_script_button.pack(side=tk.RIGHT, padx=5)

        validate_text_frame = ttk.Frame(validate_sh_frame)
        validate_text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        validate_scrollbar = ttk.Scrollbar(validate_text_frame)
        validate_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        validate_text_area = widgets.create_script_editor(validate_text_frame, yscrollcommand=validate_scrollbar.set)
        validate_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        validate_scrollbar.config(command=validate_text_area.yview)
        enable_text_context_menu(validate_text_area)

        self.text_areas["validate.sh"] = validate_text_area
        self.modified_files["validate.sh"] = False

        # --- compile_validate.sh override tab (optional, per-configuration) ---
        validate_compile_frame = ttk.Frame(self.editor_notebook)
        self.editor_notebook.add(validate_compile_frame, text="compile_validate.sh (override)")

        validate_compile_header_frame = ttk.Frame(validate_compile_frame)
        validate_compile_header_frame.pack(fill=tk.X, padx=5, pady=5)

        validate_compile_help_label = heading_label(validate_compile_header_frame, "Validation build script override")
        validate_compile_help_label.pack(side=tk.LEFT)

        validate_compile_help_button = widgets.create_button(
            validate_compile_header_frame, text="Help", command=self._show_validation_compile_sh_help
        )
        validate_compile_help_button.pack(side=tk.RIGHT, padx=5)

        self.validation_compile_override_button = widgets.create_button(
            validate_compile_header_frame, text="Add Override", command=self._toggle_validation_compile_override
        )
        self.validation_compile_override_button.pack(side=tk.RIGHT, padx=5)

        validate_compile_text_frame = ttk.Frame(validate_compile_frame)
        validate_compile_text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        validate_compile_scrollbar = ttk.Scrollbar(validate_compile_text_frame)
        validate_compile_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        validate_compile_text_area = widgets.create_script_editor(
            validate_compile_text_frame, yscrollcommand=validate_compile_scrollbar.set
        )
        validate_compile_text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        validate_compile_scrollbar.config(command=validate_compile_text_area.yview)
        enable_text_context_menu(validate_compile_text_area)

        self.text_areas["compile_validate.sh"] = validate_compile_text_area
        self.modified_files["compile_validate.sh"] = False

        self.editor_sub_tab_index = {
            "execute.sh": self.editor_notebook.index(execute_sh_frame),
            "compile.sh": self.editor_notebook.index(compile_sh_frame),
            "validate.sh": self.editor_notebook.index(validate_sh_frame),
            "compile_validate.sh": self.editor_notebook.index(validate_compile_frame),
        }
        self.editor_sub_tab_labels = {
            "execute.sh": "execute.sh",
            "compile.sh": "compile.sh (override)",
            "validate.sh": "validate.sh",
            "compile_validate.sh": "compile_validate.sh (override)",
        }

        # Build execute panel
        self._build_execute_panel(execute_frame)

        self.current_config: Optional[str] = None
        self.compilation_editor_open = False
        self.compilation_text_areas: dict[str, tk.Text] = {}
        self.compilation_modified_files: dict[str, bool] = {}
        self.compilation_notebook: Optional[ttk.Notebook] = None
        self.compilation_tabs: dict[str, int] = {}
        self.compilation_tab_tooltips: dict[int, tuple[str, Tooltip]] = {}
        self.compilation_tooltip_timer: Optional[str] = None
        self.current_tooltip_tab: Optional[int] = None
        self.derive_button_tooltip: Optional[Tooltip] = None
        self.derive_button_tooltip_timer: Optional[str] = None
        self.bind("<Control-s>", lambda event: self._handle_save_shortcut())
        self._refresh_config_list()
        self.after(100, self._maybe_open_wizard)
        self._start_modification_polling()

    def _update_dot_dp_label(self, event: Optional["tk.Event[tk.Misc]"] = None) -> None:
        """Truncate the .discopop path label to at most half the bottom bar's width.

        If the full path does not fit, it is pruned from the left with a leading
        ellipsis so the most specific part of the path stays visible. The full
        path remains available via the mouse-over tooltip.
        """
        available = self.dot_dp_label.master.winfo_width()
        if available <= 1:
            return
        max_width = available // 2
        full = self.dot_dp_path
        if self._dot_dp_font.measure(full) <= max_width:
            self.dot_dp_label.config(text=full)
            return

        ellipsis = "…"
        truncated = full
        while truncated and self._dot_dp_font.measure(ellipsis + truncated) > max_width:
            truncated = truncated[1:]
        self.dot_dp_label.config(text=ellipsis + truncated)

    def _set_window_icon(self) -> None:
        """Set the DiscoPoP logo as the window / taskbar icon.

        Uses ``iconphoto`` (the portable API: PNG via ``tk.PhotoImage``) with
        ``default=True`` so child toplevels/dialogs inherit it too. The
        PhotoImage is stored on ``self`` because Tk keeps only a weak reference
        and would otherwise garbage-collect the image, silently dropping the
        icon. A missing/unreadable file must not crash the GUI, hence the guard.
        """
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
        try:
            self._window_icon = tk.PhotoImage(file=icon_path)
            self.iconphoto(True, self._window_icon)
        except tk.TclError:
            pass

    def _setup_styles(self) -> None:
        """Single location for all shared ttk styles.

        Named button styles and the Treeview / Notebook tab styling all live
        here so components of the same type look identical wherever they are
        built (the Treeview and TNotebook.Tab styling used to be configured
        ad hoc from report_panel.py and compilation_editor.py).
        """
        style = ThemedStyle(self)

        style.configure(
            "TCombobox",
            fieldbackground="white",
            borderwidth=1,
            relief="solid",
            padding=2,
        )

        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#f0f0f0"), ("active", "white")],
            bordercolor=[("focus", CATPPUCCIN_CYAN)],
        )

        # Semantic button styles
        style.configure(widgets.STYLE_PRIMARY_BUTTON, font=(widgets.FONT_FAMILY, 11, "bold"))
        style.configure(widgets.STYLE_DANGER_BUTTON, foreground=widgets.STATUS_FAIL)
        style.map(widgets.STYLE_DANGER_BUTTON, foreground=[("disabled", widgets.STATUS_IDLE)])
        style.configure(widgets.STYLE_ICON_BUTTON, relief="flat", borderwidth=0, padding=0)

        # Notebook tabs (previously configured globally from compilation_editor.py,
        # which made the styling order-dependent).
        style.configure("TNotebook.Tab", padding=[10, 2], font=widgets.FONT_BODY)

        # Report Treeview (previously configured ad hoc in report_panel.py).
        style.configure(
            "Treeview",
            rowheight=40,
            font=(widgets.FONT_FAMILY, 10),
            fieldbackground=widgets.TREE_BG,
            background=widgets.TREE_BG,
            padding=2,
            bordercolor=widgets.TREE_BORDER,
        )
        style.configure(
            "Treeview.Heading",
            font=(widgets.FONT_FAMILY, 10, "bold"),
            borderwidth=1,
            relief="solid",
        )
        style.map("Treeview.Heading", background=[("", widgets.TREE_HEADING_BG)])
        style.map("Treeview", fieldbackground=[("", widgets.TREE_BG)])

    def _build_execution_time_settings(self, parent: ttk.Frame) -> None:
        """The "read the execution time from the console output" setting of execute.sh.

        It lives in this tab rather than next to the other execution options
        because it is a property of the script it belongs to -- it describes how
        that program reports its own timing -- and it is therefore stored per
        configuration in ``execution_time.json`` and saved with the script.
        """
        frame = ttk.LabelFrame(parent, text="Execution time", padding=5)
        frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)

        self.execution_time_modified = False
        self._execution_time_traced = False
        self._execution_time_loading = False
        self.execution_time_enabled_var = tk.BooleanVar(value=False)
        self.execution_time_regex_var = tk.StringVar(value=DEFAULT_EXECUTION_TIME_REGEX)

        toggle = ttk.Checkbutton(
            frame,
            text="Read the execution time from the program's console output",
            variable=self.execution_time_enabled_var,
            command=self._update_execution_time_state,
        )
        toggle.pack(anchor=tk.W)

        toggle_tooltip = Tooltip(
            toggle,
            "Off: the wall clock time of execute.sh is measured, including setup,\n"
            "teardown and any file I/O it performs.\n"
            "On: the time the program prints itself is used instead. If the pattern\n"
            "finds nothing, the wall clock time is reported and the run is marked\n"
            "as having fallen back to it.",
        )
        bind_tooltip_hover(toggle, toggle_tooltip, self)

        pattern_frame = ttk.Frame(frame)
        pattern_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(pattern_frame, text="Pattern:", width=10, anchor=tk.W).pack(side=tk.LEFT)
        self.execution_time_regex_entry = ttk.Entry(pattern_frame, textvariable=self.execution_time_regex_var)
        self.execution_time_regex_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.execution_time_test_button = widgets.create_button(
            pattern_frame, text="Test", command=self._test_execution_time_regex
        )
        self.execution_time_test_button.pack(side=tk.LEFT, padx=5)

        self.execution_time_hint_label = widgets.caption_label(
            frame,
            "The first capture group holds the value, e.g. Total time:\\s*([0-9.]+) "
            "for a program printing 'Total time: 1.234 seconds'.",
        )
        self.execution_time_hint_label.pack(anchor=tk.W, pady=(3, 0))

        self.execution_time_test_label = ttk.Label(frame, text="")
        self.execution_time_test_label.pack(anchor=tk.W, pady=(3, 0))

        self._update_execution_time_state()


def run_gui(arguments: ProjectManagerArguments) -> None:
    was_initialized = False
    if not os.path.exists(arguments.project_config_dir):
        try:
            from discopop_library.ProjectManager.utilities.initializeDirectories import initialize_directories

            initialize_directories(arguments)
            initialize_configuration_files(arguments)
            was_initialized = True
        except Exception as e:
            root = tk.Tk()
            root.withdraw()
            show_error(
                root,
                "Initialization Error",
                f"Failed to initialize project configuration:\n{e}",
            )
            root.destroy()
            return

    app = ConfigManagerApp(arguments, was_initialized=was_initialized)
    # mainloop() produces no output for as long as the window is open, which a
    # caller that is not a person -- a script, a CI job, an agent -- cannot tell
    # apart from a hang. Name what it is waiting for.
    print("Opening the DiscoPoP Project Manager. Close the window to continue.", file=sys.stderr)
    app.mainloop()
