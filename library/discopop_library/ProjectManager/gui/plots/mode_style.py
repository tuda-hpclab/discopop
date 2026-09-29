# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Single source of truth for how results are encoded visually.

The shared encoding language across every results chart:

* **colour = configuration** (a fixed categorical palette, assigned by stable
  sorted order so filtering a subset never repaints the survivors),
* **marker shape + line dash = execution mode** (seq / par / dp / hd), and
* **status colour = validity** (valid / invalid / failed / not_applied).

Values are plain hex / matplotlib marker codes so this module stays free of Tk
and matplotlib and can be unit-tested directly.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

# Categorical palette for configurations. These are the light-mode hues validated
# for colour-vision-deficiency separation and contrast (dataviz palette check).
# Hues are assigned in this fixed order and never cycled within a chart until the
# palette is exhausted, at which point they wrap.
CONFIG_PALETTE: Tuple[str, ...] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#8b5a2b",  # brown
)

# Execution mode -> matplotlib marker code.
MODE_MARKERS: Dict[str, str] = {
    "seq": "o",  # circle
    "par": "s",  # square
    "dp": "^",  # triangle
    "hd": "D",  # diamond
}
DEFAULT_MARKER = "o"

# Execution mode -> matplotlib dash pattern (``(None, None)`` means a solid line).
MODE_DASHES: Dict[str, Tuple[Optional[float], ...]] = {
    "seq": (1, 2),
    "par": (None, None),
    "dp": (6, 3),
    "hd": (2, 2),
}
DEFAULT_DASHES: Tuple[Optional[float], ...] = (None, None)

# Validity status -> colour. Kept separate from the categorical palette; these are
# reserved for state and never reused as a "series colour".
#
# ``not_applied`` is its own state on purpose: the parallelization suggestions never
# reached the code, so nothing parallel was ever measured. Folding it into "failed"
# (a run that broke) or into "valid" (a run without speedup) would hide exactly the
# case where an unmodified sequential run masquerades as a parallel one.
STATUS_COLORS: Dict[str, str] = {
    "valid": "#2e7d32",  # green
    "invalid": "#e65100",  # orange
    "failed": "#c62828",  # red
    "not_applied": "#7b1fa2",  # purple
}

# Every status, in the order charts should draw and list them.
STATUS_ORDER: Tuple[str, ...] = ("valid", "invalid", "failed", "not_applied")

# Human-readable status names for legends, tables and tooltips.
STATUS_LABELS: Dict[str, str] = {
    "valid": "valid",
    "invalid": "invalid",
    "failed": "failed",
    "not_applied": "patch not applied",
}

NOT_APPLIED_STATUS = "not_applied"

# A distinct marker on top of the distinct colour: a not-applied point carries no
# measurement, so it must not be mistaken for a data point at the same position.
STATUS_MARKERS: Dict[str, str] = {
    "valid": "o",
    "invalid": "o",
    "failed": "o",
    "not_applied": "X",
}

# Neutral / reference colours (baselines, ideal-linear lines, grid emphasis).
REFERENCE_COLOR = "#8b919b"

# Font sizes (points) for the embedded charts. Slightly larger than the matplotlib
# default so labels stay readable inside a compact panel canvas.
AXIS_LABEL_SIZE = 12
TICK_LABEL_SIZE = 10
LEGEND_SIZE = 10
ANNOTATION_SIZE = 10
LEGEND_TITLE_SIZE = 11

# Marker sizes for the embedded charts.
SCATTER_SIZE = 85  # scatter marker area (points^2) for the report charts
AUTOTUNER_SCATTER_SIZE = 65  # autotuning individuals (there can be many per run)
LINE_MARKER_SIZE = 10  # marker diameter on the scaling lines


def assign_config_colors(configs: Sequence[str]) -> Dict[str, str]:
    """Map each configuration to a fixed colour, assigned by sorted order.

    Pass the *full* set of configurations (not a filtered subset) so a chart that
    later hides some configurations keeps the remaining ones on their colours.
    """
    ordered = sorted(set(configs))
    return {config: CONFIG_PALETTE[i % len(CONFIG_PALETTE)] for i, config in enumerate(ordered)}


def mode_marker(mode: str) -> str:
    """matplotlib marker code for an execution mode (circle for unknown modes)."""
    return MODE_MARKERS.get(mode, DEFAULT_MARKER)


def mode_dashes(mode: str) -> Tuple[Optional[float], ...]:
    """matplotlib dash pattern for an execution mode (solid for unknown modes)."""
    return MODE_DASHES.get(mode, DEFAULT_DASHES)


def status_color(status: str) -> str:
    """Colour for a validity status; falls back to the failed colour."""
    return STATUS_COLORS.get(status, STATUS_COLORS["failed"])


def status_marker(status: str) -> str:
    """matplotlib marker code for a validity status."""
    return STATUS_MARKERS.get(status, "o")


def status_label(status: str) -> str:
    """Human-readable name of a validity status."""
    return STATUS_LABELS.get(status, status)


def execution_status(valid: bool, timeout: bool = False, application_failed: bool = False) -> str:
    """Reduce an execution's flags to a status key for :func:`status_color`.

    ``application_failed`` wins over everything else: such a record is not a
    measurement of the configuration it is labelled with -- the requested patches were
    never applied, so the run was skipped -- and must be shown as its own state.
    """
    if application_failed:
        return NOT_APPLIED_STATUS
    if valid:
        return "valid"
    return "failed"


def style_axes(ax: Any) -> None:
    """Apply the shared (enlarged) font sizes to an axes' labels and ticks."""
    ax.xaxis.label.set_size(AXIS_LABEL_SIZE)
    ax.yaxis.label.set_size(AXIS_LABEL_SIZE)
    ax.tick_params(axis="both", labelsize=TICK_LABEL_SIZE)


def style_legend(legend: Any) -> None:
    """Enlarge the font of a legend and its title, if present."""
    if legend is None:
        return
    for text in legend.get_texts():
        text.set_fontsize(LEGEND_SIZE)
    title = legend.get_title()
    if title is not None:
        title.set_fontsize(LEGEND_TITLE_SIZE)


def autotuner_status(return_code: int, valid: bool, tsan: bool, application_failed: bool = False) -> str:
    """Status of an autotuner measurement (has separate validity/TSAN flags).

    * ``not_applied`` -- the requested patches did not apply, so nothing was measured
    * ``failed``      -- non-zero return code
    * ``invalid``     -- ran but failed the result or thread-sanitizer check
    * ``valid``       -- ran and passed both
    """
    if application_failed:
        return NOT_APPLIED_STATUS
    if return_code != 0:
        return "failed"
    if valid and tsan:
        return "valid"
    return "invalid"
