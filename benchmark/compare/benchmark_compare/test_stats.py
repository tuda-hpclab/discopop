# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import math

import pytest

from benchmark_compare.stats import (
    IMPROVEMENT,
    REGRESSION,
    UNCHANGED,
    UNKNOWN,
    classify,
    geometric_mean,
    mann_whitney_p,
    median,
    relative_change,
)


def test_identical_samples_are_not_different() -> None:
    assert mann_whitney_p([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 1.0


def test_exact_p_value_of_separated_samples() -> None:
    # all 20 ways to pick 3 of 6 ranks; only the two most extreme are as far apart as the observed split
    assert mann_whitney_p([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(2 / 20)
    assert mann_whitney_p([4.0, 5.0, 6.0], [1.0, 2.0, 3.0]) == pytest.approx(2 / 20)
    # 6 against 6: the smallest p-value two interleaved rounds of three repetitions can reach
    assert mann_whitney_p([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [7.0, 8.0, 9.0, 10.0, 11.0, 12.0]) == pytest.approx(2 / 924)


def test_overlapping_samples_are_not_significant() -> None:
    assert mann_whitney_p([1.0, 3.0, 5.0, 7.0], [2.0, 4.0, 6.0, 8.0]) > 0.5


def test_ties_are_handled() -> None:
    p = mann_whitney_p([1.0, 1.0, 2.0], [1.0, 2.0, 2.0])
    assert 0.0 < p <= 1.0


def test_large_samples_use_the_normal_approximation() -> None:
    first = [float(value) for value in range(20)]
    second = [float(value) for value in range(100, 120)]
    assert mann_whitney_p(first, second) < 1e-6
    assert mann_whitney_p(first, first) == pytest.approx(1.0)


def test_empty_samples_give_nan() -> None:
    assert math.isnan(mann_whitney_p([], [1.0]))


def test_classification() -> None:
    assert classify(0.2, 0.01) == REGRESSION
    assert classify(-0.2, 0.01) == IMPROVEMENT
    # large, but not significant
    assert classify(0.2, 0.3) == UNCHANGED
    # significant, but below the threshold
    assert classify(0.05, 0.001) == UNCHANGED
    # measured once: the threshold alone decides
    assert classify(0.2, None) == REGRESSION
    assert classify(math.nan, 0.01) == UNKNOWN
    assert classify(0.06, 0.01, threshold=0.05) == REGRESSION


def test_helpers() -> None:
    assert median([3.0, 1.0, 2.0, math.nan]) == 2.0
    assert geometric_mean([1.0, 4.0]) == pytest.approx(2.0)
    assert math.isnan(geometric_mean([]))
    assert relative_change(10.0, 12.0) == pytest.approx(0.2)
    assert math.isnan(relative_change(0.0, 1.0))
