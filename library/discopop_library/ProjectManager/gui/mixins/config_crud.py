# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import shutil
import tkinter as tk
from tkinter import simpledialog

from discopop_library.ProjectManager.utilities.initializeFiles import initialize_configuration_files
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import show_error, show_warning, ask_yes_no, show_message


class ConfigCrudMixin(ConfigManagerMixinBase):
    def _new_config(self) -> None:
        dialog = simpledialog.askstring("New Configuration", "Enter configuration name:", parent=self)  # type: ignore[arg-type]
        if not dialog:
            return

        config_name = dialog.strip()
        if not config_name:
            show_error(self, "Invalid name", "Configuration name cannot be empty")
            return

        config_path = os.path.join(self.config_dir, config_name)
        if os.path.exists(config_path):
            show_error(self, "Already exists", f"Configuration '{config_name}' already exists")
            return

        try:
            os.makedirs(config_path, exist_ok=True)
            initialize_configuration_files(self.arguments)
            self._refresh_config_list()
            self.current_config = config_name
            for i in range(self.listbox.size()):
                if self.listbox.get(i) == config_name:
                    self.listbox.selection_clear(0, tk.END)
                    self.listbox.selection_set(i)
                    break
            self._load_config()
            self._set_status(f"Created configuration '{config_name}'", fg="green", reset_delay=2000)
        except Exception as e:
            show_error(self, "Error", f"Failed to create configuration: {e}")
            self._set_status("Error creating config", fg="red")

    def _copy_config(self) -> None:
        if not self.current_config:
            show_warning(self, "No selection", "Please select a configuration to copy")
            return

        dialog = simpledialog.askstring("Copy Configuration", f"Enter new name for copy of '{self.current_config}':")
        if not dialog:
            return

        config_name = dialog.strip()
        if not config_name:
            show_error(self, "Invalid name", "Configuration name cannot be empty")
            return

        if config_name == self.current_config:
            show_error(self, "Invalid name", "New name must be different from the original")
            return

        source_path = os.path.join(self.config_dir, self.current_config)
        dest_path = os.path.join(self.config_dir, config_name)

        if os.path.exists(dest_path):
            show_error(self, "Already exists", f"Configuration '{config_name}' already exists")
            return

        try:
            shutil.copytree(source_path, dest_path)
            self._refresh_config_list()
            self._set_status(f"Copied configuration to '{config_name}'", fg="green", reset_delay=2000)
        except Exception as e:
            show_error(self, "Error", f"Failed to copy configuration: {e}")
            self._set_status("Error copying config", fg="red")

    def _rename_config(self) -> None:
        if not self.current_config:
            show_warning(self, "No selection", "Please select a configuration to rename")
            return

        dialog = simpledialog.askstring("Rename Configuration", f"Enter new name for '{self.current_config}':")
        if not dialog:
            return

        new_name = dialog.strip()
        if not new_name:
            show_error(self, "Invalid name", "Configuration name cannot be empty")
            return

        if new_name == self.current_config:
            show_message(self, "No change", "New name is the same as the current name")
            return

        old_path = os.path.join(self.config_dir, self.current_config)
        new_path = os.path.join(self.config_dir, new_name)

        if os.path.exists(new_path):
            show_error(self, "Already exists", f"Configuration '{new_name}' already exists")
            return

        try:
            os.rename(old_path, new_path)
            self.current_config = new_name
            self._refresh_config_list()
            self._load_config()
            self._set_status(f"Renamed configuration to '{new_name}'", fg="green", reset_delay=2000)
        except Exception as e:
            show_error(self, "Error", f"Failed to rename configuration: {e}")
            self._set_status("Error renaming config", fg="red")

    def _delete_config(self) -> None:
        if not self.current_config:
            show_warning(self, "No selection", "Please select a configuration to delete")
            return

        if not ask_yes_no(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{self.current_config}'? This cannot be undone.",
        ):
            return

        config_path = os.path.join(self.config_dir, self.current_config)
        try:
            shutil.rmtree(config_path)
            self.current_config = None
            self._refresh_config_list()
            self._set_status("Deleted configuration", fg="green", reset_delay=2000)
        except Exception as e:
            show_error(self, "Error", f"Failed to delete configuration: {e}")
            self._set_status("Error deleting config", fg="red")
