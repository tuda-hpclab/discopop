# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Dict

from discopop_library.ProjectManager.gui.plots.data import (
    best_so_far,
    mode_of_setting,
    parse_execution_results,
    parse_progress_jsonl,
    parse_progress_line,
    split_progress_events,
    pareto_frontier,
)


def _sample_results() -> Dict[str, Any]:
    return {
        "tiny": {
            "execute.sh": {
                "seq_settings.json": [
                    {"applied_suggestions": [], "code": 0, "time": 10.0, "thread_count": 1, "label": ""},
                ],
                "par_settings.json": [
                    {"applied_suggestions": [3, 7], "code": 0, "time": 4.0, "thread_count": 8, "label": "auto"},
                    {"applied_suggestions": [3], "code": 1, "time": 1.0, "thread_count": 8, "label": ""},
                    {
                        "applied_suggestions": [9],
                        "code": 0,
                        "time": 5.0,
                        "thread_count": 8,
                        "label": "",
                        "timeout_expired": True,
                    },
                ],
            }
        }
    }


def test_mode_of_setting() -> None:
    assert mode_of_setting("par_settings.json") == "par"
    assert mode_of_setting("seq_settings.json") == "seq"
    assert mode_of_setting("custom") == "custom"


def test_parse_execution_results_speedup_and_validity() -> None:
    records = parse_execution_results(_sample_results())
    by_key = {(r.mode, tuple(r.applied_suggestions), r.code): r for r in records}

    # sequential baseline: speedup 1.0, efficiency 1.0
    seq = by_key[("seq", (), 0)]
    assert seq.speedup == 1.0 and seq.efficiency == 1.0 and seq.valid

    # valid parallel run: 10.0 / 4.0 = 2.5, efficiency 2.5 / 8
    par = by_key[("par", (3, 7), 0)]
    assert par.speedup == 2.5
    assert par.efficiency is not None and abs(par.efficiency - 2.5 / 8) < 1e-9
    assert par.valid and par.label == "auto"

    # failed run (code != 0) is invalid but speedup still computed from its time
    failed = by_key[("par", (3,), 1)]
    assert not failed.valid and failed.speedup == 10.0

    # timed-out run is invalid
    timed_out = by_key[("par", (9,), 0)]
    assert timed_out.timeout and not timed_out.valid


def test_parse_execution_results_autotuner_baseline_from_unsuggested_run() -> None:
    # Autotuner runs write only par combinations (no seq baseline); the run with
    # no suggestions applied is the reference every combination is measured against.
    data = {
        "c": {
            "execute.sh": {
                "par_settings.json": [
                    {"applied_suggestions": [], "code": 0, "time": 4.0, "thread_count": 4},  # baseline
                    {"applied_suggestions": [1], "code": 0, "time": 2.0, "thread_count": 4},  # 2x faster
                    {"applied_suggestions": [2], "code": 0, "time": 8.0, "thread_count": 4},  # 2x slower
                ]
            }
        }
    }
    by_sugg = {tuple(r.applied_suggestions): r for r in parse_execution_results(data)}
    assert by_sugg[()].speedup == 1.0  # baseline against itself
    assert by_sugg[(1,)].speedup == 2.0
    assert by_sugg[(1,)].efficiency is not None and abs(by_sugg[(1,)].efficiency - 2.0 / 4) < 1e-9
    assert by_sugg[(2,)].speedup == 0.5


def test_parse_execution_results_no_baseline_gives_none_speedup() -> None:
    # Neither a seq baseline nor an unsuggested run -> no reference, speedup None.
    data = {
        "c": {
            "execute.sh": {
                "par_settings.json": [{"applied_suggestions": [5], "code": 0, "time": 2.0, "thread_count": 4}]
            }
        }
    }
    (record,) = parse_execution_results(data)
    assert record.speedup is None and record.efficiency is None


def test_pareto_frontier_maximizes_both() -> None:
    # (efficiency, speedup); dominated points must be excluded
    points = [
        (0.5, 4.0),  # 0 on frontier
        (0.3, 5.0),  # 1 on frontier
        (0.3, 3.0),  # 2 dominated by 0 and 1
        (0.2, 2.0),  # 3 dominated
    ]
    assert pareto_frontier(points) == [1, 0]  # sorted by ascending x


def test_pareto_frontier_empty() -> None:
    assert pareto_frontier([]) == []


def test_best_so_far_running_max_over_valid() -> None:
    measurements = [
        (1, 1.0, True),
        (2, 0.75, True),  # worse, best stays 1.0
        (3, None, False),  # failed/invalid ignored
        (4, 2.4, True),  # new best
        (5, 2.1, True),
    ]
    assert best_so_far(measurements) == [(1, 1.0), (2, 1.0), (3, 1.0), (4, 2.4), (5, 2.4)]


def test_best_so_far_starts_at_first_valid() -> None:
    measurements = [(1, None, False), (2, 1.5, True)]
    assert best_so_far(measurements) == [(2, 1.5)]


