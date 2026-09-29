# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""An always-visible "Selection Details" side bar for the results panels.

Charts and tables report whatever the user last clicked into one of these, rather
than opening a popup, so the view stays stable while clicking around. Used by both
the Report tab (execution records) and the Hotspot Detection tab (code regions).

Fields are stacked label-above-value rather than side-by-side so both stay
readable as the bar is dragged narrower, and the whole field list scrolls: a
narrow bar with many wrapped values easily exceeds the available height.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton

DEFAULT_TITLE = "Selection Details"
DEFAULT_PLACEHOLDER = "Click a point, line, or bar\nto see its details here."


class DetailBar(ttk.Frame):
    """A scrollable, always-visible detail panel filled from a selection."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        title: str = DEFAULT_TITLE,
        placeholder: str = DEFAULT_PLACEHOLDER,
    ) -> None:
        super().__init__(parent)
        self._placeholder_text = placeholder
        self._value_labels: List[ttk.Label] = []
        self._actions: List[Tuple[RoundedButton, Callable[[], bool]]] = []

        widgets.heading_label(self, title).pack(anchor=tk.W, padx=8, pady=(8, 4))
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=(0, 8))

        # Actions sit at the bottom, packed before the scroll area so they keep
        # their height however long the field list grows.
        self._actions_frame = ttk.Frame(self)
        self._actions_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))

        scroll_container = ttk.Frame(self)
        scroll_container.pack(fill=tk.BOTH, expand=True, padx=(8, 0))

        self._canvas = tk.Canvas(scroll_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._body = ttk.Frame(self._canvas)
        body_window = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._canvas.bind("<Configure>", lambda e: self._canvas.itemconfig(body_window, width=e.width))
        # One handler covers both the scrollregion (grows with the field rows) and
        # the values' wraplength (tracks the bar's width). Bound once here rather
        # than per selection, since Tk's bind() replaces a widget's handler for the
        # same sequence instead of chaining.
        self._body.bind("<Configure>", lambda _e: self._on_body_configure())

        self._bind_scroll(self._canvas)
        self._bind_scroll(self._body)
        self.show_placeholder()

    # -- content ------------------------------------------------------------

    def show_placeholder(self) -> None:
        """Reset to the "nothing selected yet" state."""
        self._clear_body()
        placeholder = widgets.caption_label(self._body, self._placeholder_text, justify=tk.LEFT)
        placeholder.pack(anchor=tk.W, pady=4)
        self._bind_scroll(placeholder)
        self._update_actions()

    def show_fields(self, fields: Sequence[Tuple[str, str]]) -> None:
        """Replace the contents with ``(label, value)`` rows."""
        self._clear_body()
        for label, value in fields:
            label_widget = ttk.Label(self._body, text=label, font=widgets.FONT_CAPTION, foreground=widgets.STATUS_IDLE)
            label_widget.pack(anchor=tk.W, pady=(8, 0))
            value_label = ttk.Label(self._body, text=value, font=widgets.FONT_BODY, justify=tk.LEFT)
            value_label.pack(anchor=tk.W, fill=tk.X)
            self._value_labels.append(value_label)
            self._bind_scroll(label_widget)
            self._bind_scroll(value_label)
        self._on_body_configure()
        self._update_actions()

    def add_action(self, text: str, command: Callable[[], None], *, enabled: Callable[[], bool]) -> RoundedButton:
        """Add a button below the fields, enabled according to ``enabled()``.

        ``enabled`` is re-evaluated whenever the contents change, so an action
        that needs a selection disables itself while the placeholder is showing.
        """
        button = widgets.create_button(self._actions_frame, text=text, command=command, state="disabled")
        button.pack(side=tk.TOP, fill=tk.X, pady=2)
        self._actions.append((button, enabled))
        return button

    # -- internals ----------------------------------------------------------

    def _clear_body(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        self._value_labels = []

    def _update_actions(self) -> None:
        for button, is_enabled in self._actions:
            button.config(state="normal" if is_enabled() else "disabled")

    def _on_body_configure(self) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        width = max(80, self._body.winfo_width())
        for value_label in self._value_labels:
            value_label.configure(wraplength=width)

    def _bind_scroll(self, widget: tk.Misc) -> None:
        """Route wheel events on ``widget`` to the scroll canvas.

        A no-op when the content already fits, so it never steals the wheel from
        a parent scroll area.
        """

        def on_wheel(event: Any) -> str:
            bbox = self._canvas.bbox("all")
            if bbox is None or (bbox[3] - bbox[1]) <= self._canvas.winfo_height():
                return "break"
            number: Optional[int] = getattr(event, "num", None)
            if number == 4:
                delta = -1
            elif number == 5:
                delta = 1
            else:
                delta = -1 if event.delta > 0 else 1
            self._canvas.yview_scroll(delta, "units")
            return "break"

        widget.bind("<MouseWheel>", on_wheel)  # Windows / macOS
        widget.bind("<Button-4>", on_wheel)  # X11 scroll up
        widget.bind("<Button-5>", on_wheel)  # X11 scroll down
