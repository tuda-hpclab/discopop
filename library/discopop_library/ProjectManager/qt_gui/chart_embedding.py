# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Embedding a matplotlib figure in a Qt widget (the counterpart of ``gui/chart_embedding.py``)."""

from typing import Any, Optional, Tuple, cast

from PySide6.QtCore import QSize
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from discopop_library.ProjectManager.plots import interaction
from discopop_library.ProjectManager.qt_gui import widgets

CHART_BACKGROUND = "#f4f5f7"
# the look of the axes (see style_axes): faint horizontal and vertical grid lines, the axis lines at the left and the
# bottom only, labels and ticks in grays
CHART_GRID = "#dfe2e6"
CHART_SPINE = "#b4b8be"
CHART_LABEL = "#3c4048"
CHART_TICK = "#5f6368"
TOOLBAR_ICON_PX = 18


def create_canvas(
    figsize: Tuple[float, float] = (6.0, 3.6),
    dpi: int = 100,
    toolbar: bool = True,
) -> Tuple[QWidget, Any, Any, Optional[Any]]:
    """Create a matplotlib ``Figure`` on a Qt canvas.

    Returns ``(widget, figure, canvas, toolbar_or_None)``: ``widget`` holds the canvas and, below it, the optional
    navigation toolbar (pan / zoom / save); put it into a layout. Draw into ``figure`` and call :func:`redraw`.
    """
    from matplotlib.backends.backend_qt import NavigationToolbar2QT
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    # the charts stay light in both themes; around the plot area an off-white, so a chart is no white block on a page
    figure = Figure(figsize=figsize, dpi=dpi, layout="constrained", facecolor=CHART_BACKGROUND)
    canvas = FigureCanvasQTAgg(figure)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(canvas, 1)
    nav: Optional[Any] = None
    if toolbar:
        nav = NavigationToolbar2QT(canvas, widget)
        # a slim row: smaller icons, on the background of the pane (widgets.CHART_TOOLBAR_NAME)
        nav.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))
        nav.setObjectName(widgets.CHART_TOOLBAR_NAME)
        layout.addWidget(nav)
    interaction.install_tooltip_presenter(canvas, _show_tooltip)
    return widget, figure, canvas, nav


def _show_tooltip(text: Optional[str]) -> None:
    if text is None:
        QToolTip.hideText()
    else:
        QToolTip.showText(QCursor.pos(), text)


def style_axes(figure: Any) -> None:
    """Give the axes of ``figure`` the look of the application: no top and right axis lines, a faint grid behind the
    data, gray labels and ticks, the background of the figure behind the plot area, legends without a frame line.

    Applied after a chart was drawn (by :func:`redraw`), so the charts themselves (``plots``, also drawn into the PDF
    report) keep matplotlib's defaults. Idempotent; 3D axes and color bars keep their look.
    """
    from matplotlib.legend import Legend

    for ax in figure.axes:
        # rectilinear axes only (no 3D, polar or other projections), no color bars
        if getattr(ax, "name", "") != "rectilinear" or ax.get_label() == "<colorbar>":
            continue
        if tuple(ax.get_facecolor()) == (1.0, 1.0, 1.0, 1.0):
            ax.set_facecolor(CHART_BACKGROUND)
        if not len(ax.get_xticks()) and not len(ax.get_yticks()):
            # an empty chart (interaction.empty_message): only its message, no axis lines
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.grid(False)
            continue
        # a twin (twinx / twiny) has its axis at the right resp. top, and the grid of the axes it twins
        y_right = ax.yaxis.get_ticks_position() == "right"
        x_top = ax.xaxis.get_ticks_position() == "top"
        for side, axis_line in (("top", x_top), ("right", y_right), ("bottom", not x_top), ("left", not y_right)):
            ax.spines[side].set_visible(axis_line)
            ax.spines[side].set_color(CHART_SPINE)
        ax.set_axisbelow(True)
        if not (y_right or x_top):
            ax.grid(True, color=CHART_GRID, linewidth=0.8)
        ax.tick_params(colors=CHART_TICK, which="both")
        for tick_label in ax.get_xticklabels() + ax.get_yticklabels():
            tick_label.set_color(CHART_TICK)
        ax.xaxis.label.set_color(CHART_LABEL)
        ax.yaxis.label.set_color(CHART_LABEL)
        ax.title.set_color(CHART_LABEL)
        for child in ax.get_children():
            if isinstance(child, Legend):
                # (the stubs of matplotlib's Legend lack get_frame)
                frame = cast(Any, child).get_frame()
                frame.set_edgecolor("none")
                frame.set_alpha(0.85)


def redraw(canvas: Any) -> None:
    """Schedule a redraw of an embedded canvas (safe to call frequently), in the look of :func:`style_axes`."""
    style_axes(canvas.figure)
    canvas.draw_idle()
