# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for repeating a measurement and reporting the median of it.

Like the measurement tests next door these run real scripts through the real
function: what is being checked is how many times a script is actually started
and which of those runs ends up in the results file, neither of which a mocked
subprocess would show.

The scripts count their own invocations in a file, so one script body can behave
differently on each repetition -- which is the whole point of the feature.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.execution import record_skipped_execution
from discopop_library.ProjectManager.configurations.execution_time import (
    TIME_SOURCE_CONSOLE,
    TIME_SOURCE_FALLBACK,
    TIME_SOURCE_WALL_CLOCK,
)
from discopop_library.ProjectManager.configurations.repetitions import (
    TIME_AGGREGATE_FAILED_RUN,
    TIME_AGGREGATE_MEDIAN,
    TIME_AGGREGATE_NOT_MEASURED,
)
from discopop_library.ProjectManager.configurations.test_execution_measurement import (
    TOTAL_TIME_REGEX,
    _project,
    _recorded,
)

# Prelude counting this script's invocations in $DP_PROJECT_ROOT_DIR/invocations
# and leaving the number in $N, so a script body can answer differently on each
# repetition.
COUNTER = """
COUNT_FILE="$DP_PROJECT_ROOT_DIR/invocations"
N=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
N=$((N + 1))
echo "$N" > "$COUNT_FILE"
"""


def _invocations(arguments: ProjectManagerArguments) -> int:
    """How many times the script was actually started."""
    with open(os.path.join(arguments.project_root, "invocations"), "r") as f:
        return int(f.read().strip())


def _run(
    tmp_path: Path, script_body: str, repetitions: int, regex: Optional[str] = TOTAL_TIME_REGEX
) -> Tuple[Tuple[int, float, str, str], Dict[str, Any], int]:
    arguments, config_path, settings_path, script_path = _project(tmp_path, script_body)
    result = execute_configuration(
        arguments,
        arguments.project_root,
        config_path,
        settings_path,
        script_path,
        1,
        None,
        execution_time_regex=regex,
        repetitions=repetitions,
    )
    assert result is not None
    return result, _recorded(arguments), _invocations(arguments)


# The times the script below reports, in order. The median (4.10) is neither the
# first nor the last value, and one repetition is a far slower outlier -- exactly
# the noise a single measurement would have reported as the configuration's
# runtime.
REPORTED_TIMES = [4.10, 4.05, 6.80, 4.08, 4.12]
VARYING_TIMES = COUNTER + "".join(
    "if [ $N -eq " + str(i + 1) + ' ]; then echo "run $N Total time: ' + str(t) + '"; fi\n'
    for i, t in enumerate(REPORTED_TIMES)
)


def test_a_single_repetition_behaves_as_before(tmp_path: Path) -> None:
    """The default must record exactly what it recorded before this option existed."""
    result, entry, invocations = _run(tmp_path, COUNTER + "echo 'Total time: 1.5'\n", 1)
    assert invocations == 1
    assert result[1] == 1.5
    assert entry["time"] == 1.5
    assert entry["repetitions"] == 1
    assert entry["repetition_times"] == [1.5]


def test_the_script_is_run_once_per_repetition(tmp_path: Path) -> None:
    _, entry, invocations = _run(tmp_path, VARYING_TIMES, 5)
    assert invocations == 5
    assert entry["repetitions"] == 5
    assert entry["repetition_times"] == REPORTED_TIMES


def test_the_median_of_the_repetitions_is_reported(tmp_path: Path) -> None:
    result, entry, _ = _run(tmp_path, VARYING_TIMES, 5)
    assert entry["time"] == 4.10
    assert entry["time_aggregate"] == TIME_AGGREGATE_MEDIAN
    # the returned time is the recorded one: every caller reading the return
    # value sees the same measurement the results file holds
    assert result[1] == entry["time"]
    # and the outlier is not what the configuration is judged by
    assert entry["time"] < max(REPORTED_TIMES)


def test_the_recorded_output_belongs_to_the_reported_run(tmp_path: Path) -> None:
    """Not a median per field: one run is picked and it supplies all of them.

    The stored output has to be the output the reported time was read from,
    otherwise a reader re-checking the measurement against the console log would
    find a different number there.
    """
    result, entry, _ = _run(tmp_path, VARYING_TIMES, 5)
    median_index = REPORTED_TIMES.index(4.10)
    assert entry["stdout"].startswith("run " + str(median_index + 1) + " ")
    assert result[2] == entry["stdout"]


