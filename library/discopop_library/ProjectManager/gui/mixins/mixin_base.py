# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Any, Optional, Dict

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.gui.mixins.helpers import Tooltip


class ConfigManagerMixinBase:
    """Base class declaring the interface expected by all ConfigManagerApp mixins."""

    # Core attributes
    arguments: ProjectManagerArguments
    config_dir: str
    current_config: Optional[str]
    was_initialized: bool

    # UI elements - main layout
    paned: tk.PanedWindow
    status_label: ttk.Label
    tooltip: Optional[Tooltip]
    right_tabs: ttk.Notebook
    editor_tab_index: int

    # Left panel - configuration list
    listbox: tk.Listbox
    new_button: RoundedButton
    edit_compilation_button: RoundedButton

    # Editor tab
    text_areas: Dict[str, tk.Text]
    modified_files: Dict[str, bool]
    save_button: RoundedButton
    editor_notebook: ttk.Notebook
    editor_sub_tab_index: Dict[str, int]
    editor_sub_tab_labels: Dict[str, str]
    compile_override_button: RoundedButton
    validate_script_button: RoundedButton
    validation_compile_override_button: RoundedButton
    # Execution time setting of execute.sh (stored per configuration in
    # execution_time.json). Not a text area, hence its own dirty flag.
    execution_time_enabled_var: tk.BooleanVar
    execution_time_regex_var: tk.StringVar
    execution_time_regex_entry: ttk.Entry
    execution_time_test_button: RoundedButton
    execution_time_test_label: ttk.Label
    execution_time_modified: bool
    _execution_time_traced: bool
    _execution_time_loading: bool

    # Pattern Detection tab
    pattern_detection_tab_index: int

    # Hotspot Detection tab
    hotspot_tab_index: int

    # Execute panel elements
    mode_vars: Dict[str, tk.BooleanVar]
    mode_checkbuttons: Dict[str, ttk.Checkbutton]
    thread_var: tk.IntVar
    execution_repetitions_var: tk.IntVar
    label_prefix_var: tk.StringVar
    timeout_execution_var: tk.IntVar
    timeout_compilation_var: tk.IntVar
    timeout_validation_var: tk.IntVar
    log_level_var: tk.StringVar
    execution_time_summary_label: ttk.Label
    inplace_var: tk.BooleanVar
    skip_cleanup_var: tk.BooleanVar
    run_button: RoundedButton
    prepare_pattern_detection_button: RoundedButton
    output_text: scrolledtext.ScrolledText
    generate_report_button: RoundedButton

    # Report panel elements
    results_tree: ttk.Treeview
    view_report_button: RoundedButton
    reload_report_button: RoundedButton

    # Compilation editor
    compilation_editor_open: bool
    compilation_text_areas: Dict[str, tk.Text]
    compilation_modified_files: Dict[str, bool]
    compilation_notebook: Optional[ttk.Notebook]
    compilation_tabs: Dict[str, int]
    compilation_tab_tooltips: Dict[int, tuple[str, Tooltip]]
    compilation_tooltip_timer: Optional[str]
    current_tooltip_tab: Optional[int]
    test_compilation_button: RoundedButton
    derive_compilation_button: RoundedButton
    shared_validation_compile_button: RoundedButton
    derive_button_tooltip: Optional[Tooltip]
    derive_button_tooltip_timer: Optional[str]

    # Pattern Detection panel elements
    explorer_output_text: Optional[scrolledtext.ScrolledText]
    explorer_run_button: Optional[RoundedButton]
    browse_suggestions_button: Optional[RoundedButton]
    explorer_running: bool
    pattern_types_vars: Optional[Dict[str, tk.BooleanVar]]
    jobs_var: Optional[tk.StringVar]
    hotspot_hint_frame: Optional[ttk.LabelFrame]

    # Apply Suggestions (Execute tab)
    suggestions_mode_var: tk.StringVar
    suggestions_count_label: ttk.Label
    autotuner_suggestions_info_label: ttk.Label
    execute_suggestion_selector: SuggestionSelector

    # Hotspot Detection panel elements
    hotspot_output_text: Optional[scrolledtext.ScrolledText]
    hotspot_run_button: Optional[RoundedButton]
    hotspot_running: bool
    hotspot_repetitions_var: Optional[tk.IntVar]
    hotspot_notebook: Optional[ttk.Notebook]
    hotspot_regions_tree: Optional[ttk.Treeview]
    hotspot_runs_tree: Optional[ttk.Treeview]

    # Autotuning panel elements
    autotuning_output_text: Optional[scrolledtext.ScrolledText]
    autotuning_run_button: Optional[RoundedButton]
    autotuning_config_label: Optional[ttk.Label]
    autotuning_running: bool
    autotuning_threads_var: Optional[tk.StringVar]
    autotuning_hotspot_types_vars: Optional[Dict[str, tk.BooleanVar]]
    autotuning_algorithm_var: Optional[tk.StringVar]
    autotuning_log_level_var: Optional[tk.StringVar]
    autotuning_suggestions_label: Optional[ttk.Label]
    autotuning_tab_index: int

    # Patch Repair panel elements
    patch_repair_running: bool
    patch_repair_tab_index: int
    patch_repair_output_text: Optional[scrolledtext.ScrolledText]
    patch_repair_run_button: Optional[RoundedButton]
    patch_repair_stop_button: Optional[RoundedButton]
    patch_repair_config_label: Optional[ttk.Label]
    patch_repair_hotspot_types_vars: Optional[Dict[str, tk.BooleanVar]]
    patch_repair_backend_var: Optional[tk.StringVar]
    patch_repair_model_var: Optional[tk.StringVar]
    patch_repair_prompts_var: Optional[tk.StringVar]
    patch_repair_retries_var: Optional[tk.StringVar]
    patch_repair_timeout_var: Optional[tk.StringVar]
    patch_repair_dry_run_var: Optional[tk.BooleanVar]
    patch_repair_log_level_var: Optional[tk.StringVar]
    autotuning_suggestions_mode_var: tk.StringVar
    autotuner_search_space_selector: SuggestionSelector
    autotuner_evaluate_selector: SuggestionSelector

    # Methods that mixins call on each other
    # Note: Methods from tk.Tk (after, after_cancel, bind, wait_window, update_idletasks)
    # are inherited at runtime and should not be defined here as stubs - they would
    # shadow the real implementations due to MRO

    def _set_status(self, text: str, fg: str = widgets.STATUS_IDLE, *, reset_delay: Optional[int] = None) -> None:
        """Set status label text and optionally schedule a reset to 'Ready' after reset_delay ms."""
        self.status_label.config(text=text, foreground=fg)
        if reset_delay is not None:
            self.after(reset_delay, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore

    def _load_config(self) -> None:
        """Load configuration from disk."""
        ...

    def _save_config(self) -> None:
        """Save configuration to disk."""
        ...

    def _refresh_config_list(self) -> None:
        """Refresh the configuration list display."""
        ...

    def _on_config_selected(self, event: Any) -> None:
        """Handle configuration selection."""
        ...

    def _update_execute_modes(self) -> None:
        """Update execution mode availability."""
        ...

    def _build_execute_panel(self, parent: tk.Widget) -> None:
        """Build the execute panel UI."""
        ...

    def _build_report_panel(self, parent: tk.Widget) -> None:
        """Build the report panel UI."""
        ...

    def _update_report_display(self) -> None:
        """Update the report display."""
        ...

    def _validate_execution_inputs(self) -> bool:
        """Validate execution input fields."""
        return True

    def _run_execution(self) -> None:
        """Run the execution."""
        ...

    def _prepare_pattern_detection(self) -> None:
        """Prepare for pattern detection with pre-configured parameters."""
        ...

    def _open_compilation_editor(self) -> None:
        """Open the compilation editor."""
        ...

    def _update_derive_button_state(self) -> None:
        """Update the derive button state."""
        ...

    def _new_config(self) -> None:
        """Create a new configuration."""
        ...

    def _copy_config(self) -> None:
        """Copy a configuration."""
        ...

    def _rename_config(self) -> None:
        """Rename a configuration."""
        ...

    def _delete_config(self) -> None:
        """Delete a configuration."""
        ...

    def _generate_report(self) -> None:
        """Generate a report."""
        ...

    def _view_report(self) -> None:
        """View the report."""
        ...

    def _reset_execution_results(self) -> None:
        """Reset execution results."""
        ...

    def _reset_project_data(self) -> None:
        """Reset project data."""
        ...

    def _maybe_open_wizard(self) -> None:
        """Maybe open the configuration wizard."""
        ...

    def _handle_save_shortcut(self) -> None:
        """Handle save shortcut."""
        ...

    def _start_modification_polling(self) -> None:
        """Start polling for file modifications."""
        ...

    def _check_modification(self, filename: str) -> None:
        """Check if a file has been modified."""
        ...

    def _check_compilation_modification(self, filename: str) -> None:
        """Check if a compilation file has been modified."""
        ...

    def _save_compilation_files(self) -> None:
        """Save compilation files."""
        ...

    def _get_help_command(self, filename: str) -> Optional[Any]:
        """Get the help command for a file."""
        ...

    def _format_json_content(self, content: str) -> str:
        """Format JSON content."""
        return ""

    def _run_test_compilation(self) -> None:
        """Run a test compilation."""
        ...

    def _on_config_right_click(self, event: Any) -> None:
        """Handle right-click on configuration."""
        ...

    def _build_pattern_detection_panel(self, parent: tk.Widget) -> None:
        """Build the pattern detection panel UI."""
        ...

    def _update_pattern_detection_ui(self) -> None:
        """Update the pattern detection UI based on prerequisites."""
        ...

    def _run_pattern_detection(self) -> None:
        """Run the pattern detection."""
        ...

    def _update_hotspot_hint(self) -> None:
        """Show or hide the 'no hotspot results' hint in the Pattern Detection tab."""
        ...

    def _update_pattern_detection_tab_state(self, enabled: bool) -> None:
        """Update the pattern detection tab enabled/disabled state."""
        ...

    def _open_suggestion_browser(self) -> None:
        """Open the suggestion browser dialog."""
        ...

    def _refresh_suggestion_selection_display(self) -> None:
        """Refresh the suggestion selection count label in the Execute tab."""
        ...

    def _build_hotspot_panel(self, parent: tk.Widget) -> None:
        """Build the hotspot detection panel UI."""
        ...

    def _update_hotspot_ui(self) -> None:
        """Update the hotspot detection button states and status block."""
        ...

    def _refresh_hotspot_results(self) -> None:
        """Reload Hotspots.json and the measurement run log, then refresh the views."""
        ...

    def _update_hotspot_config_display(self) -> None:
        """Refresh the parts of the hotspot panel that depend on the selected config."""
        ...

    def _build_patch_repair_panel(self, parent: tk.Widget) -> None:
        """Build the patch repair panel UI."""
        ...

    def _update_patch_repair_ui(self) -> None:
        """Enable or disable the patch repair panel based on the available patches."""
        ...

    def _update_patch_repair_config_display(self) -> None:
        """Update the configuration display label in the patch repair panel."""
        ...

    def _build_autotuning_panel(self, parent: tk.Widget) -> None:
        """Build the autotuning panel UI."""
        ...

    def _update_autotuning_ui(self) -> None:
        """Update the autotuning UI based on suggestion availability."""
        ...

    def _refresh_autotuning_suggestions_display(self) -> None:
        """Refresh the selected suggestions display in the autotuning panel."""
        ...

    def _update_autotuning_config_display(self) -> None:
        """Update the configuration display label in the autotuning panel."""
        ...
