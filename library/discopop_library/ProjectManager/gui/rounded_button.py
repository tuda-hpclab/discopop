# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A rounded-corner button drawn on a :class:`tkinter.Canvas`.

``tk.Button`` / ``ttk.Button`` cannot render rounded corners, so this widget
draws the shape itself (a smoothed polygon) with the label on top and wires up
the click / hover / focus / keyboard behavior a real button needs.

It is intended as a drop-in replacement for the ``ttk.Button`` call sites in
this GUI, so it supports the subset of the ttk API those call sites use:

* construction with ``text``, ``command``, ``state`` and ``width``
  (``width`` is interpreted in characters, like ttk),
* runtime ``config(...)`` / ``configure(...)`` of ``text``, ``command``,
  ``state``, ``width`` and ``variant``,
* ``cget`` / ``__getitem__`` / ``__setitem__`` of those keys,
* stretching to fill its cell (``pack(fill="x")`` / ``grid(sticky=...)``) --
  the rounded shape is re-drawn on ``<Configure>``.

The appearance comes from a :class:`style.ButtonStyle`, selected by variant
name; see ``style.py`` to restyle.
"""

import tkinter as tk
from typing import Any, Callable, List, Optional

from discopop_library.ProjectManager.gui.style import ButtonStyle, DEFAULT_VARIANT, get_button_style

# State strings, matching tk.NORMAL / tk.DISABLED.
_NORMAL = "normal"
_DISABLED = "disabled"


class RoundedButton(tk.Canvas):
    """A canvas-drawn, rounded, themeable push button."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str = "",
        command: Optional[Callable[[], Any]] = None,
        *,
        variant: str = DEFAULT_VARIANT,
        style: Optional[ButtonStyle] = None,
        state: str = _NORMAL,
        width: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        # Match the canvas background to the parent so the rounded corners look
        # transparent (a canvas cannot be truly transparent). ttk parents do
        # not expose "bg" via cget, so fall back to the theme's frame color.
        super().__init__(parent, highlightthickness=0, bd=0, bg=self._parent_bg(parent), takefocus=1, **kwargs)

        self._style: ButtonStyle = style or get_button_style(variant)
        self._text: str = text
        self._command: Optional[Callable[[], Any]] = command
        self._state: str = state
        self._min_char_width: Optional[int] = width
        self._hovering: bool = False
        self._focused: bool = False

        # Draw order: shape first (bottom), label on top.
        self._shape: int = self.create_polygon((0, 0, 0, 0), smooth=True, fill=self._style.bg, outline="")
        self._label: int = self.create_text(0, 0, text=text, fill=self._style.fg, font=self._style.font)

        self._resize_to_content()

        # Interactions.
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<space>", self._on_key_activate)
        self.bind("<Return>", self._on_key_activate)
        # Redraw the shape whenever the widget is (re)sized, e.g. fill="x".
        self.bind("<Configure>", self._on_configure)

        self._apply_state()

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _parent_bg(parent: tk.Misc) -> str:
        """Best-effort background color of the parent, for fake transparency."""
        try:
            return str(parent.cget("bg"))
        except tk.TclError:
            # ttk widget: query the current theme's frame background.
            try:
                from tkinter import ttk

                return str(ttk.Style().lookup("TFrame", "background")) or "#f0f0f0"
            except tk.TclError:
                return "#f0f0f0"

    def _text_extent(self, text: str) -> tuple[int, int]:
        """Measure ``text`` in the button font exactly as the canvas draws it.

        Measuring via a throwaway canvas item (rather than ``tkfont.Font``)
        guarantees the size matches what is rendered -- important because a
        font *spec* like ``("TkDefaultFont", 10)`` can otherwise re-resolve to
        a differently sized font than the canvas actually uses (notably on
        HiDPI displays).
        """
        item = self.create_text(0, 0, text=text, font=self._style.font)
        bbox = self.bbox(item)
        self.delete(item)
        if not bbox:
            return 0, 0
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _resize_to_content(self) -> None:
        """Size the canvas to fit the label (plus padding / minimum width)."""
        text_w, text_h = self._text_extent(self._text) if self._text else (0, 0)
        width = text_w + 2 * self._style.pad_x
        if self._min_char_width:
            # Interpret ``width`` like ttk: a minimum size in characters.
            char_w, _ = self._text_extent("0" * self._min_char_width)
            width = max(width, char_w + 2 * self._style.pad_x)
        height = text_h + 2 * self._style.pad_y
        # Bypass our own configure() override (which treats width as characters).
        tk.Canvas.configure(self, width=width, height=height)
        self._redraw(width, height)

    @staticmethod
    def _rounded_points(w: float, h: float, r: float) -> List[float]:
        """Polygon points for a rounded rectangle, smoothed by the canvas."""
        r = max(0.0, min(r, w / 2, h / 2))
        return [
            r,
            0,
            w - r,
            0,
            w,
            0,
            w,
            r,
            w,
            h - r,
            w,
            h,
            w - r,
            h,
            r,
            h,
            0,
            h,
            0,
            h - r,
            0,
            r,
            0,
            0,
        ]

    def _redraw(self, w: float, h: float) -> None:
        """Reposition the rounded shape and center the label for size (w, h)."""
        self.coords(self._shape, *self._rounded_points(w, h, self._style.radius))
        self.coords(self._label, w / 2, h / 2)

    def _apply_state(self) -> None:
        """Paint colors / cursor / focusability according to the current state."""
        if self._state == _DISABLED:
            self.itemconfig(self._shape, fill=self._style.disabled_bg, outline="")
            self.itemconfig(self._label, fill=self._style.disabled_fg)
            tk.Canvas.configure(self, cursor="", takefocus=0)
        else:
            fill = self._style.hover_bg if self._hovering else self._style.bg
            ring = self._style.focus_color if self._focused else ""
            self.itemconfig(self._shape, fill=fill, outline=ring, width=2 if self._focused else 1)
            self.itemconfig(self._label, fill=self._style.fg)
            tk.Canvas.configure(self, cursor="hand2", takefocus=1)

    @property
    def _disabled(self) -> bool:
        return self._state == _DISABLED

    # -- event handlers -------------------------------------------------------

    def _on_configure(self, event: "tk.Event[Any]") -> None:
        self._redraw(event.width, event.height)

    def _on_enter(self, _event: "tk.Event[Any]") -> None:
        self._hovering = True
        if not self._disabled:
            self.itemconfig(self._shape, fill=self._style.hover_bg)

    def _on_leave(self, _event: "tk.Event[Any]") -> None:
        self._hovering = False
        if not self._disabled:
            self.itemconfig(self._shape, fill=self._style.bg)

    def _on_focus_in(self, _event: "tk.Event[Any]") -> None:
        self._focused = True
        if not self._disabled:
            self.itemconfig(self._shape, outline=self._style.focus_color, width=2)

    def _on_focus_out(self, _event: "tk.Event[Any]") -> None:
        self._focused = False
        self.itemconfig(self._shape, outline="", width=1)

    def _on_click(self, _event: "tk.Event[Any]") -> None:
        if self._disabled:
            return
        self.focus_set()
        self._activate()

    def _on_key_activate(self, _event: "tk.Event[Any]") -> str:
        if not self._disabled:
            self._activate()
        return "break"  # do not propagate Space/Return further

    def _activate(self) -> None:
        if self._command is not None:
            self._command()

    # -- ttk.Button-compatible configuration API ------------------------------

    def configure(self, cnf: Any = None, **kwargs: Any) -> Any:  # type: ignore[override]
        """Configure like a ttk button.

        Intercepts ``text``, ``command``, ``state``, ``width`` and ``variant``;
        everything else is forwarded to the underlying canvas.
        """
        if cnf:
            kwargs.update(cnf)

        relayout = False
        restyle = False

        if "variant" in kwargs:
            self._style = get_button_style(kwargs.pop("variant"))
            self.itemconfig(self._label, font=self._style.font)
            relayout = True
            restyle = True
        if "style" in kwargs:
            style = kwargs.pop("style")
            if isinstance(style, ButtonStyle):
                self._style = style
                self.itemconfig(self._label, font=self._style.font)
                relayout = True
                restyle = True
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self.itemconfig(self._label, text=self._text)
            relayout = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "width" in kwargs:
            # ttk width is measured in characters.
            self._min_char_width = kwargs.pop("width")
            relayout = True
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            restyle = True

        result = tk.Canvas.configure(self, **kwargs) if kwargs else None
        if relayout:
            self._resize_to_content()
        if restyle:
            self._apply_state()
        return result

    # ttk/tk widgets expose config as an alias of configure.
    config = configure

    def cget(self, key: str) -> Any:  # type: ignore[override]
        if key == "text":
            return self._text
        if key == "command":
            return self._command
        if key == "state":
            return self._state
        if key == "width":
            return self._min_char_width
        return tk.Canvas.cget(self, key)

    def __getitem__(self, key: str) -> Any:
        return self.cget(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.configure(**{key: value})

    # -- convenience ----------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Set the button state to ``"normal"`` or ``"disabled"``."""
        self.configure(state=state)

    def invoke(self) -> None:
        """Invoke the command, mirroring ttk.Button.invoke()."""
        if not self._disabled:
            self._activate()
