# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.Amdahl.model import amdahl_ceiling, amdahl_limit
from discopop_library.ProjectManager.plots.data import ExecutionRecord
from discopop_library.ProjectManager.reports.amdahl import best_rows


def _rec(config: str, speedup: float, threads: int, p: float, mode: str = "par") -> ExecutionRecord:
    return ExecutionRecord(
        config=config,
        script="execute.sh",
        mode=mode,
        label="",
        thread_count=threads,
        applied_suggestions=[5],
        time=1.0,
        code=0,
        timeout=False,
        valid=True,
        speedup=speedup,
        efficiency=speedup / threads,
        parallel_fraction=p,
        amdahl_ceiling=amdahl_ceiling(p, threads),
        amdahl_limit=amdahl_limit(p),
    )


def test_best_rows_picks_best_par_record_per_config() -> None:
    rows = best_rows(
        [_rec("a", 1.5, 4, 0.9), _rec("a", 3.0, 4, 0.9), _rec("b", 2.0, 2, 1.0), _rec("c", 1.0, 1, 0.0, "seq")]
    )
    assert [r[0] for r in rows] == ["a", "b"]
    assert rows[0][3] == "3.00x" and rows[0][4] == "3.08x" and rows[0][5] == "10.00x" and rows[0][6] == "97%"
    assert rows[1][5] == "unbounded"
