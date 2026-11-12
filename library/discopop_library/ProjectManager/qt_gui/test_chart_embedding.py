# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The look of the embedded charts: applied by ``redraw`` on top of what the plots drew."""

from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.plots import interaction
from discopop_library.ProjectManager.qt_gui import chart_embedding


def test_redraw_gives_the_axes_the_look_of_the_application(qtbot: QtBot) -> None:
    widget, figure, canvas, _ = chart_embedding.create_canvas()
    qtbot.addWidget(widget)
    ax = figure.add_subplot(111)
    ax.plot([0, 1], [0, 1])
    chart_embedding.redraw(canvas)
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
    assert ax.spines["left"].get_visible() and ax.xaxis.get_gridlines()[0].get_visible()
    # twice is the same as once
    chart_embedding.redraw(canvas)
    assert ax.spines["left"].get_visible() and not ax.spines["top"].get_visible()


def test_an_empty_chart_keeps_only_its_message(qtbot: QtBot) -> None:
    widget, figure, canvas, _ = chart_embedding.create_canvas()
    qtbot.addWidget(widget)
    ax = figure.add_subplot(111)
    interaction.empty_message(ax, "Nothing yet")
    chart_embedding.redraw(canvas)
    assert not any(spine.get_visible() for spine in ax.spines.values())


def test_twin_and_polar_axes(qtbot: QtBot) -> None:
    widget, figure, canvas, _ = chart_embedding.create_canvas()
    qtbot.addWidget(widget)
    ax = figure.add_subplot(121)
    twin = ax.twinx()
    polar = figure.add_subplot(122, projection="polar")
    chart_embedding.redraw(canvas)  # no KeyError for the spines a polar axes lacks
    # the twin's axis is at the right
    assert twin.spines["right"].get_visible() and not twin.spines["left"].get_visible()
    assert ax.spines["left"].get_visible() and not ax.spines["right"].get_visible()
    assert polar.spines["polar"].get_visible()
