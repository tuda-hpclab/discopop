# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Report pages for the Amdahl ceilings of the measured parallelizations.

Page 1 lists, per configuration, the best valid measurement with the ceilings of its
suggestion set (for its own thread count and for unlimited threads) and how much of the
ceiling it reaches. Page 2 is the speedup-vs-ceiling chart. Both are estimates: the
parallel fraction comes from the hotspot-detection runtimes. Nothing is emitted when no
record has a ceiling (no hotspot data, or no suggestions applied).
"""

import json
import logging
import math
import os
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt

from discopop_library.Amdahl.regions import load_regions
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import report_charts
from discopop_library.ProjectManager.plots.data import ExecutionRecord, parse_execution_results

logger = logging.getLogger("ProjectManager")

TABLE_HEADERS = ["Config", "Suggestions", "Threads", "Speedup", "Ceiling (N)", "Ceiling (unlimited)", "Reached"]


def best_rows(records: List[ExecutionRecord]) -> List[List[str]]:
    """One table row per configuration: its best valid ``par`` record that has a ceiling."""
    usable, _missing = report_charts.amdahl_points(records, valid_only=True)
    best: Dict[str, ExecutionRecord] = {}
    for record in usable:
        current = best.get(record.config)
        if current is None or (record.speedup or 0.0) > (current.speedup or 0.0):
            best[record.config] = record
    rows: List[List[str]] = []
    for config in sorted(best):
        r = best[config]
        assert r.speedup is not None and r.amdahl_ceiling is not None
        limit = r.amdahl_limit
        rows.append(
            [
                config,
                ",".join(str(s) for s in r.applied_suggestions) or "(none)",
                str(r.thread_count),
                f"{r.speedup:.2f}x",
                f"{r.amdahl_ceiling:.2f}x",
                "unbounded" if limit is None or math.isinf(limit) else f"{limit:.2f}x",
                f"{100.0 * r.speedup / r.amdahl_ceiling:.0f}%",
            ]
        )
    return rows


def generate_amdahl_report(arguments: ProjectManagerArguments, timestamp: str) -> None:
    path = os.path.join(arguments.project_dir, "execution_results.json")
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        data = json.load(f)
    regions: Optional[dict] = None  # type: ignore[type-arg]
    try:
        regions = load_regions(os.path.dirname(os.path.normpath(arguments.project_dir)))
    except Exception as e:  # noqa: BLE001 -- the report must not fail on the optional ceilings
        logger.warning("Amdahl ceilings unavailable: " + str(e))
    if not regions:
        return
    records = [r for r in parse_execution_results(data, regions) if r.script == "execute.sh"]
    rows = best_rows(records)
    if not rows:
        return

    table_fig: Any = plt.figure(layout="constrained")  # type: ignore[call-arg]
    ax: Any = table_fig.add_subplot(111)
    ax.axis("off")
    ax.set_title("Amdahl ceilings of the best measurements (estimates from hotspot runtimes)", fontsize="small")
    table = ax.table(cellText=rows, colLabels=TABLE_HEADERS, loc="upper center")
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.auto_set_column_width(list(range(len(TABLE_HEADERS))))

    chart_fig: Any = plt.figure(layout="constrained")  # type: ignore[call-arg]
    report_charts.render_amdahl_scatter(chart_fig, records, x_mode="both")
