# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.ProjectManager.gui.plots.data import ExecutionRecord
from discopop_library.ProjectManager.gui.plots.report_charts import (
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
