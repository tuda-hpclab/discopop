# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Dict, List

from discopop_library.ProjectManager.gui.plots.autotuning_chart import ProgressModel


def _greedy_events() -> List[Dict[str, Any]]:
    return [
        {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 8},
        {
            "event": "measurement",
            "index": 1,
            "suggestions": [],
            "runtime": 10.0,
            "return_code": 0,
            "valid": True,
            "tsan": True,
            "speedup": 1.0,
        },
        {
            "event": "measurement",
            "index": 2,
            "suggestions": [3],
            "runtime": 4.0,
            "return_code": 0,
            "valid": True,
            "tsan": True,
            "speedup": 2.5,
        },
        {
            "event": "measurement",
            "index": 3,
            "suggestions": [7],
            "runtime": 1.0,
            "return_code": 1,
            "valid": False,
            "tsan": False,
            "speedup": 10.0,
        },
        {
            "event": "measurement",
            "index": 4,
            "suggestions": [9],
            "runtime": 6.0,
            "return_code": 0,
            "valid": False,
            "tsan": True,
            "speedup": 1.6,
        },
        {"event": "result", "suggestions": [3], "speedup": 2.5, "efficiency": 0.31, "runtime": 4.0},
    ]


def test_ingest_greedy_counts_and_best() -> None:
    model = ProgressModel.from_events(_greedy_events())
    assert not model.is_evolutionary()
    assert len(model.measurements) == 4
    assert model.thread_count == 8
    assert model.best_speedup() == 2.5
    assert model.counts() == (2, 1, 1, 0)  # valid, invalid, failed, not applied
    assert model.result is not None and model.result["suggestions"] == [3]


def test_summary_tiles_reflect_best_valid() -> None:
    model = ProgressModel.from_events(_greedy_events())
    tiles = dict(model.summary_tiles())
    assert tiles["Best speedup"] == "2.50×"
    assert tiles["Best runtime"] == "4.00 s"
    assert tiles["Efficiency"] == f"{2.5 / 8:.2f}"
    assert tiles["Evaluated"] == "4"
    assert tiles["Valid"] == "2"
    assert tiles["Invalid / failed"] == "1 / 1"


def test_summary_tiles_empty_model() -> None:
    tiles = dict(ProgressModel().summary_tiles())
    assert tiles["Best speedup"] == "—"
    assert tiles["Evaluated"] == "0"


def test_ingest_evolutionary_generations() -> None:
    events: List[Dict[str, Any]] = [
        {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4},
        {"event": "generation", "generation": 0, "max_fitness": 1.0, "avg_fitness": 0.8, "threshold": 0.85},
        {
            "event": "measurement",
            "index": 1,
            "suggestions": [3],
            "runtime": 5.0,
            "return_code": 0,
            "valid": True,
            "tsan": True,
            "speedup": 2.0,
            "generation": 0,
        },
        {"event": "generation", "generation": 1, "max_fitness": 2.0, "avg_fitness": 1.5, "threshold": 1.7},
    ]
    model = ProgressModel.from_events(events)
    assert model.is_evolutionary()
    assert len(model.generations) == 2
    assert model.generations[1].max_fitness == 2.0
    assert model.measurements[0].generation == 0


def test_generation_ingests_measured_average() -> None:
    events: List[Dict[str, Any]] = [
        {
            "event": "generation",
            "generation": 1,
            "max_fitness": 2.0,
            "avg_fitness": 1.5,
            "threshold": 1.7,
            "generation_avg_fitness": 0.8,
        }
    ]
    model = ProgressModel.from_events(events)
    assert model.generations[0].generation_avg_fitness == 0.8


def test_generation_without_measured_average_stays_none() -> None:
    """Runs recorded before the measured average existed must still load."""
    events: List[Dict[str, Any]] = [
        {"event": "generation", "generation": 0, "max_fitness": 1.0, "avg_fitness": 0.8, "threshold": 0.85}
    ]
    model = ProgressModel.from_events(events)
    assert model.generations[0].generation_avg_fitness is None


def _not_applied_event(index: int, suggestion: int) -> Dict[str, Any]:
    """A measurement event for a configuration whose patches did not apply."""
    return {
        "event": "measurement",
        "index": index,
        "suggestions": [suggestion],
        "runtime": 0.0,
        "return_code": 0,
        "valid": False,
        "tsan": False,
        "speedup": None,
        "application_failed": True,
        "failed_suggestions": [suggestion],
    }


def test_unpatched_configuration_is_its_own_status_and_never_wins() -> None:
    events = _greedy_events() + [_not_applied_event(5, 27)]
    model = ProgressModel.from_events(events)
    skipped = model.measurements[-1]
    assert skipped.status == "not_applied" and skipped.application_failed
    assert skipped.failed_suggestions == [27]
    # counted separately from invalid (which is what return_code 0 + invalid would be)
    assert model.counts() == (2, 1, 1, 1)
    # and it can never be reported as the best configuration
    assert model.best_speedup() == 2.5


def test_not_applied_warning_names_the_affected_suggestions() -> None:
    model = ProgressModel.from_events(_greedy_events() + [_not_applied_event(5, 27)])
    warning = model.not_applied_warning()
    assert warning is not None and "27" in warning and "1 configuration" in warning
    assert len(model.not_applied_measurements()) == 1


def test_no_warning_when_every_configuration_was_patched() -> None:
    assert ProgressModel.from_events(_greedy_events()).not_applied_warning() is None


def test_not_applied_tile_is_shown() -> None:
    tiles = dict(ProgressModel.from_events(_greedy_events() + [_not_applied_event(5, 27)]).summary_tiles())
    assert tiles["Not applied"] == "1"
    # a skipped configuration is not folded into the invalid/failed counts
    assert tiles["Invalid / failed"] == "1 / 1"


def test_failed_suggestions_alone_marks_a_measurement_as_not_applied() -> None:
    """A run whose payload predates the explicit flag but lists failed suggestions."""
    event = _not_applied_event(5, 27)
    del event["application_failed"]
    model = ProgressModel.from_events([event])
    assert model.measurements[0].status == "not_applied"
