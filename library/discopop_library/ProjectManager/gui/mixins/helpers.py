# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import re
import tkinter as tk
import tkinter.font
from tkinter import scrolledtext, ttk
from typing import Optional, Literal, Any, Union

from discopop_library.ProjectManager.gui import widgets


class TextAreaHandler(logging.Handler):
    """Custom logging handler that writes to a tkinter Text widget with color coding"""

    def __init__(self, text_area: scrolledtext.ScrolledText) -> None:
        super().__init__()
        self.text_area = text_area

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level_name = record.levelname

            self.text_area.config(state=tk.NORMAL)
            self.text_area.insert(tk.END, msg + "\n", level_name)
            self.text_area.see(tk.END)
            self.text_area.config(state="disabled")
        except Exception:
            self.handleError(record)


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tipwindow: Optional[tk.Toplevel] = None
        self.id: Optional[str] = None
        self.x = self.y = 0

    def showtip(self, x: int, y: int) -> None:
        if self.tipwindow:
            return
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=widgets.FONT_BODY,
            justify=tk.LEFT,
            wraplength=300,
            padx=8,
            pady=8,
        )
        label.pack()

    def hidetip(self) -> None:
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


def show_message(parent: Any, title: str, message: str) -> None:  # type: ignore
    """Display a message dialog with normal (non-bold) text."""
    dialog = tk.Toplevel(parent)  # type: ignore
    dialog.withdraw()
    dialog.title(title)
    dialog.resizable(True, True)

    button_frame = ttk.Frame(dialog, padding=(15, 0))
    button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 15))

    ok_button = widgets.primary_button(button_frame, text="OK", command=dialog.destroy, width=10)
    ok_button.pack(side=tk.LEFT)

    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)

    label = ttk.Label(main_frame, text=message, wraplength=600, justify=tk.LEFT, font=widgets.FONT_BODY)
    label.pack(fill=tk.BOTH, expand=True)

    dialog.update_idletasks()
    req_width = label.winfo_reqwidth() + 60
    req_height = label.winfo_reqheight() + 90
    w = max(600, min(900, req_width))
    h = max(250, min(700, req_height))

    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2

    dialog.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
    dialog.minsize(600, 250)

    dialog.transient(parent)  # type: ignore
    dialog.deiconify()
    dialog.grab_set()  # type: ignore
    dialog.wait_window()  # type: ignore


def show_warning(parent: Any, title: str, message: str) -> None:
    """Display a warning dialog with normal text."""
    show_message(parent, title, message)


def show_error(parent: Any, title: str, message: str) -> None:
    """Display an error dialog with normal text."""
    show_message(parent, title, message)


def ask_yes_no(parent: Any, title: str, message: str) -> bool:  # type: ignore
    """Display a yes/no confirmation dialog with normal text. Returns True for Yes, False for No."""
    dialog = tk.Toplevel(parent)  # type: ignore
    dialog.withdraw()
    dialog.title(title)
    dialog.resizable(True, True)

    result: list[bool] = [False]

    button_frame = ttk.Frame(dialog, padding=(15, 0))
    button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 15))

    def on_yes() -> None:
        result[0] = True
        dialog.destroy()

    def on_no() -> None:
        result[0] = False
        dialog.destroy()

    yes_button = widgets.primary_button(button_frame, text="Yes", command=on_yes, width=10)
    yes_button.pack(side=tk.LEFT, padx=5)

    no_button = widgets.create_button(button_frame, text="No", command=on_no, width=10)
    no_button.pack(side=tk.LEFT, padx=5)

    main_frame = ttk.Frame(dialog, padding=15)
    main_frame.pack(fill=tk.BOTH, expand=True)

    label = ttk.Label(main_frame, text=message, wraplength=600, justify=tk.LEFT, font=widgets.FONT_BODY)
    label.pack(fill=tk.BOTH, expand=True)

    dialog.update_idletasks()
    req_width = label.winfo_reqwidth() + 60
    req_height = label.winfo_reqheight() + 100
    w = max(600, min(900, req_width))
    h = max(250, min(700, req_height))

    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + (pw - w) // 2
    y = py + (ph - h) // 2

    dialog.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
    dialog.minsize(600, 250)

    dialog.transient(parent)  # type: ignore
    dialog.deiconify()
    dialog.grab_set()  # type: ignore
    dialog.wait_window()

    return result[0]


def clean_ansi_output(text: str) -> str:
    """Remove ANSI escape codes and clean up carriage returns for display."""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m|\x1b\[[A-Z]")
    text = ansi_escape.sub("", text)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if "\r" in line:
            parts = line.split("\r")
            line = parts[-1] if parts[-1] else parts[-2] if len(parts) > 1 else ""
        if line.strip():
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def bind_tooltip_hover(widget: tk.Widget, tooltip: Tooltip, parent: Any, delay: int = 500) -> None:
    """Bind <Enter>/<Leave> on widget to show/hide tooltip with a debounce timer."""
    timer: list[Optional[str]] = [None]

    def on_enter(event: Any) -> None:
        if timer[0]:
            parent.after_cancel(timer[0])
        timer[0] = parent.after(delay, tooltip.showtip, event.x_root, event.y_root)

    def on_leave(event: Any) -> None:
        if timer[0]:
            parent.after_cancel(timer[0])
            timer[0] = None
        tooltip.hidetip()

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


def enable_text_context_menu(text_widget: Union[tk.Text, scrolledtext.ScrolledText]) -> None:
    """Add right-click context menu with copy and paste to a Text widget."""

    def copy_text() -> None:
        try:
            sel = text_widget.get("sel.first", "sel.last")
            text_widget.clipboard_clear()
            text_widget.clipboard_append(sel)
        except tk.TclError:
            pass

    def paste_text() -> None:
        try:
            text_widget.insert("insert", text_widget.clipboard_get())
        except tk.TclError:
            pass

    def show_menu(event: Any) -> None:
        menu = tk.Menu(text_widget, tearoff=False)
        menu.add_command(label="Copy", command=copy_text)
        menu.add_command(label="Paste", command=paste_text)
        menu.tk_popup(event.x_root, event.y_root)

    text_widget.bind("<Button-3>", show_menu)
