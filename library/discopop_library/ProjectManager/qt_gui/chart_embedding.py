# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Embedding a matplotlib figure in a Qt widget (the counterpart of ``gui/chart_embedding.py``)."""

from typing import Any, Optional, Tuple

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from discopop_library.ProjectManager.plots import interaction


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

    figure = Figure(figsize=figsize, dpi=dpi, layout="constrained")
    canvas = FigureCanvasQTAgg(figure)
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(canvas, 1)
    nav: Optional[Any] = None
    if toolbar:
        nav = NavigationToolbar2QT(canvas, widget)
        layout.addWidget(nav)
    interaction.install_tooltip_presenter(canvas, _show_tooltip)
    return widget, figure, canvas, nav


def _show_tooltip(text: Optional[str]) -> None:
    if text is None:
        QToolTip.hideText()
    else:
        QToolTip.showText(QCursor.pos(), text)


def redraw(canvas: Any) -> None:
    """Schedule a redraw of an embedded canvas (safe to call frequently)."""
    canvas.draw_idle()