def test_the_wall_clock_time_belongs_to_the_reported_run(tmp_path: Path) -> None:
    """The pair has to describe one run: the auto-tuner's timeout is derived from it."""
    _, entry, _ = _run(tmp_path, VARYING_TIMES, 5)
    wall_clock_times = cast(List[float], entry["repetition_wall_clock_times"])
    assert len(wall_clock_times) == 5
    median_index = REPORTED_TIMES.index(entry["time"])
    assert entry["wall_clock_time"] == wall_clock_times[median_index]
    # the timeout must bound the whole process, so the recorded wall clock time
    # is one repetition's duration and not the sum of all of them
    assert entry["wall_clock_time"] < sum(wall_clock_times)


def test_the_wall_clock_time_is_repeated_without_a_pattern_too(tmp_path: Path) -> None:
    _, entry, invocations = _run(tmp_path, COUNTER + "echo 'no timing here'\n", 3, regex=None)
    assert invocations == 3
    assert entry["repetition_times"] == entry["repetition_wall_clock_times"]
    assert entry["time"] == entry["wall_clock_time"]
    assert entry["time"] in entry["repetition_times"]


def test_a_failing_repetition_stops_the_loop(tmp_path: Path) -> None:
    """A broken configuration is not worth measuring four more times."""
    script = COUNTER + "echo 'Total time: 2.0'\nif [ $N -eq 3 ]; then exit 1; fi\n"
    result, entry, invocations = _run(tmp_path, script, 5)
    assert invocations == 3
    assert entry["repetitions"] == 3
    assert result[0] == 1


def test_a_failing_repetition_is_what_gets_recorded(tmp_path: Path) -> None:
    """A median among the runs that did succeed would report the run as working."""
    script = COUNTER + 'echo "run $N Total time: 2.0"\nif [ $N -eq 3 ]; then exit 1; fi\n'
    _, entry, _ = _run(tmp_path, script, 5)
    assert entry["code"] == 1
    assert entry["stdout"].startswith("run 3 ")


def test_an_immediate_failure_is_not_retried(tmp_path: Path) -> None:
    result, entry, invocations = _run(tmp_path, COUNTER + "exit 3\n", 4)
    assert invocations == 1
    assert entry["repetitions"] == 1
    assert result[0] == 3


def test_an_unusable_repetition_count_is_rejected(tmp_path: Path) -> None:
    """Refused before the script runs, rather than silently treated as one run."""
    arguments, config_path, settings_path, script_path = _project(tmp_path, "echo 'Total time: 1.0'\n")
    with pytest.raises(ValueError):
        execute_configuration(
            arguments,
            arguments.project_root,
            config_path,
            settings_path,
            script_path,
            1,
            None,
            repetitions=0,
        )


def test_a_rejected_count_leaves_the_working_directory_alone(tmp_path: Path) -> None:
    """The refusal must come before the process is moved into the project copy.

    ``execute_configuration`` chdirs into the copy and back out again at the end.
    Raising in between would strand the caller in a directory that its own cleanup
    is about to delete, and every later relative path would resolve against it.
    """
    arguments, config_path, settings_path, script_path = _project(tmp_path, "echo 'Total time: 1.0'\n")
    before = os.getcwd()
    with pytest.raises(ValueError):
        execute_configuration(
            arguments,
            arguments.project_root,
            config_path,
            settings_path,
            script_path,
            1,
            None,
            repetitions=0,
        )
    assert os.getcwd() == before


def test_an_even_repetition_count_reports_the_lower_middle_run(tmp_path: Path) -> None:
    """With no single middle value, the reported run is still one that happened.

    It has to be: the recorded output, return code and wall clock time all come
    from it, and the average of two runs has none of those.
    """
    times = [4.0, 1.0, 3.0, 2.0]
    script = COUNTER + "".join(
        "if [ $N -eq " + str(i + 1) + ' ]; then echo "run $N Total time: ' + str(t) + '"; fi\n'
        for i, t in enumerate(times)
    )
    result, entry, invocations = _run(tmp_path, script, 4)
    assert invocations == 4
    # lower of the two middle values (2.0 and 3.0)
    assert entry["time"] == 2.0
    assert result[1] == 2.0
    assert entry["stdout"].startswith("run 4 ")
    assert entry["wall_clock_time"] == entry["repetition_wall_clock_times"][3]