def test_parse_progress_line() -> None:
    good = '@@AT_PROGRESS {"event": "measurement", "index": 2, "speedup": 2.0}'
    obj = parse_progress_line(good)
    assert obj is not None and obj["event"] == "measurement" and obj["index"] == 2

    assert parse_progress_line("INFO: some other stdout line") is None
    assert parse_progress_line("@@AT_PROGRESS {not valid json}") is None
    assert parse_progress_line("@@AT_PROGRESS [1, 2, 3]") is None  # not a dict


def test_parse_progress_line_behind_unrelated_output() -> None:
    """A bar redraw ends without a newline, so an event can share its line."""
    line = '42%|####      | 5/12 [00:11<00:15]@@AT_PROGRESS {"event": "measurement", "index": 5}'
    obj = parse_progress_line(line)
    assert obj is not None and obj["index"] == 5


def test_split_progress_events_separates_events_from_console_text() -> None:
    line = '  7%|#         | 1/14@@AT_PROGRESS {"event": "measurement", "index": 1}\n'
    events, residual = split_progress_events(line)
    assert [e["index"] for e in events] == [1]
    assert residual.strip() == "7%|#         | 1/14"


def test_split_progress_events_multiple_events_in_one_line() -> None:
    line = '@@AT_PROGRESS {"event": "baseline"}@@AT_PROGRESS {"event": "measurement", "index": 1}'
    events, residual = split_progress_events(line)
    assert [e["event"] for e in events] == ["baseline", "measurement"]
    assert residual == ""


def test_split_progress_events_keeps_non_events_as_output() -> None:
    assert split_progress_events("INFO: plain line") == ([], "INFO: plain line")
    events, residual = split_progress_events("@@AT_PROGRESS {not valid json}")
    assert events == [] and residual == "@@AT_PROGRESS {not valid json}"
    events, residual = split_progress_events("@@AT_PROGRESS [1, 2, 3]")  # not a dict
    assert events == [] and residual == "@@AT_PROGRESS [1, 2, 3]"


def test_parse_progress_jsonl() -> None:
    text = '{"event": "baseline"}\n\n{"event": "measurement"}\nbroken line\n'
    events = parse_progress_jsonl(text)
    assert [e["event"] for e in events] == ["baseline", "measurement"]


def _not_applied_entry(requested: int, thread_count: int = 4) -> Dict[str, Any]:
    """A placeholder entry as written when the suggestions could not be applied."""
    return {
        "applied_suggestions": [],
        "requested_suggestions": [requested],
        "failed_suggestions": [requested],
        "suggestion_application_failed": True,
        "executed": False,
        "code": -1,
        "time": 0.0,
        "thread_count": thread_count,
        "label": "",
    }


def test_unapplied_run_is_flagged_and_carries_no_metrics() -> None:
    data = {
        "c": {
            "execute.sh": {
                "seq_settings.json": [
                    {"applied_suggestions": [], "code": 0, "time": 10.0, "thread_count": 1},
                ],
                "par_settings.json": [_not_applied_entry(27)],
            }
        }
    }
    records = parse_execution_results(data)
    skipped = [r for r in records if r.mode == "par"][0]
    assert skipped.application_failed
    assert skipped.failed_suggestions == [27] and skipped.requested_suggestions == [27]
    assert not skipped.valid and not skipped.has_measurement
    # it was never run, so there is nothing to report as a speedup
    assert skipped.speedup is None and skipped.efficiency is None
    assert skipped.status == "not_applied"


def test_unapplied_run_does_not_become_the_autotuner_baseline() -> None:
    """Its applied set is empty too, which used to make it a candidate reference."""
    data = {
        "c": {
            "execute.sh": {
                "par_settings.json": [
                    {"applied_suggestions": [], "code": 0, "time": 4.0, "thread_count": 4},  # real baseline
                    _not_applied_entry(27),  # zero runtime, must be ignored
                    {"applied_suggestions": [1], "code": 0, "time": 2.0, "thread_count": 4},
                ]
            }
        }
    }
    by_key = {(tuple(r.applied_suggestions), r.application_failed): r for r in parse_execution_results(data)}
    assert by_key[((), False)].speedup == 1.0
    assert by_key[((1,), False)].speedup == 2.0  # 4.0 / 2.0, not 0.0 / 2.0


def test_unapplied_seq_run_does_not_become_the_seq_baseline() -> None:
    data = {
        "c": {
            "execute.sh": {
                "seq_settings.json": [_not_applied_entry(1, thread_count=1)],
                "par_settings.json": [
                    {"applied_suggestions": [1], "code": 0, "time": 2.0, "thread_count": 4},
                ],
            }
        }
    }
    par = [r for r in parse_execution_results(data) if r.mode == "par"][0]
    # no usable baseline exists, so no speedup is invented from the placeholder
    assert par.speedup is None


def test_ordinary_entries_default_to_applied() -> None:
    """Results written before the new fields existed must keep reading as measurements."""
    records = parse_execution_results(_sample_results())
    assert all(not r.application_failed for r in records)
    assert all(r.has_measurement for r in records)
