# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Helpers for embedding a matplotlib figure in a Tk frame.

matplotlib and its Tk backend are imported lazily inside the functions so this
module can be imported (and the pure-data helpers next to it unit-tested) in a
headless environment without a display or a Tk build.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Optional, Tuple


def create_canvas(
    parent: tk.Widget,
    figsize: Tuple[float, float] = (6.0, 3.6),
    dpi: int = 100,
    toolbar: bool = True,
) -> Tuple[Any, Any, Optional[Any]]:
    """Create a matplotlib ``Figure`` embedded in ``parent``.

    Returns ``(figure, canvas, toolbar_or_None)``. The canvas widget is packed to
    fill ``parent``; the optional navigation toolbar (pan/zoom/save) is packed
    below it. Draw into ``figure`` and call :func:`redraw` to refresh.
    """
    from matplotlib.backends.backend_tkagg import (  # type: ignore[attr-defined]
        FigureCanvasTkAgg,
        NavigationToolbar2Tk,
    )
    from matplotlib.figure import Figure

    figure = Figure(figsize=figsize, dpi=dpi, layout="constrained")
    canvas = FigureCanvasTkAgg(figure, master=parent)
    nav: Optional[Any] = None
    if toolbar:
        # pack_toolbar=False lets us control geometry; pack it under the canvas.
        nav = NavigationToolbar2Tk(canvas, parent, pack_toolbar=False)
        nav.update()
        nav.pack(side=tk.BOTTOM, fill=tk.X)
    canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    return figure, canvas, nav


def redraw(canvas: Any) -> None:
    """Schedule a redraw of an embedded canvas (safe to call frequently)."""
    canvas.draw_idle()


def force_resize_redraw(widget: tk.Misc) -> None:
    """Re-render embedded matplotlib canvases at their current size.

    A ``FigureCanvasTkAgg`` widget only rasterizes the figure at the correct
    resolution in its ``<Configure>`` handler. When a canvas is built while the Tk
    event loop is blocked (e.g. during an in-process run) it renders at the wrong
    size; synthesizing a ``<Configure>`` with the now-correct geometry triggers the
    redraw a manual window resize would otherwise be needed for. Mirrors the
    approach in ``explorer_integration._redraw_embedded_canvases``.
    """
    try:
        widget.update_idletasks()
    except tk.TclError:
        return
    _synthesize_configure(widget)


def _synthesize_configure(widget: tk.Misc) -> None:
    for child in widget.winfo_children():
        _synthesize_configure(child)
    if widget.winfo_class() == "Canvas":
        width = widget.winfo_width()
        height = widget.winfo_height()
        if width > 1 and height > 1:
            try:
                widget.event_generate("<Configure>", width=width, height=height)
            except tk.TclError:
                pass
