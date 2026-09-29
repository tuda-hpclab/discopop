# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from discopop_library.ProjectManager.utilities.initializeFiles import (
    initial_settings_content,
    initial_script_content,
)
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.widgets import (
    create_styled_output_console,
    create_script_editor,
    heading_label,
)
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import enable_text_context_menu


class WizardStepsMixin(ConfigManagerMixinBase):
    def _create_step_welcome(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        intro = """Welcome to the Configuration Assistant

This wizard will guide you through the steps necessary to create a valid and complete configuration for DiscoPoP profiling.

The wizard will help you with:

1. Specifying the compilation script (compile.sh)
2. Configuring compilation settings (compilers and flags)
3. Testing the compilation configuration
4. Reviewing and accepting derived settings files
5. Specifying the execution script and naming your configuration
6. Optionally specifying an output validation script (validate.sh), plus a separate
   compilation script for it if validation needs a different build

After completing this wizard, your project will be ready to use with DiscoPoP.

Click "Next >" to begin."""
        label = ttk.Label(frame, text=intro, font=widgets.FONT_BODY, justify=tk.LEFT, wraplength=900)
        label.pack(anchor=tk.NW, padx=10, pady=15)
        return frame

    def _create_step_write_access_check(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        parent_folder = os.path.dirname(self.arguments.project_root)
        has_write_access = os.access(parent_folder, os.W_OK)

        if has_write_access:
            status_text = "✓ Write Access Available"
            status_color = widgets.STATUS_OK
            description = """Write access to the parent folder has been detected.

This allows DiscoPoP to automatically create and delete temporary project copies
during execution, which enables non-inplace mode for testing and validation.

You can proceed with the wizard configuration."""
        else:
            status_text = "⚠ No Write Access"
            status_color = widgets.STATUS_STOP
            description = """Write access to the parent folder is not available.

Executions will be limited to "inplace" mode, where the project directory is
modified directly. Temporary project copies cannot be created.

You can still proceed with the configuration, but keep this limitation in mind."""

        status_label = heading_label(frame, status_text, foreground=status_color)
        status_label.pack(anchor=tk.W, padx=10, pady=(15, 10))

        description_label = ttk.Label(frame, text=description, font=widgets.FONT_BODY, justify=tk.LEFT, wraplength=900)
        description_label.pack(anchor=tk.NW, padx=10, pady=10)

        return frame

    def _create_step_compile_sh(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        hint_text = (
            "Specify the compilation script. It is executed from the project root directory.\n\n"
            "Requirements:\n"
            "  • Use $CC / $CXX and $CFLAGS / $CXXFLAGS for all compile commands.\n"
            "  • The script must return exit code 0 on success.\n\n"
            "You can use relative paths as if you are already in the project root.\n"
            "See the wiki for examples: https://tuda-hpclab.github.io/discopop/"
        )
        hint = ttk.Label(frame, text=hint_text, font=widgets.FONT_BODY, justify=tk.LEFT)
        hint.pack(anchor=tk.W, padx=5, pady=(5, 10))

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.compile_sh_text = create_script_editor(frame, height=14, width=80, yscrollcommand=scrollbar.set)
        self.compile_sh_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=self.compile_sh_text.yview)
        enable_text_context_menu(self.compile_sh_text)

        self.compile_sh_text.tag_config("placeholder", foreground=widgets.PLACEHOLDER_FG)
        self._compile_sh_has_placeholder = False

        compile_sh_path = os.path.join(self.arguments.project_config_dir, "compile.sh")
        if os.path.exists(compile_sh_path):
            with open(compile_sh_path, "r") as f:
                existing = f.read()
            if existing.strip() != initial_script_content.strip():
                self.compile_sh_text.insert(1.0, existing)
                return frame

        self.compile_sh_text.insert(1.0, "#!/bin/bash\n")
        self.compile_sh_text.insert("2.0", "$CXX your_code.cpp -o a.out", "placeholder")
        self._compile_sh_has_placeholder = True

        self.compile_sh_text.bind("<KeyPress>", self._on_compile_sh_interact)
        self.compile_sh_text.bind("<Button-1>", self._on_compile_sh_interact)

        return frame

    def _on_compile_sh_interact(self, event: Any) -> None:
        """Remove placeholder text when user interacts with compile.sh editor."""
        if not self._compile_sh_has_placeholder:
            return
        self._remove_compile_sh_placeholder()

    def _remove_compile_sh_placeholder(self) -> None:
        """Remove the grey placeholder text."""
        if not self._compile_sh_has_placeholder:
            return

        self._compile_sh_has_placeholder = False
        line2_text = self.compile_sh_text.get("2.0", "2.end")
        if line2_text == "$CXX your_code.cpp -o a.out":
            self.compile_sh_text.delete("2.0", "3.0")
            self.compile_sh_text.insert("1.end", "\n")
        self.compile_sh_text.mark_set("insert", "2.0")
        self.compile_sh_text.unbind("<KeyPress>")
        self.compile_sh_text.unbind("<Button-1>")

    def _create_step_seq_settings(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        hint = ttk.Label(
            frame,
            text="Configure your compilation settings. These will be used to compile your project.",
            font=widgets.FONT_BODY,
        )
        hint.pack(anchor=tk.W, padx=5, pady=(5, 10))

        form_frame = ttk.Frame(frame)
        form_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(form_frame, text="C Compiler (CC):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.cc_entry = ttk.Entry(form_frame, width=40)
        self.cc_entry.grid(row=0, column=1, sticky=tk.W, padx=10)

        ttk.Label(form_frame, text="C++ Compiler (CXX):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.cxx_entry = ttk.Entry(form_frame, width=40)
        self.cxx_entry.grid(row=1, column=1, sticky=tk.W, padx=10)

        ttk.Label(form_frame, text="C Flags (CFLAGS):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.cflags_entry = ttk.Entry(form_frame, width=40)
        self.cflags_entry.grid(row=2, column=1, sticky=tk.W, padx=10)

        ttk.Label(form_frame, text="C++ Flags (CXXFLAGS):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.cxxflags_entry = ttk.Entry(form_frame, width=40)
        self.cxxflags_entry.grid(row=3, column=1, sticky=tk.W, padx=10)

        import json

        seq_settings_path = os.path.join(self.arguments.project_config_dir, "seq_settings.json")
        if os.path.exists(seq_settings_path):
            with open(seq_settings_path, "r") as f:
                settings = json.load(f)
        else:
            settings = initial_settings_content

        self.cc_entry.insert(0, settings.get("CC", "clang"))
        self.cxx_entry.insert(0, settings.get("CXX", "clang++"))
        self.cflags_entry.insert(0, settings.get("CFLAGS", ""))
        self.cxxflags_entry.insert(0, settings.get("CXXFLAGS", ""))

        return frame

    def _create_step_test_compilation(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        hint = ttk.Label(
            frame,
            text="Click 'Run Test Compilation' to verify your compilation script works.",
            font=widgets.FONT_BODY,
        )
        hint.pack(anchor=tk.W, padx=5, pady=(5, 10))

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, padx=10, pady=5)

        self.run_test_btn = widgets.primary_button(
            button_frame, text="Run Test Compilation", command=self._run_test_compilation
        )
        self.run_test_btn.pack(side=tk.LEFT)

        self.test_status_label = ttk.Label(button_frame, text="", font=widgets.FONT_BODY)
        self.test_status_label.pack(side=tk.LEFT, padx=10)

        self.test_output_text = create_styled_output_console(frame)
        self.test_output_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        return frame

    def _create_step_derived_settings(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        hint = ttk.Label(
            frame,
            text="Review and accept the derived settings. You can edit them before continuing.",
            font=widgets.FONT_BODY,
        )
        hint.pack(anchor=tk.W, padx=5, pady=(5, 10))

        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.dp_settings_text = create_script_editor(notebook, height=15, width=80)
        notebook.add(self.dp_settings_text, text="dp_settings.json")
        enable_text_context_menu(self.dp_settings_text)

        self.hd_settings_text = create_script_editor(notebook, height=15, width=80)
        notebook.add(self.hd_settings_text, text="hd_settings.json")
        enable_text_context_menu(self.hd_settings_text)

        self.par_settings_text = create_script_editor(notebook, height=15, width=80)
        notebook.add(self.par_settings_text, text="par_settings.json")
        enable_text_context_menu(self.par_settings_text)

        self.notebook = notebook
        return frame

    def _create_step_execute_sh(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        config_frame = ttk.Frame(frame)
        config_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

        ttk.Label(config_frame, text="Configuration Name:", font=widgets.FONT_BODY).pack(anchor=tk.W, pady=5)
        self.config_name_entry = ttk.Entry(config_frame, width=40)
        self.config_name_entry.pack(anchor=tk.W)
        self.config_name_entry.insert(0, "default")

        hint_text = (
            "Specify a minimal execution script to validate the instrumentation.\n"
            "More detailed configurations can be added afterwards.\n\n"
            "Requirements:\n"
            "  • The script must execute the program created by the previously defined compilation.\n"
            "  • The script must return exit code 0 on success.\n\n"
            "You can use relative paths as if you are already in the project root.\n"
            "See the wiki for examples: https://tuda-hpclab.github.io/discopop/"
        )
        hint = ttk.Label(frame, text=hint_text, font=widgets.FONT_BODY, justify=tk.LEFT)
        hint.pack(anchor=tk.W, padx=5, pady=(0, 10))

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.execute_sh_text = create_script_editor(frame, height=14, width=80, yscrollcommand=scrollbar.set)
        self.execute_sh_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=self.execute_sh_text.yview)
        enable_text_context_menu(self.execute_sh_text)

        self.execute_sh_text.tag_config("placeholder", foreground=widgets.PLACEHOLDER_FG)
        self._execute_sh_has_placeholder = False

        self.execute_sh_text.insert(1.0, "#!/bin/bash\n")
        self.execute_sh_text.insert("2.0", "./a.out <args>", "placeholder")
        self._execute_sh_has_placeholder = True

        self.execute_sh_text.bind("<KeyPress>", self._on_execute_sh_interact)
        self.execute_sh_text.bind("<Button-1>", self._on_execute_sh_interact)

        return frame

    def _create_step_validate_sh(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)

        hint_text = (
            "Optionally specify a validation script (validate.sh).\n\n"
            "Leave empty to skip. If provided, validate.sh re-runs the program and validates its\n"
            "output separately from the timed execute.sh run (e.g. a diff against a reference).\n"
            "A run then counts as correct only if BOTH execute.sh and validate.sh exit 0.\n\n"
            "You can use relative paths as if you are already in the project root."
        )
        hint = ttk.Label(frame, text=hint_text, font=widgets.FONT_BODY, justify=tk.LEFT)
        hint.pack(anchor=tk.W, padx=5, pady=(5, 10))

        validate_frame = ttk.LabelFrame(frame, text="validate.sh")
        validate_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        scrollbar = ttk.Scrollbar(validate_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.validate_sh_text = create_script_editor(validate_frame, height=9, width=80, yscrollcommand=scrollbar.set)
        self.validate_sh_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=self.validate_sh_text.yview)
        enable_text_context_menu(self.validate_sh_text)

        validate_compile_frame = ttk.LabelFrame(
            frame, text="compile_validate.sh — only if validation needs a different build"
        )
        validate_compile_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        validate_compile_hint = ttk.Label(
            validate_compile_frame,
            text=(
                "Leave empty to build validate.sh's code with compile.sh, as usual. If filled in, this\n"
                "script is compiled after the timed execute.sh run and before validate.sh, so the extra\n"
                "build never affects the measured runtime. Use $CC / $CXX and $CFLAGS / $CXXFLAGS."
            ),
            font=widgets.FONT_BODY,
            justify=tk.LEFT,
        )
        validate_compile_hint.pack(anchor=tk.W, padx=5, pady=(5, 0))

        validate_compile_scrollbar = ttk.Scrollbar(validate_compile_frame)
        validate_compile_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.validate_compile_sh_text = create_script_editor(
            validate_compile_frame, height=7, width=80, yscrollcommand=validate_compile_scrollbar.set
        )
        self.validate_compile_sh_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        validate_compile_scrollbar.config(command=self.validate_compile_sh_text.yview)
        enable_text_context_menu(self.validate_compile_sh_text)

        return frame

    def _on_execute_sh_interact(self, event: Any) -> None:
        """Remove placeholder text when user interacts with execute.sh editor."""
        if not self._execute_sh_has_placeholder:
            return
        self._remove_execute_sh_placeholder()

    def _remove_execute_sh_placeholder(self) -> None:
        """Remove the grey placeholder text from execute.sh editor."""
        if not self._execute_sh_has_placeholder:
            return

        self._execute_sh_has_placeholder = False
        line2_text = self.execute_sh_text.get("2.0", "2.end")
        if line2_text == "./a.out <args>":
            self.execute_sh_text.delete("2.0", "3.0")
            self.execute_sh_text.insert("1.end", "\n")
        self.execute_sh_text.mark_set("insert", "2.0")
        self.execute_sh_text.unbind("<KeyPress>")
        self.execute_sh_text.unbind("<Button-1>")
