# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any

from discopop_library.ProjectManager.plots.data import ExecutionRecord
from discopop_library.ProjectManager.plots.report_charts import (
    best_of,
    metric_value,
    more_is_better,
    not_applied_note,
    not_applied_records,
    record_status_text,
)


def _rec(config: str, mode: str, threads: int, time: float, speedup: float, valid: bool = True) -> ExecutionRecord:
    return ExecutionRecord(
        config=config,
        script="execute.sh",
        mode=mode,
        label="",
        thread_count=threads,
        applied_suggestions=[],
        time=time,
        code=0 if valid else 1,
        timeout=False,
        valid=valid,
        speedup=speedup,
        efficiency=speedup / threads,
    )


def test_metric_value() -> None:
    r = _rec("c", "par", 8, 4.0, 2.5)
    assert metric_value(r, "runtime") == 4.0
    assert metric_value(r, "threads") == 8.0
    assert metric_value(r, "speedup") == 2.5
    efficiency = metric_value(r, "efficiency")
    assert efficiency is not None and abs(efficiency - 2.5 / 8) < 1e-9
    assert metric_value(r, "bogus") is None


def test_more_is_better() -> None:
    assert more_is_better("speedup")
    assert more_is_better("efficiency")
    assert not more_is_better("runtime")


def test_best_of_prefers_max_speedup() -> None:
    records = [
        _rec("c", "par", 8, 5.0, 2.0),
        _rec("c", "par", 8, 4.0, 2.5),  # best speedup for (c, par)
        _rec("c", "dp", 8, 3.0, 3.3),
        _rec("c", "par", 8, 1.0, 9.9, valid=False),  # invalid ignored despite high speedup
    ]
    best = best_of(records, "speedup")
    assert best[("c", "par")].speedup == 2.5
    assert best[("c", "dp")].speedup == 3.3


def test_best_of_prefers_min_runtime() -> None:
    records = [
        _rec("c", "par", 8, 5.0, 2.0),
        _rec("c", "par", 8, 4.0, 2.5),  # smallest runtime
    ]
    best = best_of(records, "runtime")
    assert best[("c", "par")].time == 4.0


def test_best_of_ignores_all_invalid() -> None:
    records = [_rec("c", "par", 8, 4.0, 2.5, valid=False)]
    assert best_of(records, "speedup") == {}


def _not_applied(config: str = "c", mode: str = "par", requested: int = 27) -> ExecutionRecord:
    """A record for a run that was skipped because its patches did not apply."""
    return ExecutionRecord(
        config=config,
        script="execute.sh",
        mode=mode,
        label="",
        thread_count=8,
        applied_suggestions=[],
        time=0.0,
        code=-1,
        timeout=False,
        valid=False,
        speedup=None,
        efficiency=None,
        requested_suggestions=[requested],
        failed_suggestions=[requested],
        application_failed=True,
        executed=False,
    )


def test_best_of_never_picks_an_unapplied_run() -> None:
    records = [_rec("c", "par", 8, 4.0, 2.5), _not_applied()]
    best = best_of(records, "speedup")
    assert best[("c", "par")].speedup == 2.5
    assert best_of([_not_applied()], "runtime") == {}


def test_not_applied_records_are_identified_and_summarized() -> None:
    records = [_rec("c", "par", 8, 4.0, 2.5), _not_applied(requested=27)]
    assert not_applied_records(records) == [records[1]]
    note = not_applied_note(records)
    assert note is not None and "27" in note and "1 run" in note


def test_no_note_when_every_patch_applied() -> None:
    assert not_applied_note([_rec("c", "par", 8, 4.0, 2.5)]) is None
    assert not_applied_note([]) is None


def test_record_status_text_distinguishes_all_states() -> None:
    assert record_status_text(_rec("c", "par", 8, 4.0, 2.5)) == "✓ valid"
    assert record_status_text(_rec("c", "par", 8, 4.0, 2.5, valid=False)) == "✗ failed"
    assert record_status_text(_not_applied()) == "⚠ not applied"


def Any_ax(figure: Any) -> Any:
    return figure.axes[0]


def _amdahl_rec(speedup: float, threads: int, p: float, valid: bool = True) -> ExecutionRecord:
    from discopop_library.Amdahl.model import amdahl_ceiling, amdahl_limit

    r = _rec("c", "par", threads, 1.0, speedup, valid)
    r.parallel_fraction = p
    r.amdahl_ceiling = amdahl_ceiling(p, threads)
    r.amdahl_limit = amdahl_limit(p)
    return r


def test_amdahl_points_counts_records_without_ceiling() -> None:
    from discopop_library.ProjectManager.plots.report_charts import amdahl_points

    known = _amdahl_rec(2.0, 4, 0.8)
    unknown = _rec("c", "par", 4, 1.0, 2.0)
    usable, missing = amdahl_points([known, unknown])
    assert usable == [known] and missing == 1
    assert amdahl_points([known, _amdahl_rec(1.0, 4, 0.5, valid=False)], valid_only=True)[0] == [known]


