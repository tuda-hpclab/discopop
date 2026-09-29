# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for picking the run that counts among repeated measurements."""

from typing import List

import pytest

from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_MEASURED_REPETITIONS,
    DEFAULT_TUNING_REPETITIONS,
    SINGLE_MEASUREMENT,
    MEASURED_MODES,
    repetitions_for_mode,
    select_representative,
    validate_repetitions,
)


def test_a_single_repetition_is_its_own_representative() -> None:
    assert select_representative([4.2]) == 0


def test_the_median_run_is_picked() -> None:
    times = [4.10, 4.05, 6.80, 4.08, 4.12]
    index = select_representative(times)
    assert times[index] == 4.10
    # what the repetitions are for: the outlier must not decide the measurement
    assert times[index] < sum(times) / len(times)


def test_the_lower_of_two_middle_values_is_picked() -> None:
    """An even count has no single middle run, and an average has no output.

    The representative carries the recorded return code, console output and wall
    clock time, so it has to be a run that actually happened.
    """
    times = [1.0, 2.0, 3.0, 4.0]
    assert times[select_representative(times)] == 2.0


def test_the_representative_is_an_index_into_the_original_order() -> None:
    times = [9.0, 1.0, 5.0]
    assert select_representative(times) == 2


def test_equal_times_resolve_deterministically() -> None:
    """Ties are broken by position, and always the same way.

    The sort is stable, so equal times keep their input order and the middle
    *position* is what decides -- not the earliest run. Asserted rather than left
    open, so that a run whose repetitions all measured the same still has a
    predictable recorded output.
    """
    assert select_representative([2.5, 2.5, 2.5]) == 1
    assert select_representative([2.5, 2.5]) == 0
    # a tie among the middle values does not disturb the surrounding order
    assert select_representative([9.0, 1.0, 1.0]) == 2


def test_no_repetitions_cannot_be_represented() -> None:
    with pytest.raises(ValueError):
        select_representative([])


def test_at_least_one_execution_is_required() -> None:
    assert validate_repetitions(1) is None
    assert validate_repetitions(5) is None
    assert validate_repetitions(0) is not None
    assert validate_repetitions(-1) is not None


def test_a_non_integer_count_is_rejected() -> None:
    # A bool is an int in Python, but "True repetitions" is a mistake, not a count.
    assert validate_repetitions(True) is not None  # type: ignore[arg-type]
    assert validate_repetitions("3") is not None  # type: ignore[arg-type]
    assert validate_repetitions(2.5) is not None  # type: ignore[arg-type]


def test_only_the_measuring_modes_are_repeated() -> None:
    """The decision the command line and the graphical interface share.

    dp and hd run instrumented binaries whose output feeds the Explorer and the
    hotspot analysis; their duration is a byproduct, so a median of it would cost
    profiling runs and buy nothing.
    """
    for mode in ("seq", "par"):
        assert repetitions_for_mode(mode, 5) == 5
    for mode in ("dp", "hd", "", "unknown"):
        assert repetitions_for_mode(mode, 5) == SINGLE_MEASUREMENT


def test_the_measuring_modes_are_the_documented_ones() -> None:
    assert MEASURED_MODES == ("seq", "par")


def test_the_two_defaults_differ_on_purpose() -> None:
    """Measured runs are repeated by default; the search is not.

    The search performs one program execution per candidate, so the same count
    there multiplies the runtime of a whole search rather than of one reported
    number. Pinned so that raising the tuning default is a deliberate act.
    """
    assert DEFAULT_MEASURED_REPETITIONS == 3
    assert DEFAULT_TUNING_REPETITIONS == SINGLE_MEASUREMENT == 1
    # a median can only ignore an outlier from three runs on
    assert DEFAULT_MEASURED_REPETITIONS >= 3
