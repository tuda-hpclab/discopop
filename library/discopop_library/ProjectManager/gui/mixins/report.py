# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import subprocess
import threading
import tkinter as tk


from discopop_library.ProjectManager.services.reports import ReportProblem, find_latest_report_pdf
from discopop_library.ProjectManager.reports.full import generate_full_report
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import show_warning


class ReportMixin(ConfigManagerMixinBase):
    def _generate_report(self) -> None:
        self.generate_report_button.config(state="disabled")

        def append_output(text: str) -> None:
            self.output_text.config(state=tk.NORMAL)
            self.output_text.insert(tk.END, text)
            self.output_text.see(tk.END)
            self.output_text.config(state="disabled")

        self.after(0, lambda: append_output("Generating report...\n"))  # type: ignore

        args_copy = copy.copy(self.arguments)
        args_copy.show_report = False

        def thread_func() -> None:
            try:
                generate_full_report(args_copy)
                self.after(0, lambda: append_output("Report generated.\n"))  # type: ignore
                self.after(0, lambda: self.view_report_button.config(state=tk.NORMAL))  # type: ignore
            except Exception as e:
                self.after(0, lambda e_msg=str(e): append_output(f"Error generating report: {e_msg}\n"))  # type: ignore
                self.after(0, lambda: self.generate_report_button.config(state=tk.NORMAL))  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

    def _view_report(self) -> None:
        report_path, problem = find_latest_report_pdf(self.arguments.project_dir)
        if report_path is None:
            if problem == ReportProblem.NO_REPORTS_DIRECTORY:
                show_warning(self, "No report", "No report found. Generate one first.")
            elif problem == ReportProblem.NO_REPORT:
                show_warning(self, "No report", "No report found.")
            else:
                show_warning(self, "No report", "No report PDF found.")
            return

        subprocess.Popen(["xdg-open", report_path])

    def _reset_execution_results(self) -> None:
        args_copy = copy.copy(self.arguments)
        args_copy.reset = False
        args_copy.reset_execution_results = True

        from discopop_library.ProjectManager.utilities.reset import reset_project

        try:
            reset_project(args_copy)
            self._set_status("Execution results reset successfully", fg="green")
            self._refresh_config_list()
            self._update_report_display()
            self._update_pattern_detection_ui()
        except Exception as e:
            self._set_status(f"Error resetting execution results: {e}", fg="red")

    def _reset_project_data(self) -> None:
        args_copy = copy.copy(self.arguments)
        args_copy.reset = True
        args_copy.reset_execution_results = False

        from discopop_library.ProjectManager.utilities.reset import reset_project

        try:
            reset_project(args_copy)
            self._set_status("Project reset successfully", fg="green")
            self._refresh_config_list()
            self._update_report_display()
            self._update_pattern_detection_ui()
        except Exception as e:
            self._set_status(f"Error resetting project: {e}", fg="red")
