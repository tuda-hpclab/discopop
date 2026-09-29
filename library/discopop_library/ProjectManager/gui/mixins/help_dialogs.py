# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase


class HelpDialogsMixin(ConfigManagerMixinBase):
    def _show_help_dialog(self, title: str, content: str) -> None:
        help_window = tk.Toplevel(self)  # type: ignore[arg-type]
        help_window.withdraw()
        help_window.title(title)
        help_window.geometry("900x650")
        help_window.minsize(850, 600)
        help_window.resizable(True, True)

        button_frame = ttk.Frame(help_window)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))

        ok_button = widgets.primary_button(button_frame, text="OK", command=help_window.destroy)
        ok_button.pack(side=tk.LEFT)

        main_frame = ttk.Frame(help_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(main_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text = tk.Text(main_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=widgets.FONT_BODY)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text.yview)

        text.insert(1.0, content)
        text.config(state=tk.DISABLED)

        help_window.update_idletasks()
        w = 900
        h = 650
        px = self.winfo_rootx()  # type: ignore[attr-defined]
        py = self.winfo_rooty()  # type: ignore[attr-defined]
        pw = self.winfo_width()  # type: ignore[attr-defined]
        ph = self.winfo_height()  # type: ignore[attr-defined]
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        help_window.geometry(f"{w}x{h}+{x}+{y}")
        help_window.deiconify()

    def _get_help_command(self, filename: str) -> Optional[Callable[[], None]]:
        """Get the help command for a given file"""
        help_commands: dict[str, Callable[[], None]] = {
            "compile.sh": self._show_compile_sh_help,
            "compile_validate.sh": self._show_validation_compile_sh_help,
            "execute.sh": self._show_execute_sh_help,
            "validate.sh": self._show_validate_sh_help,
            "seq_settings.json": self._show_seq_settings_help,
            "dp_settings.json": self._show_dp_settings_help,
            "hd_settings.json": self._show_hd_settings_help,
            "par_settings.json": self._show_par_settings_help,
        }
        return help_commands.get(filename)

    def _show_compile_sh_help(self) -> None:
        help_text = (
            "Compilation Script (compile.sh)\n\n"
            "Purpose:\n"
            "The compile.sh script is responsible for building your application using configurable\n"
            "compilers and flags.\n\n"
            "Requirements:\n"
            "  • Must use $CC for C compilation\n"
            "  • Must use $CXX for C++ compilation\n"
            "  • Must respect $CFLAGS and $CXXFLAGS environment variables\n"
            "  • Must return exit code 0 on success\n"
            "  • Must be executable from the project root directory\n\n"
            "Example:\n"
            "#!/bin/bash\n"
            "$CXX $CXXFLAGS -o program main.cpp\n\n"
            "Notes:\n"
            "The DiscoPoP framework will set the compiler variables to appropriate values\n"
            "during the instrumentation process.\n\n"
            "Per-configuration override:\n"
            "Each configuration may define its own compile.sh (via the 'compile.sh (override)'\n"
            "tab in the configuration editor). When present, it is used instead of this shared\n"
            "script for that configuration only.\n\n"
            "Separate build for validation:\n"
            "This script builds the code that execute.sh runs. If validate.sh needs a\n"
            "differently compiled binary, provide a compile_validate.sh in addition — see its\n"
            "own help for details."
        )
        self._show_help_dialog("compile.sh Help", help_text)

    def _show_validation_compile_sh_help(self) -> None:
        help_text = (
            "Validation Build Script (compile_validate.sh) — optional\n\n"
            "Purpose:\n"
            "compile.sh builds the code that execute.sh runs. When validate.sh requires a\n"
            "differently compiled binary — for instance one built with extra checks, a\n"
            "reference implementation, or an output-dumping flag — put those build\n"
            "instructions into compile_validate.sh.\n\n"
            "Behavior:\n"
            "  • Optional: without it, validate.sh runs against the same build as execute.sh,\n"
            "    exactly as before.\n"
            "  • When present, it is run after the timed execute.sh run and before\n"
            "    validate.sh, so the extra build never affects the measured runtime.\n"
            "  • If the build fails, validate.sh is skipped and the run counts as invalid.\n"
            "  • It is ignored for configurations that define no validate.sh, since there\n"
            "    would be nothing to run against that build.\n\n"
            "Resolution order (role before specificity):\n"
            "  1. the configuration's own compile_validate.sh override\n"
            "  2. the shared compile_validate.sh\n"
            "  3. otherwise the compile script used for execute.sh\n"
            "A shared compile_validate.sh therefore also applies to configurations that have\n"
            "their own compile.sh override.\n\n"
            "Requirements:\n"
            "  • Same as compile.sh: use $CC / $CXX and $CFLAGS / $CXXFLAGS, exit 0 on success\n"
            "  • Must be executable from the project root directory\n\n"
            "Example:\n"
            "#!/bin/bash\n"
            "$CXX $CXXFLAGS -DVALIDATE_OUTPUT -o program main.cpp"
        )
        self._show_help_dialog("compile_validate.sh Help", help_text)

    def _show_execute_sh_help(self) -> None:
        help_text = (
            "Execution Script (execute.sh)\n\n"
            "Purpose:\n"
            "The execute.sh script runs your application and collects profiling data for\n"
            "analysis.\n\n"
            "Requirements:\n"
            "  • Must execute the application built by compile.sh\n"
            "  • Should pass all command-line arguments to the application\n"
            "  • Must return exit code 0 on success\n"
            "  • Must be executable from the project root directory\n\n"
            "Example:\n"
            "#!/bin/bash\n"
            "./program <args>\n\n"
            "Notes:\n"
            "The script is executed in each compilation mode (sequential, instrumented, etc.)\n"
            "to collect performance data.\n\n"
            "Execution time:\n"
            "By default the wall clock time of execute.sh is measured, which also covers\n"
            "setup, teardown and any file I/O the run performs. If that is not the time of\n"
            "interest and the program prints its own timing, switch on 'Read the execution\n"
            "time from the program's console output' and give a regular expression whose\n"
            "FIRST CAPTURE GROUP holds the value:\n"
            "  • Total time:\\s*([0-9.]+)   for 'Total time: 1.234 seconds'\n"
            "  • the default pattern looks for <DP_EXEC_TIME>1.234</DP_EXEC_TIME>, a tag a\n"
            "    program can print regardless of how the rest of its output is formatted\n"
            "Both streams are searched (stdout first); of several matches the last one is\n"
            "used, so a program printing a time per phase can end with the total. 'Test'\n"
            "applies the pattern to the output of the last recorded run, without executing\n"
            "anything.\n\n"
            "If the pattern finds nothing, the wall clock time is reported instead and the\n"
            "run is recorded as having fallen back to it — a measurement is never silently\n"
            "replaced by the other kind. The setting is stored per configuration in\n"
            "execution_time.json, next to this script, and can be overridden for a single\n"
            "run with --execution-time-regex."
        )
        self._show_help_dialog("execute.sh Help", help_text)

    def _show_validate_sh_help(self) -> None:
        help_text = (
            "Output Validation Script (validate.sh) — optional\n\n"
            "Purpose:\n"
            "The validate.sh script executes the application and validates its output. It is\n"
            "run separately from the timed execute.sh run, so that validation work (e.g. a\n"
            "diff against a reference output) does not pollute the runtime measurement.\n\n"
            "Behavior:\n"
            "  • Optional: if validate.sh does not exist, execute.sh alone determines\n"
            "    correctness (its exit code), exactly as before.\n"
            "  • When present, it is auto-run after a successful execute.sh, but only for\n"
            "    the seq and par modes (dp/hd are profiling runs and are left untouched).\n"
            "  • A run counts as correct only if BOTH execute.sh and validate.sh exit 0.\n"
            "  • If validation needs a different build than execute.sh, provide a\n"
            "    compile_validate.sh; it is then compiled after the timed run and before\n"
            "    validate.sh. See its own help for details.\n\n"
            "Requirements:\n"
            "  • Should run the application built by compile.sh and check its output\n"
            "  • Must return exit code 0 when the output is valid, non-zero otherwise\n"
            "  • Must be executable from the project root directory\n\n"
            "Example:\n"
            "#!/bin/bash\n"
            "./program <args> > output.out\n"
            "diff output.out reference.out"
        )
        self._show_help_dialog("validate.sh Help", help_text)

    def _show_seq_settings_help(self) -> None:
        help_text = (
            "Sequential Compilation Settings (seq_settings.json)\n\n"
            "Purpose:\n"
            "The seq_settings.json file contains configuration parameters for compiling\n"
            "your application in sequential mode.\n\n"
            "Contents:\n"
            "  • CC: C compiler command\n"
            "  • CXX: C++ compiler command\n"
            "  • CFLAGS: Flags for C compilation\n"
            "  • CXXFLAGS: Flags for C++ compilation\n\n"
            "Usage:\n"
            "Sequential mode provides a baseline measurement for performance comparison.\n"
            "This is the first compilation mode used to establish reference performance metrics."
        )
        self._show_help_dialog("seq_settings.json Help", help_text)

    def _show_dp_settings_help(self) -> None:
        help_text = (
            "DiscoPoP Instrumentation Settings (dp_settings.json)\n\n"
            "Purpose:\n"
            "The dp_settings.json file contains configuration parameters for compiling\n"
            "your application with full DiscoPoP instrumentation.\n\n"
            "Modifications from Sequential:\n"
            "  • CC is set to discopop_cc\n"
            "  • CXX is set to discopop_cxx\n"
            "  • Other flags are preserved from sequential settings\n\n"
            "Usage:\n"
            "This mode instruments your code to collect detailed profiling data about\n"
            "parallelization opportunities and performance characteristics."
        )
        self._show_help_dialog("dp_settings.json Help", help_text)

    def _show_hd_settings_help(self) -> None:
        help_text = (
            "Hotspot Detection Settings (hd_settings.json)\n\n"
            "Purpose:\n"
            "The hd_settings.json file contains configuration parameters for compiling\n"
            "your application with hotspot detection instrumentation.\n\n"
            "Modifications from Sequential:\n"
            "  • CC is set to discopop_hotspot_cc\n"
            "  • CXX is set to discopop_hotspot_cxx\n"
            "  • -fopenmp flag is added to CFLAGS and CXXFLAGS\n\n"
            "Usage:\n"
            "Hotspot detection performs lightweight profiling to identify performance-critical\n"
            "code regions without the overhead of full instrumentation."
        )
        self._show_help_dialog("hd_settings.json Help", help_text)

    def _show_par_settings_help(self) -> None:
        help_text = (
            "Parallel Execution Settings (par_settings.json)\n\n"
            "Purpose:\n"
            "The par_settings.json file contains configuration parameters for compiling\n"
            "your application with OpenMP parallelization.\n\n"
            "Modifications from Sequential:\n"
            "  • CC and CXX are preserved from sequential settings\n"
            "  • -fopenmp flag is added to CFLAGS and CXXFLAGS\n\n"
            "Usage:\n"
            "This mode compiles your parallelized code (as suggested by DiscoPoP analysis)\n"
            "with OpenMP support to execute on multiple processors."
        )
        self._show_help_dialog("par_settings.json Help", help_text)
