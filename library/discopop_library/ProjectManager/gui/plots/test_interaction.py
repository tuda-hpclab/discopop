# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Hit-testing tests for the shared chart interaction layer.

These render onto the Agg backend (no display needed) because the pixel-space hit
testing only means anything once a figure has an actual transform -- which is the
whole point of doing it in display coordinates: it is the only formulation that
works on a log-scaled axis and across axes whose units differ by orders of
magnitude.
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from discopop_library.ProjectManager.gui.plots import hotspot_charts, interaction, report_charts  # noqa: E402
from discopop_library.ProjectManager.gui.plots.data import ExecutionRecord  # noqa: E402
from discopop_library.ProjectManager.gui.plots.hotspot_data import (  # noqa: E402
    HOTNESS_NO,
    HOTNESS_YES,
    KIND_LOOP,
    HotspotRegion,
    RegionKey,
)


@dataclass
class _Event:
    """The attributes :func:`find_payload_at_event` reads off a mouse event.

    Standing in for ``matplotlib.backend_bases.MouseEvent`` keeps these tests
    independent of that constructor's signature.
    """

    inaxes: Any
    x: float
    y: float
    xdata: Optional[float]
    ydata: Optional[float]


def _figure() -> Figure:
    figure = Figure(figsize=(6, 3.6), layout="constrained")
    FigureCanvasAgg(figure)
    return figure


def _region(csid: int, avg: float, hotness: str, ratio: float) -> HotspotRegion:
    return HotspotRegion(
        key=RegionKey(path="/proj/lulesh.cc", line=1000 + csid, kind=KIND_LOOP),
        csid=csid,
        runtimes=[avg * 0.5, avg * 1.5],
        avg=avg,
        minimum=avg * 0.5,
        maximum=avg * 1.5,
        ratio=ratio,
        hotness=hotness,
        share=0.5,
    )


def _regions() -> List[HotspotRegion]:
    # Averages four orders of magnitude apart, so a data-space threshold would
    # fail here while a pixel-space one does not.
    return [_region(1, 4.8, HOTNESS_YES, 0.84), _region(2, 0.03, HOTNESS_NO, 0.50)]


def _click_at(
    figure: Figure, ax: Any, data_point: Tuple[float, float], offset: Tuple[float, float] = (0.0, 0.0)
) -> Any:
    """Click at ``data_point``, optionally displaced by a pixel ``offset``."""
    pixel_x, pixel_y = ax.transData.transform(data_point)
    pixel_x += offset[0]
    pixel_y += offset[1]
    # Bar hit-testing works in data coordinates, so supply both representations
    # of the same cursor position, exactly as matplotlib's own event does.
    data_x, data_y = ax.transData.inverted().transform((pixel_x, pixel_y))
    event = _Event(inaxes=ax, x=pixel_x, y=pixel_y, xdata=data_x, ydata=data_y)
    return interaction.find_payload_at_event(figure, event)


def test_scatter_hit_on_log_axis() -> None:
    regions = _regions()
    figure = _figure()
    hotspot_charts.render_quadrant(figure, regions)
    figure.canvas.draw()
    ax = figure.axes[0]

    hit = _click_at(figure, ax, (regions[0].avg, regions[0].ratio))
    assert hit is not None and hit.csid == 1

    # the far smaller region is still individually selectable
    hit = _click_at(figure, ax, (regions[1].avg, regions[1].ratio))
    assert hit is not None and hit.csid == 2


def test_click_far_from_any_artist_selects_nothing() -> None:
    """A miss must leave the previous selection alone rather than clearing it."""
    regions = _regions()
    figure = _figure()
    hotspot_charts.render_quadrant(figure, regions)
    figure.canvas.draw()
    assert _click_at(figure, figure.axes[0], (regions[0].avg, regions[0].ratio), offset=(120.0, 90.0)) is None


def test_bar_hit_inside_patch() -> None:
    regions = _regions()
    figure = _figure()
    hotspot_charts.render_top_bars(figure, regions, 10)
    figure.canvas.draw()
    # bars are drawn hottest-last so the hottest sits at the top position
    hit = _click_at(figure, figure.axes[0], (regions[0].avg * 0.5, 1))
    assert hit is not None and hit.csid == 1


def test_line_hit_on_run_profile() -> None:
    region = _regions()[0]
    figure = _figure()
    hotspot_charts.render_run_profile(figure, region)
    figure.canvas.draw()
    hit = _click_at(figure, figure.axes[0], (1, region.runtimes[1]))
    assert hit is not None and hit.csid == region.csid


def test_report_pareto_still_resolves_records() -> None:
    """Regression guard: the Report tab shares this hit-testing layer."""
    records = [
        ExecutionRecord("c", "execute.sh", "par", "", 8, [], 4.0, 0, False, True, 2.5, 2.5 / 8),
        ExecutionRecord("c", "execute.sh", "seq", "", 1, [], 10.0, 0, False, True, 1.0, 1.0),
    ]
    figure = _figure()
    report_charts.render_pareto(figure, records)
    figure.canvas.draw()
    efficiency, speedup = records[0].efficiency, records[0].speedup
    assert efficiency is not None and speedup is not None
    hit = _click_at(figure, figure.axes[0], (efficiency, speedup))
    assert hit is not None and hit.mode == "par" and hit.speedup == 2.5


def test_empty_figure_yields_no_payload() -> None:
    figure = _figure()
    hotspot_charts.render_quadrant(figure, [])
    figure.canvas.draw()
    ax = figure.axes[0]
    assert interaction.find_payload_at_event(figure, _Event(ax, 100.0, 100.0, 0.5, 0.5)) is None
