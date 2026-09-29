# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Accumulate the autotuner progress stream and render the live search plot.

:class:`ProgressModel` ingests the event dicts produced by the autotuner
(``baseline`` / ``measurement`` / ``generation`` / ``result``) and exposes the
summary tile values and the data the chart needs. :func:`render` draws into a
matplotlib figure, adapting to the algorithm:

* if generation events are present (evolutionary) -> best-so-far / population
  average / measured average / convergence threshold lines per generation, with
  the individuals measured in each generation scattered by validity. Note that
  the population average covers the surviving population while the measured
  average covers exactly the scattered points, so only the latter is expected to
  run through the middle of the dots;
* otherwise (greedy / coordinate descent / measure-only) -> the best-so-far
  speedup line with each measured configuration scattered by validity.

The model is matplotlib- and Tk-free so it can be unit-tested directly; only
:func:`render` touches a figure (passed in by the caller).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from discopop_library.ProjectManager.gui.plots import mode_style
from discopop_library.ProjectManager.gui.plots.data import best_so_far


@dataclass
class Measurement:
    index: int
    suggestions: List[int]
    speedup: Optional[float]
    runtime: Optional[float]
    status: str  # "valid" | "invalid" | "failed" | "not_applied"
    generation: Optional[int]
    # Requested suggestions that never reached the code. When non-empty the search
    # step carries no measurement at all: the configuration was skipped because its
    # code was still the unmodified original.
    failed_suggestions: List[int] = field(default_factory=list)

    @property
    def application_failed(self) -> bool:
        return self.status == mode_style.NOT_APPLIED_STATUS


@dataclass
class Generation:
    generation: int
    max_fitness: float
    avg_fitness: float
    threshold: float
    # Average over the individuals measured in this generation -- exactly the points
    # scattered for it. ``None`` for runs recorded before this field existed.
    generation_avg_fitness: Optional[float] = None