def test_amdahl_scatter_all_modes_and_clipped_limit() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import AMDAHL_X_MODES, render_amdahl_scatter

    # p = 0.999 -> unlimited limit ~1000x, far beyond the axis
    records = [_amdahl_rec(2.0, 4, 0.8), _amdahl_rec(3.5, 4, 0.999), _amdahl_rec(1.5, 2, 1.0)]
    for mode in AMDAHL_X_MODES:
        figure = Figure()
        render_amdahl_scatter(figure, records, x_mode=mode)
        ax: Any = figure.axes[0]
        assert ax.get_xlim()[1] < 10  # the 1000x limit does not set the range
    # in "both" mode: a filled point and a hollow limit marker per group
    figure = Figure()
    render_amdahl_scatter(figure, records, x_mode="both")
    assert len(Any_ax(figure).collections) >= 2


def test_amdahl_charts_without_data_show_a_message() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import render_amdahl_3d, render_amdahl_scatter

    for render in (render_amdahl_scatter, render_amdahl_3d):
        figure = Figure()
        render(figure, [_rec("c", "par", 4, 1.0, 2.0)])
        assert figure.axes


def test_amdahl_3d_plots_ceiling_efficiency_speedup() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import render_amdahl_3d

    figure = Figure()
    render_amdahl_3d(figure, [_amdahl_rec(2.0, 4, 0.8), _amdahl_rec(3.0, 8, 0.9)])
    ax: Any = figure.axes[0]
    assert ax.name == "3d"
    assert (ax.get_xlabel(), ax.get_ylabel(), ax.get_zlabel()) == ("Amdahl ceiling ×", "Efficiency", "Speedup ×")


def test_tooltip_mentions_both_ceilings() -> None:
    from discopop_library.ProjectManager.plots.report_charts import _format_record_tooltip

    text = _format_record_tooltip(_amdahl_rec(2.0, 4, 0.75))
    assert "Amdahl ceiling (4 threads): 2.286×" in text and "unlimited threads): 4.000×" in text


def test_bubble_chart_sizes_follow_efficiency() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import bubble_area, render_amdahl_scatter

    low, high = _amdahl_rec(1.0, 4, 0.8), _amdahl_rec(3.5, 4, 0.9)  # efficiency 0.25 and 0.875
    figure = Figure()
    render_amdahl_scatter(figure, [low, high], x_mode="threads", size_by_efficiency=True)
    sizes = list(Any_ax(figure).collections[0].get_sizes())
    assert sizes == [bubble_area(0.25), bubble_area(0.875)]
    assert bubble_area(5.0) == bubble_area(1.2)  # outliers are capped, not off the chart
    labels = [t.get_text() for t in Any_ax(figure).get_legend().get_texts()]
    assert "efficiency 0.5" in labels


def test_3d_chart_views_stems_plane_and_efficiency_axis() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import AMDAHL_3D_VIEWS, render_amdahl_3d

    normal = _amdahl_rec(2.0, 4, 0.8)
    superlinear = _amdahl_rec(5.0, 4, 0.99)  # efficiency 1.25
    figure = Figure()
    render_amdahl_3d(figure, [normal])
    ax = Any_ax(figure)
    assert ax.get_ylim() == (0.0, 1.1) and ax.get_xlim()[0] == 0.0 and ax.get_zlim()[0] == 0.0
    for view, (elev, azim) in AMDAHL_3D_VIEWS.items():
        render_amdahl_3d(figure, [normal], view=view)
        ax = Any_ax(figure)
        if view != "free":
            assert (ax.elev, ax.azim) == (elev, azim)
    # outliers extend the axis instead of being clipped
    render_amdahl_3d(figure, [normal, superlinear])
    assert Any_ax(figure).get_ylim()[1] > 1.25


def test_3d_free_view_keeps_the_users_rotation() -> None:
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots.report_charts import render_amdahl_3d

    figure = Figure()
    render_amdahl_3d(figure, [_amdahl_rec(2.0, 4, 0.8)], view="free")
    Any_ax(figure).view_init(elev=40, azim=10)
    render_amdahl_3d(figure, [_amdahl_rec(2.0, 4, 0.8)], view="free")
    assert (Any_ax(figure).elev, Any_ax(figure).azim) == (40, 10)


def test_3d_points_are_hit_by_projection() -> None:
    from types import SimpleNamespace

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from discopop_library.ProjectManager.plots import interaction
    from discopop_library.ProjectManager.plots.report_charts import render_amdahl_3d

    a, b = _amdahl_rec(2.0, 4, 0.8), _amdahl_rec(3.5, 4, 0.9)
    figure = Figure()
    FigureCanvasAgg(figure)
    render_amdahl_3d(figure, [a, b])
    figure.canvas.draw()
    ax = Any_ax(figure)
    from mpl_toolkits.mplot3d import proj3d  # type: ignore[import-untyped]

    for target, (x, y, z) in (
        (a, (a.amdahl_ceiling, a.efficiency, a.speedup)),
        (b, (b.amdahl_ceiling, b.efficiency, b.speedup)),
    ):
        px, py, _ = proj3d.proj_transform(x, y, z, ax.get_proj())
        dx, dy = ax.transData.transform((px, py))
        event = SimpleNamespace(inaxes=ax, x=dx + 2, y=dy - 2)
        assert interaction.find_payload_at_event(figure, event) is target
    assert interaction.find_payload_at_event(figure, SimpleNamespace(inaxes=ax, x=0, y=0)) is None
