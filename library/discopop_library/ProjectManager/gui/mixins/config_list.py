# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tkinter as tk
from typing import Any, Literal, Optional

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase


class ConfigListMixin(ConfigManagerMixinBase):
    def _refresh_config_list(self) -> None:
        if not self.listbox.winfo_exists():
            return

        previous_config = self.current_config

        self.listbox.delete(0, tk.END)
        if os.path.exists(self.config_dir):
            configs = sorted(
                [d for d in os.listdir(self.config_dir) if os.path.isdir(os.path.join(self.config_dir, d))]
            )

            execution_results_path = os.path.join(self.arguments.project_dir, "execution_results.json")
            execution_results: dict[str, Any] = {}
            try:
                if os.path.exists(execution_results_path):
                    with open(execution_results_path, "r") as f:
                        execution_results = json.load(f)
            except Exception:
                pass

            for config in configs:
                self.listbox.insert(tk.END, config)

            if configs:
                if previous_config and previous_config in configs:
                    index = configs.index(previous_config)
                    self.listbox.selection_set(index)
                    self.current_config = previous_config
                else:
                    self.listbox.selection_set(0)
                    self.current_config = configs[0]
                self._load_config()
                self._update_autotuning_config_display()
                if hasattr(self, "_refresh_autotuning_suggestions_display"):
                    self._refresh_autotuning_suggestions_display()
                if hasattr(self, "_refresh_suggestion_selection_display"):
                    self._refresh_suggestion_selection_display()
                if hasattr(self, "_update_hotspot_config_display"):
                    self._update_hotspot_config_display()
                # the Patch Repair tab names the selected configuration and refuses to
                # run without one, so it has to learn about the selection as well
                self._update_patch_repair_ui()

    def _on_config_selected(self, event: Optional[Any]) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self.current_config = self.listbox.get(selection[0])
        self._load_config()
        self._update_autotuning_config_display()
        if hasattr(self, "_refresh_autotuning_suggestions_display"):
            self._refresh_autotuning_suggestions_display()
        if hasattr(self, "_refresh_suggestion_selection_display"):
            self._refresh_suggestion_selection_display()
        if hasattr(self, "_update_hotspot_config_display"):
            self._update_hotspot_config_display()
        self._update_patch_repair_ui()

        try:
            current_tab_index = self.right_tabs.index(self.right_tabs.select())
            if current_tab_index in (1, 2):
                self.right_tabs.select(self.editor_tab_index)
        except Exception:
            pass

    def _on_config_right_click(self, event: Any) -> None:
        index = self.listbox.nearest(event.y)
        if index < 0:
            return

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.current_config = self.listbox.get(index)
        self._load_config()

        menu = tk.Menu(self.listbox, tearoff=False)
        menu.add_command(label="Copy", command=self._copy_config)
        menu.add_command(label="Rename", command=self._rename_config)
        menu.add_separator()
        menu.add_command(label="Delete", command=self._delete_config)

        menu.tk_popup(event.x_root, event.y_root)

    def _update_execute_modes(self) -> None:
        if not self.current_config:
            for cb in self.mode_checkbuttons.values():
                cb.config(state="disabled")
            self.run_button.config(state="disabled")
            if hasattr(self, "prepare_pattern_detection_button"):
                self.prepare_pattern_detection_button.config(state="disabled")
            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete("1.0", tk.END)
            self.output_text.config(state="disabled")
            self.generate_report_button.config(state="disabled")
            self.view_report_button.config(state="disabled")
            for var in self.mode_vars.values():
                var.set(False)
            self.mode_vars["seq"].set(True)
            return

        config_path = os.path.join(self.config_dir, self.current_config)
        compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, self.current_config)
        shared_seq_settings = os.path.join(self.arguments.project_config_dir, "seq_settings.json")
        shared_dp_settings = os.path.join(self.arguments.project_config_dir, "dp_settings.json")
        shared_hd_settings = os.path.join(self.arguments.project_config_dir, "hd_settings.json")
        shared_par_settings = os.path.join(self.arguments.project_config_dir, "par_settings.json")
        execute_sh = os.path.join(config_path, "execute.sh")

        for mode, settings_file in [
            ("seq", "seq_settings.json"),
            ("dp", "dp_settings.json"),
            ("hd", "hd_settings.json"),
            ("par", "par_settings.json"),
        ]:
            if mode == "seq":
                settings_path = shared_seq_settings
            elif mode == "dp":
                settings_path = shared_dp_settings
            elif mode == "hd":
                settings_path = shared_hd_settings
            elif mode == "par":
                settings_path = shared_par_settings
            else:
                settings_path = ""

            exists = os.path.exists(settings_path) and os.path.exists(compile_sh) and os.path.exists(execute_sh)
            state: Literal["normal", "disabled"] = "normal" if exists else "disabled"
            self.mode_checkbuttons[mode].config(state=state)
            if not exists:
                self.mode_vars[mode].set(False)

        self.run_button.config(state="normal")
        if hasattr(self, "prepare_pattern_detection_button"):
            self.prepare_pattern_detection_button.config(state="normal")

        reports_dir = os.path.join(self.arguments.project_dir, "reports")
        report_exists = False
        if os.path.exists(reports_dir):
            report_dirs = sorted([d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))])
            if report_dirs:
                latest_report_dir = os.path.join(reports_dir, report_dirs[-1])
                report_path = os.path.join(latest_report_dir, "full_report.pdf")
                report_exists = os.path.exists(report_path)

        self.view_report_button.config(state="normal" if report_exists else "disabled")