@dataclass
class ProgressModel:
    """Running state of one autotuning search, built from progress events."""

    thread_count: int = 1
    measurements: List[Measurement] = field(default_factory=list)
    generations: List[Generation] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None

    def ingest(self, event: Dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "baseline":
            self.thread_count = int(event.get("thread_count", self.thread_count))
        elif kind == "measurement":
            failed_suggestions = [int(s) for s in event.get("failed_suggestions", [])]
            application_failed = bool(event.get("application_failed", False)) or bool(failed_suggestions)
            self.measurements.append(
                Measurement(
                    index=int(event.get("index", len(self.measurements) + 1)),
                    suggestions=[int(s) for s in event.get("suggestions", [])],
                    speedup=event.get("speedup"),
                    runtime=event.get("runtime"),
                    status=mode_style.autotuner_status(
                        int(event.get("return_code", 0)),
                        bool(event.get("valid", False)),
                        bool(event.get("tsan", False)),
                        application_failed=application_failed,
                    ),
                    generation=event.get("generation"),
                    failed_suggestions=failed_suggestions,
                )
            )
        elif kind == "generation":
            self.generations.append(
                Generation(
                    generation=int(event["generation"]),
                    max_fitness=float(event["max_fitness"]),
                    avg_fitness=float(event["avg_fitness"]),
                    threshold=float(event["threshold"]),
                    generation_avg_fitness=(
                        float(event["generation_avg_fitness"])
                        if event.get("generation_avg_fitness") is not None
                        else None
                    ),
                )
            )
        elif kind == "result":
            self.result = event

    @classmethod
    def from_events(cls, events: Sequence[Dict[str, Any]]) -> "ProgressModel":
        model = cls()
        for event in events:
            model.ingest(event)
        return model

    def is_evolutionary(self) -> bool:
        return bool(self.generations)

    def _valid(self) -> List[Measurement]:
        return [m for m in self.measurements if m.status == "valid" and m.speedup is not None]

    def best_speedup(self) -> Optional[float]:
        valid = self._valid()
        return max((m.speedup for m in valid), default=None)  # type: ignore[type-var]

    def counts(self) -> Tuple[int, int, int, int]:
        """(valid, invalid, failed, not_applied) over all reported measurements."""
        valid = sum(1 for m in self.measurements if m.status == "valid")
        invalid = sum(1 for m in self.measurements if m.status == "invalid")
        failed = sum(1 for m in self.measurements if m.status == "failed")
        not_applied = sum(1 for m in self.measurements if m.status == mode_style.NOT_APPLIED_STATUS)
        return valid, invalid, failed, not_applied

    def not_applied_measurements(self) -> List[Measurement]:
        """The search steps whose patches could not be applied (never measured)."""
        return [m for m in self.measurements if m.status == mode_style.NOT_APPLIED_STATUS]

    def not_applied_warning(self) -> Optional[str]:
        """A warning line for the GUI, or None when every configuration was patched."""
        skipped = self.not_applied_measurements()
        if not skipped:
            return None
        ids = sorted({s for m in skipped for s in (m.failed_suggestions or m.suggestions)})
        return (
            "⚠ "
            + str(len(skipped))
            + " configuration(s) could not be patched and were not measured"
            + (" (suggestions: " + ", ".join(str(i) for i in ids) + ")" if ids else "")
            + "."
        )

    def summary_tiles(self) -> List[Tuple[str, str]]:
        """(label, value) pairs for the summary tile row above the plot."""
        best = self.best_speedup()
        valid, invalid, failed, not_applied = self.counts()
        if best is not None:
            best_measurement = max(self._valid(), key=lambda m: m.speedup)  # type: ignore[arg-type,return-value]
            runtime = best_measurement.runtime
            efficiency = best / self.thread_count if self.thread_count else None
        else:
            runtime = None
            efficiency = None
        return [
            ("Best speedup", f"{best:.2f}×" if best is not None else "—"),
            ("Efficiency", f"{efficiency:.2f}" if efficiency is not None else "—"),
            ("Best runtime", f"{runtime:.2f} s" if runtime is not None else "—"),
            ("Evaluated", str(len(self.measurements))),
            ("Valid", str(valid)),
            ("Invalid / failed", f"{invalid} / {failed}"),
            ("Not applied", str(not_applied)),
        ]


def render(figure: Any, model: ProgressModel) -> None:
    """Draw ``model`` into ``figure`` (cleared first). Caller redraws the canvas."""
    figure.clear()
    ax = figure.add_subplot(111)

    if not model.measurements and not model.generations:
        ax.text(
            0.5,
            0.5,
            "Run the search to see live progress",
            ha="center",
            va="center",
            color=mode_style.REFERENCE_COLOR,
            fontsize=mode_style.ANNOTATION_SIZE,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        return

    if model.is_evolutionary():
        _render_generations(ax, model)
    else:
        _render_steps(ax, model)


def _annotate_not_applied(ax: Any, model: ProgressModel) -> None:
    """Spell out the not-applied count in the plot, not only in the legend."""
    warning = model.not_applied_warning()
    if warning is None:
        return
    ax.text(
        0.99,
        0.02,
        warning,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=mode_style.ANNOTATION_SIZE,
        color=mode_style.status_color(mode_style.NOT_APPLIED_STATUS),
    )


def _baseline_line(ax: Any, x_right: float) -> None:
    ax.axhline(1.0, color=mode_style.REFERENCE_COLOR, linewidth=1.2, linestyle="--")
    ax.annotate(
        "full-parallel baseline 1×",
        xy=(x_right, 1.0),
        xytext=(-4, 4),
        textcoords="offset points",
        ha="right",
        fontsize=mode_style.ANNOTATION_SIZE,
        color=mode_style.REFERENCE_COLOR,
    )


def _scatter_by_status(ax: Any, xy_by_status: Dict[str, List[Tuple[float, float]]]) -> None:
    for status in mode_style.STATUS_ORDER:
        pts = xy_by_status.get(status)
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        not_applied = status == mode_style.NOT_APPLIED_STATUS
        ax.scatter(
            xs,
            ys,
            # a not-applied step has no measurement: give it a larger, distinctly
            # shaped marker so it cannot be read as a data point at speedup 0
            s=mode_style.AUTOTUNER_SCATTER_SIZE * (1.4 if not_applied else 1.0),
            marker=mode_style.status_marker(status),
            color=mode_style.status_color(status),
            edgecolors="white",
            linewidths=0.6,
            zorder=4 if not_applied else 3,
            label=mode_style.status_label(status),
        )


def _render_steps(ax: Any, model: ProgressModel) -> None:
    xy_by_status: Dict[str, List[Tuple[float, float]]] = {}
    for m in model.measurements:
        y = m.speedup if (m.status == "valid" and m.speedup is not None) else 0.0
        xy_by_status.setdefault(m.status, []).append((float(m.index), float(y)))
    _annotate_not_applied(ax, model)

    series = best_so_far([(m.index, m.speedup, m.status == "valid") for m in model.measurements])
    if series:
        ax.plot(
            [p[0] for p in series],
            [p[1] for p in series],
            color=mode_style.CONFIG_PALETTE[0],
            linewidth=2.2,
            zorder=2,
            label="best so far",
        )
    _scatter_by_status(ax, xy_by_status)
    x_right = float(model.measurements[-1].index) if model.measurements else 1.0
    _baseline_line(ax, x_right)
    ax.set_xlabel("Configurations evaluated")
    ax.set_ylabel("Speedup ×")
    ax.set_ylim(bottom=0)
    mode_style.style_legend(ax.legend(loc="upper left", fontsize=mode_style.LEGEND_SIZE, ncol=2))
    mode_style.style_axes(ax)


def _render_generations(ax: Any, model: ProgressModel) -> None:
    gens = model.generations
    gx = [g.generation for g in gens]
    ax.plot(gx, [g.max_fitness for g in gens], color=mode_style.CONFIG_PALETTE[0], linewidth=2.2, label="best (max)")
    ax.plot(
        gx, [g.avg_fitness for g in gens], color=mode_style.CONFIG_PALETTE[2], linewidth=2.0, label="population avg"
    )
    # Average over the individuals measured per generation -- the line the scattered
    # points are actually distributed around. Older runs have no such data.
    measured_avg = [(g.generation, g.generation_avg_fitness) for g in gens if g.generation_avg_fitness is not None]
    if measured_avg:
        ax.plot(
            [p[0] for p in measured_avg],
            [p[1] for p in measured_avg],
            color=mode_style.CONFIG_PALETTE[6],
            linewidth=1.8,
            linestyle=":",
            label="measured avg",
        )
    ax.plot(
        gx,
        [g.threshold for g in gens],
        color=mode_style.CONFIG_PALETTE[3],
        linewidth=1.8,
        linestyle="--",
        label="conv. threshold",
    )

    xy_by_status: Dict[str, List[Tuple[float, float]]] = {}
    for m in model.measurements:
        if m.generation is None:
            continue
        y = m.speedup if (m.status == "valid" and m.speedup is not None) else 0.0
        xy_by_status.setdefault(m.status, []).append((float(m.generation), float(y)))
    _scatter_by_status(ax, xy_by_status)
    _annotate_not_applied(ax, model)

    x_right = float(max(gx)) if gx else 1.0
    _baseline_line(ax, x_right)
    ax.set_xlabel("Generation")
    ax.set_ylabel("Fitness (speedup ×)")
    ax.set_ylim(bottom=0)
    mode_style.style_legend(ax.legend(loc="upper left", fontsize=mode_style.LEGEND_SIZE, ncol=2))
    mode_style.style_axes(ax)
