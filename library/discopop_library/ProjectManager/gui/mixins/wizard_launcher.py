# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import tkinter as tk


from discopop_library.ProjectManager.gui.ConfigurationWizard import ConfigurationWizard
from discopop_library.ProjectManager.utilities.initializeFiles import initial_script_content
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import show_message


class WizardLauncherMixin(ConfigManagerMixinBase):
    def _maybe_open_wizard(self) -> None:
        def _is_real_config(entry: os.DirEntry[str]) -> bool:
            if not entry.is_dir():
                return False
            execute_sh = os.path.join(entry.path, "execute.sh")
            if not os.path.exists(execute_sh):
                return False
            with open(execute_sh, "r") as f:
                return f.read().strip() != initial_script_content.strip()

        has_real_configs = os.path.exists(self.config_dir) and any(
            _is_real_config(entry) for entry in os.scandir(self.config_dir)
        )
        if not has_real_configs:
            if self.was_initialized:
                show_message(
                    self,
                    "Project Initialized",
                    f"Project configuration directory has been initialized:\n{self.config_dir}",
                )
            self._open_configuration_wizard()

    def _open_configuration_wizard(self) -> None:
        wizard = ConfigurationWizard(self, self.arguments)  # type: ignore
        self.wait_window(wizard)  # type: ignore
        self.update_idletasks()  # type: ignore
        self._refresh_config_list()
        if wizard.result:
            for i in range(self.listbox.size()):
                entry = self.listbox.get(i)
                name = entry[2:] if entry.startswith(("✓ ", "○ ")) else entry
                if name == wizard.result:
                    self.listbox.selection_set(i)
                    self.current_config = wizard.result
                    self._load_config()
                    self.right_tabs.select(self.execute_tab_index)  # type: ignore
                    break
