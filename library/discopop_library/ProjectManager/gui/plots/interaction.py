# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Hover tooltips and click-to-select for the embedded charts.

Chart renderers attach an arbitrary payload to the artists they draw (via
:func:`attach`) and then call :func:`setup_interaction` once per render. Hovering
near an artist that carries a payload shows a floating tooltip; clicking one
reports the payload back to the caller, e.g. to fill an always-visible detail
panel beside the plot.

The payload type is up to the caller -- the Report tab attaches
``ExecutionRecord``s, the Hotspot Detection tab attaches ``HotspotRegion``s --
so this module stays agnostic and takes a formatter for the tooltip text.

Hit testing works in **display (pixel) space**: data-space distances would mix
axis units (a ``ratio`` of 0.5 against an average runtime of 4.8 s) and break
outright on a log-scaled axis. Transforming through ``transData`` makes one pixel
threshold behave identically on every chart.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from discopop_library.ProjectManager.gui.plots import mode_style

# Attribute under which artists carry their payload. Deliberately one shared
# name, so the lookup below finds payloads regardless of which renderer drew them.
METADATA_KEY = "_discopop_record"

# How near the cursor must be (in pixels) to count as hovering an artist.
HIT_RADIUS_PX = 12.0

_INTERACTION_BOUND_KEY = "_discopop_interaction_bound"


def attach(artist: Any, payload: Any) -> None:
    """Attach ``payload`` to ``artist`` so hover/click can recover it.

    For scatter collections the payload is a *sequence* aligned with the
    collection's offsets; for lines and bar patches it is a single object.
    """
    setattr(artist, METADATA_KEY, payload)


def empty_message(ax: Any, message: str) -> None:
    """Render a centred placeholder in an otherwise empty axes."""
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        color=mode_style.REFERENCE_COLOR,
        fontsize=mode_style.ANNOTATION_SIZE,
    )
    ax.set_xticks([])
    ax.set_yticks([])


def find_payload_at_event(figure: Any, event: Any) -> Optional[Any]:
    """The payload of the artist nearest ``event``, or ``None``.

    Shared by hover tooltips and click selection so both react to exactly the
    same set of points, lines and bars.
    """
    if event.inaxes is None or event.x is None or event.y is None:
        return None

    def pixel_distances(ax: Any, points: Any) -> Any:
        """Distance in pixels from the cursor to each of ``points`` (data coords).

        Plain ndarray arithmetic rather than ``numpy`` module functions, so this
        needs no numpy import.
        """
        pixels = ax.transData.transform(points)
        dx = pixels[:, 0] - event.x
        dy = pixels[:, 1] - event.y
        return (dx * dx + dy * dy) ** 0.5

    for ax in figure.axes:
        if not ax.get_visible():
            continue

        # Scatter collections: payload is a sequence parallel to the offsets.
        for collection in ax.collections:
            if not hasattr(collection, "get_offsets"):
                continue
            offsets = collection.get_offsets()
            if len(offsets) == 0:
                continue
            payloads = getattr(collection, METADATA_KEY, None)
            if not payloads:
                continue
            distances = pixel_distances(ax, offsets)
            nearest = int(distances.argmin())
            if distances[nearest] < HIT_RADIUS_PX and nearest < len(payloads):
                return payloads[nearest]

        # Line artists: one payload per line.
        for line in ax.get_lines():
            payload = getattr(line, METADATA_KEY, None)
            if payload is None or not line.get_visible():
                continue
            points = list(zip(line.get_xdata(), line.get_ydata()))
            if not points:
                continue
            if pixel_distances(ax, points).min() < HIT_RADIUS_PX:
                return payload

        # Bar patches: hit when the cursor is inside the bar.
        for patch in ax.patches:
            payload = getattr(patch, METADATA_KEY, None)
            if payload is None or not patch.get_visible():
                continue
            if event.xdata is None or event.ydata is None:
                continue
            bbox = patch.get_bbox() if hasattr(patch, "get_bbox") else patch.get_path().get_extents()
            if bbox.contains(event.xdata, event.ydata):
                return payload
    return None


def setup_interaction(
    figure: Any,
    format_tooltip: Callable[[Any], str],
    on_select: Optional[Callable[[Any], None]] = None,
) -> None:
    """Enable hover tooltips and click-to-select on ``figure``.

    Call after every render. A click that misses every artist is ignored, leaving
    the previous selection displayed. Safe to call headless (silently skips).

    A chart tab re-renders repeatedly while reusing one canvas, so the handlers
    -- which resolve artists via ``figure.axes`` at event time, not bind time --
    only need attaching once; a flag on the canvas prevents duplicate bindings
    from firing the callback several times per click.
    """
    if not hasattr(figure.canvas, "mpl_connect") or not hasattr(figure.canvas, "get_tk_widget"):
        return
    if getattr(figure.canvas, _INTERACTION_BOUND_KEY, False):
        return
    setattr(figure.canvas, _INTERACTION_BOUND_KEY, True)

    _setup_hover_tooltips(figure, format_tooltip)

    def on_click(event: Any) -> None:
        payload = find_payload_at_event(figure, event)
        if payload is not None and on_select is not None:
            on_select(payload)

    figure.canvas.mpl_connect("button_press_event", on_click)


def _setup_hover_tooltips(figure: Any, format_tooltip: Callable[[Any], str]) -> None:
    """Show a sticky label while the cursor rests on an artist with a payload."""
    import tkinter as tk

    tooltip_label: Optional[tk.Label] = None
    last_payload: Optional[Any] = None

    def on_motion(event: Any) -> None:
        nonlocal tooltip_label, last_payload
        payload = find_payload_at_event(figure, event)

        if payload is None:
            if tooltip_label is not None:
                tooltip_label.place_forget()
            last_payload = None
            return

        # Hovering the same artist: nothing to redraw.
        if last_payload is payload:
            return
        last_payload = payload

        text = format_tooltip(payload)
        widget = figure.canvas.get_tk_widget()
        if tooltip_label is None:
            tooltip_label = tk.Label(
                widget,
                text=text,
                background="#fffacd",
                relief=tk.SOLID,
                borderwidth=1,
                font=("TkDefaultFont", 9),
                justify=tk.LEFT,
                padx=4,
                pady=2,
            )
        else:
            tooltip_label.config(text=text)

        x = widget.winfo_pointerx() - widget.winfo_rootx()
        y = widget.winfo_pointery() - widget.winfo_rooty()
        tooltip_label.place(x=x + 10, y=y + 10)

    figure.canvas.mpl_connect("motion_notify_event", on_motion)
