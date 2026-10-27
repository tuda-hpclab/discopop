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
from discopop_library.ProjectManager.services.help_texts import HELP_TEXTS
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
        self._show_help_dialog(*HELP_TEXTS["compile.sh"])

    def _show_validation_compile_sh_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["compile_validate.sh"])

    def _show_execute_sh_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["execute.sh"])

    def _show_validate_sh_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["validate.sh"])

    def _show_seq_settings_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["seq_settings.json"])

    def _show_dp_settings_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["dp_settings.json"])

    def _show_hd_settings_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["hd_settings.json"])

    def _show_par_settings_help(self) -> None:
        self._show_help_dialog(*HELP_TEXTS["par_settings.json"])
