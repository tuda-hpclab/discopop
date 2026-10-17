# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import os
import json
import tkinter as tk
from tkinter import ttk
from typing import Optional, List, Tuple, Union
from discopop_library.ProjectManager.services.derived_settings import derive_settings
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services.configurations import (
    WizardData,
    write_seq_settings,
    write_shared_compile_script,
    write_wizard_configuration,
)
from discopop_library.ProjectManager.gui.job_adapter import start_work
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkFinished
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import heading_label
from discopop_library.ProjectManager.gui.wizard_steps import WizardStepsMixin
from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no, show_error


class ConfigurationWizard(WizardStepsMixin, tk.Toplevel):  # type: ignore
    def __init__(self, parent: Union[tk.Tk, tk.Widget], arguments: ProjectManagerArguments) -> None:
        super().__init__(parent)
        self.arguments = arguments
        self.result: Optional[str] = None
        self.title("Configuration Assistant")
        self.geometry("1100x900")
        self.minsize(900, 700)
        self.resizable(True, True)

        self.step_index = 0
        self.step_frames: List[ttk.Frame] = []
        self.step_data = WizardData()
        self._compile_sh_has_placeholder = False
        self._execute_sh_has_placeholder = False

        self._setup_ui()
        self._show_step(0)
        self.grab_set()
        self.transient(parent)  # type: ignore[arg-type]
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _setup_ui(self) -> None:
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        step_indicator_frame = ttk.Frame(main_frame)
        step_indicator_frame.pack(fill=tk.X, pady=(0, 10))

        self.step_label = heading_label(step_indicator_frame, "")
        self.step_label.pack(anchor=tk.W)

        nav_frame = ttk.Frame(main_frame)
        nav_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        self.back_btn = widgets.create_button(nav_frame, text="< Back", command=self._on_back)
        self.back_btn.pack(side=tk.LEFT, padx=5)

        self.next_btn = widgets.primary_button(nav_frame, text="Next >", command=self._on_next)
        self.next_btn.pack(side=tk.LEFT, padx=5)

        self.cancel_btn = widgets.create_button(nav_frame, text="Cancel", command=self._on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT, padx=5)

        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.step_frames = [
            self._create_step_welcome(content_frame),
            self._create_step_write_access_check(content_frame),
            self._create_step_compile_sh(content_frame),
            self._create_step_seq_settings(content_frame),
            self._create_step_test_compilation(content_frame),
            self._create_step_derived_settings(content_frame),
            self._create_step_execute_sh(content_frame),
            self._create_step_validate_sh(content_frame),
        ]

    def _show_step(self, step_index: int) -> None:
        for frame in self.step_frames:
            frame.pack_forget()
        self.step_frames[step_index].pack(fill=tk.BOTH, expand=True)

        step_titles = [
            "Welcome",
            "Write Permissions Check",
            "Compilation Script",
            "Compilation Settings",
            "Test Compilation",
            "Derived Settings",
            "Execution Script",
            "Validation Script",
        ]
        total_steps = len(step_titles)
        self.title(f"Configuration Assistant - Step {step_index + 1} of {total_steps}: {step_titles[step_index]}")
        self.step_label.config(text=f"Step {step_index + 1} of {total_steps}: {step_titles[step_index]}")

        self.back_btn.config(state=tk.NORMAL if step_index > 0 else tk.DISABLED)
        if step_index < len(self.step_frames) - 1:
            self.next_btn.config(text="Next >", command=self._on_next)
        else:
            self.next_btn.config(text="Finish", command=self._on_finish)

        self.step_index = step_index

    def _on_next(self) -> None:
        if self.step_index == 0:
            self._show_step(self.step_index + 1)
        elif self.step_index == 1:
            self._show_step(self.step_index + 1)
        elif self.step_index == 2:
            self.step_data.compile_sh = self.compile_sh_text.get(1.0, tk.END)
            compile_sh_content = self.step_data.compile_sh
            if "$CC" not in compile_sh_content and "$CXX" not in compile_sh_content:
                if not ask_yes_no(
                    self,
                    "Missing Compiler Variables",
                    "The compile script does not contain $CC or $CXX variables.\n\n"
                    "This may cause the sequential compilation settings to be ignored.\n\n"
                    "Do you want to continue anyway?",
                ):
                    return
            self._write_compile_sh()
            self._show_step(self.step_index + 1)
        elif self.step_index == 3:
            self.step_data.cc = self.cc_entry.get()
            self.step_data.cxx = self.cxx_entry.get()
            self.step_data.cflags = self.cflags_entry.get()
            self.step_data.cxxflags = self.cxxflags_entry.get()
            self._write_seq_settings()
            self._show_step(self.step_index + 1)
        elif self.step_index == 4:
            self._show_step(self.step_index + 1)
            self._compute_and_display_derived_settings()
        elif self.step_index == 5:
            self._save_derived_settings()
            self._show_step(self.step_index + 1)
        elif self.step_index == 6:
            config_name = self.config_name_entry.get().strip()
            if not config_name:
                show_error(self, "Invalid Configuration Name", "Configuration name cannot be empty.")
                return
            self.step_data.config_name = config_name
            self.step_data.execute_sh = self.execute_sh_text.get(1.0, tk.END)
            self._show_step(self.step_index + 1)
        else:
            self._show_step(self.step_index + 1)

    def _on_back(self) -> None:
        if self.step_index > 0:
            self._show_step(self.step_index - 1)

    def _on_cancel(self) -> None:
        if ask_yes_no(self, "Cancel", "Are you sure you want to cancel the wizard?"):
            self.grab_release()
            self.destroy()

    def _on_finish(self) -> None:
        self.step_data.validate_sh = self.validate_sh_text.get(1.0, tk.END)
        self.step_data.validate_compile_sh = self.validate_compile_sh_text.get(1.0, tk.END)

        try:
            self._finish_wizard()
        except Exception as e:
            show_error(self, "Error", f"Failed to create configuration: {e}")

    def _write_compile_sh(self) -> None:
        write_shared_compile_script(self.arguments.project_config_dir, self.step_data)

    def _write_seq_settings(self) -> None:
        write_seq_settings(self.arguments.project_config_dir, self.step_data)

    def _run_test_compilation(self) -> None:
        from discopop_library.ProjectManager.configurations.execution import execute_configuration

        compile_sh_path = os.path.join(self.arguments.project_config_dir, "compile.sh")
        seq_settings_path = os.path.join(self.arguments.project_config_dir, "seq_settings.json")

        self.test_output_text.config(state=tk.NORMAL)
        self.test_output_text.delete(1.0, tk.END)
        self.test_output_text.config(state=tk.DISABLED)
        self.test_status_label.config(text="Running...", foreground=widgets.STATUS_BUSY)
        self.run_test_btn.config(state=tk.DISABLED)
        self.next_btn.config(state=tk.DISABLED)

        def append_output(text: str) -> None:
            self.test_output_text.config(state=tk.NORMAL)
            self.test_output_text.insert(tk.END, text)
            self.test_output_text.see(tk.END)
            self.test_output_text.config(state=tk.DISABLED)

        args_copy = copy.copy(self.arguments)

        def compile_once(_ctx: WorkContext) -> Optional[Tuple[int, float, str, str]]:
            return execute_configuration(
                args_copy,
                args_copy.project_root,
                args_copy.project_config_dir,
                seq_settings_path,
                compile_sh_path,
                1,
                args_copy.timeout_compilation,
                # a test compilation is no run of a configuration
                store_result=False,
            )

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            result = event.result if event.error is None else None
            if event.error is not None:
                append_output(f"Compilation failed: {event.error}\n")
                self.test_status_label.config(text="✗ Failed", foreground=widgets.STATUS_FAIL)
            elif result is None:
                append_output("Compilation failed: settings file not found.\n")
                self.test_status_label.config(text="✗ Failed", foreground=widgets.STATUS_FAIL)
            else:
                ret_code, elapsed, stdout, stderr = result
                if ret_code == 0:
                    append_output(f"Compilation succeeded ({elapsed:.2f}s)\n")
                    self.test_status_label.config(text="✓ Success", foreground=widgets.STATUS_OK)
                else:
                    append_output(f"Compilation failed (return code: {ret_code}, {elapsed:.2f}s)\n")
                    self.test_status_label.config(
                        text=f"✗ Failed (exit code: {ret_code})", foreground=widgets.STATUS_FAIL
                    )
                if stdout:
                    append_output(f"stdout:\n{stdout}\n")
                if stderr:
                    append_output(f"stderr:\n{stderr}\n")
            self.run_test_btn.config(state=tk.NORMAL)
            self.next_btn.config(state=tk.NORMAL)

        start_work(self, compile_once, handle)

    def _compute_and_display_derived_settings(self) -> None:
        seq_settings = {
            "CC": self.step_data.cc,
            "CXX": self.step_data.cxx,
            "CFLAGS": self.step_data.cflags,
            "CXXFLAGS": self.step_data.cxxflags,
        }

        derived = derive_settings(seq_settings)
        dp_settings = derived["dp"]
        hd_settings = derived["hd"]
        par_settings = derived["par"]

        self.step_data.derived_settings = {
            "dp_settings": dp_settings,
            "hd_settings": hd_settings,
            "par_settings": par_settings,
        }

        self.dp_settings_text.delete(1.0, tk.END)
        self.dp_settings_text.insert(1.0, json.dumps(dp_settings, indent=2))

        self.hd_settings_text.delete(1.0, tk.END)
        self.hd_settings_text.insert(1.0, json.dumps(hd_settings, indent=2))

        self.par_settings_text.delete(1.0, tk.END)
        self.par_settings_text.insert(1.0, json.dumps(par_settings, indent=2))

    def _save_derived_settings(self) -> None:
        try:
            dp_content: str = self.dp_settings_text.get(1.0, tk.END).strip()
            hd_content: str = self.hd_settings_text.get(1.0, tk.END).strip()
            par_content: str = self.par_settings_text.get(1.0, tk.END).strip()

            dp_settings = json.loads(dp_content)
            hd_settings = json.loads(hd_content)
            par_settings = json.loads(par_content)

            dp_path: str = os.path.join(self.arguments.project_config_dir, "dp_settings.json")
            hd_path: str = os.path.join(self.arguments.project_config_dir, "hd_settings.json")
            par_path: str = os.path.join(self.arguments.project_config_dir, "par_settings.json")

            with open(dp_path, "w") as f:
                json.dump(dp_settings, f, indent=2)

            with open(hd_path, "w") as f:
                json.dump(hd_settings, f, indent=2)

            with open(par_path, "w") as f:
                json.dump(par_settings, f, indent=2)

        except json.JSONDecodeError as e:
            show_error(self, "Invalid JSON", f"One of the derived settings contains invalid JSON: {e}")
            raise

    def _finish_wizard(self) -> None:
        config_name = write_wizard_configuration(self.arguments, self.step_data)

        self.result = config_name
        self.grab_release()
        self.destroy()
