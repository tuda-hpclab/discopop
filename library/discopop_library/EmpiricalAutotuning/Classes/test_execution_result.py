# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the two durations a measured configuration carries."""

from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult


def test_the_wall_clock_duration_defaults_to_the_ranked_runtime() -> None:
    # exactly right when no execution time was read from the program's output
    result = ExecutionResult(2.5, 0, True, True)
    assert result.runtime == 2.5
    assert result.wall_clock_runtime == 2.5


def test_the_two_durations_are_kept_apart() -> None:
    """A reported time covers only part of the run, so the two must not be merged.

    The per-candidate timeout is derived from ``wall_clock_runtime``; deriving it
    from ``runtime`` scales it to the timed region alone and kills every candidate
    (observed on rodinia's hotspot: 2s of computation inside a 25s run).
    """
    result = ExecutionResult(2.044, 0, True, True, wall_clock_runtime=24.936)
    assert result.runtime == 2.044
    assert result.wall_clock_runtime == 24.936
