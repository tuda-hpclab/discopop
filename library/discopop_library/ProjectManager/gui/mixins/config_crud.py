# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import tkinter as tk
from tkinter import simpledialog

from discopop_library.ProjectManager.services.configurations import (
    ConfigurationError,
    SameNameError,
    copy_configuration_directory,
    create_configuration,
    delete_configuration_directory,
    rename_configuration,
)
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import show_error, show_warning, ask_yes_no, show_message


class ConfigCrudMixin(ConfigManagerMixinBase):
    def _new_config(self) -> None:
        dialog = simpledialog.askstring("New Configuration", "Enter configuration name:", parent=self)  # type: ignore[arg-type]
        if not dialog:
            return

        try:
            config_name = create_configuration(self.arguments, dialog)
        except ConfigurationError as e:
            show_error(self, e.title, e.message)
            return
        except Exception as e:
            show_error(self, "Error", f"Failed to create configuration: {e}")
            self._set_status("Error creating config", fg="red")
            return

        try:
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

        try:
            config_name = copy_configuration_directory(self.config_dir, self.current_config, dialog)
        except ConfigurationError as e:
            show_error(self, e.title, e.message)
            return
        except Exception as e:
            show_error(self, "Error", f"Failed to copy configuration: {e}")
            self._set_status("Error copying config", fg="red")
            return

        try:
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

        try:
            new_name = rename_configuration(self.config_dir, self.current_config, dialog)
        except SameNameError:
            show_message(self, "No change", "New name is the same as the current name")
            return
        except ConfigurationError as e:
            show_error(self, e.title, e.message)
            return
        except Exception as e:
            show_error(self, "Error", f"Failed to rename configuration: {e}")
            self._set_status("Error renaming config", fg="red")
            return

        try:
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

        try:
            delete_configuration_directory(self.config_dir, self.current_config)
            self.current_config = None
            self._refresh_config_list()
            self._set_status("Deleted configuration", fg="green", reset_delay=2000)
        except Exception as e:
            show_error(self, "Error", f"Failed to delete configuration: {e}")
            self._set_status("Error deleting config", fg="red")