def test_a_failed_run_is_not_labelled_as_a_median(tmp_path: Path) -> None:
    """``time`` is then the failing run's own, so calling it an aggregate would lie."""
    script = COUNTER + "echo 'Total time: 2.0'\nif [ $N -eq 3 ]; then exit 1; fi\n"
    _, entry, _ = _run(tmp_path, script, 5)
    assert entry["time_aggregate"] == TIME_AGGREGATE_FAILED_RUN


def test_a_skipped_run_reports_no_measurement(tmp_path: Path) -> None:
    """A run that never happened has no times and must not claim an aggregate."""
    from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult

    arguments, config_path, settings_path, script_path = _project(tmp_path, "echo 'Total time: 1.0'\n")
    entry = record_skipped_execution(
        arguments,
        arguments.project_root,
        config_path,
        settings_path,
        script_path,
        1,
        PatchApplicationResult(requested=["1"], applied=[], failed=["1"]),
    )
    assert entry["repetitions"] == 0
    assert entry["repetition_times"] == []
    assert entry["repetition_wall_clock_times"] == []
    assert entry["time_aggregate"] == TIME_AGGREGATE_NOT_MEASURED


def test_an_aborting_caller_stops_the_loop(tmp_path: Path) -> None:
    """Stopping a repeated run must not wait for the repetitions still to come."""
    arguments, config_path, settings_path, script_path = _project(tmp_path, COUNTER + "echo 'Total time: 1.0'\n")
    result = execute_configuration(
        arguments,
        arguments.project_root,
        config_path,
        settings_path,
        script_path,
        1,
        None,
        repetitions=5,
        should_abort=lambda: True,
    )
    assert result is not None
    assert _invocations(arguments) == 1
    assert _recorded(arguments)["repetitions"] == 1


# The middle run prints no timing at all, so it is measured by the wall clock --
# a far larger number, since it covers the whole script rather than the region the
# pattern names.
INTERMITTENT_REPORTING = (
    COUNTER
    + 'if [ $N -eq 2 ]; then echo "run $N no timing here"; else echo "run $N Total time: 0.05"; fi\n'
    # long enough that the fallback's wall clock time is unmistakably the larger
    # quantity, which is the bias this test is about
    + "sleep 0.3\n"
)


def test_a_repetition_that_reported_nothing_is_kept_out_of_the_median(tmp_path: Path) -> None:
    """Its wall clock time measures a different thing and would bias the median up.

    A program that only intermittently prints its timing is exactly the flaky case
    repetitions exist for; letting the fallbacks in would make the number worse the
    more often it happens.
    """
    result, entry, invocations = _run(tmp_path, INTERMITTENT_REPORTING, 3)
    assert invocations == 3
    assert entry["time"] == 0.05
    assert result[1] == 0.05
    assert entry["time_source"] == TIME_SOURCE_CONSOLE
    # every repetition is still recorded, with what its time actually was
    assert len(entry["repetition_times"]) == 3
    assert entry["repetition_time_sources"] == [
        TIME_SOURCE_CONSOLE,
        TIME_SOURCE_FALLBACK,
        TIME_SOURCE_CONSOLE,
    ]
    # the excluded run's wall clock time is the larger quantity that was kept out
    assert entry["repetition_times"][1] > 0.05


def test_the_wall_clock_times_are_used_when_nothing_reported_one(tmp_path: Path) -> None:
    """With no usable report, the wall clock times are all there is."""
    _, entry, _ = _run(tmp_path, COUNTER + "echo 'no timing here'\n", 3)
    assert entry["time_source"] == TIME_SOURCE_FALLBACK
    assert entry["time"] in entry["repetition_times"]
    assert entry["time_aggregate"] == TIME_AGGREGATE_MEDIAN
    assert entry["repetition_time_sources"] == [TIME_SOURCE_FALLBACK] * 3


def test_without_a_pattern_every_repetition_counts(tmp_path: Path) -> None:
    """No pattern means no fallbacks: nothing is excluded from the median."""
    _, entry, _ = _run(tmp_path, COUNTER + "echo 'quiet'\n", 3, regex=None)
    assert entry["repetition_time_sources"] == [TIME_SOURCE_WALL_CLOCK] * 3
    assert entry["time"] in entry["repetition_times"]
