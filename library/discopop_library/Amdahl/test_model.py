# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import math
from typing import Optional, cast

from discopop_library.Amdahl.model import (
    SuggestionRegion,
    amdahl_ceiling,
    amdahl_limit,
    ceilings,
    finite_or_none,
    parallel_fraction,
)


def _r(i: int, f: int, s: int, e: int, share: Optional[float]) -> SuggestionRegion:
    return SuggestionRegion(i, f, s, e, share)


def test_ceiling_and_limit() -> None:
    assert amdahl_ceiling(0.5, 2) == 1 / (0.5 + 0.25)
    assert amdahl_ceiling(0.0, 16) == 1.0
    assert amdahl_ceiling(None, 4) is None
    assert amdahl_ceiling(0.9, 0) is None
    assert amdahl_limit(0.75) == 4.0
    assert amdahl_limit(1.0) == math.inf
    assert amdahl_limit(None) is None


def test_ceiling_never_exceeds_thread_count_or_limit() -> None:
    for p in (0.1, 0.5, 0.99):
        assert cast(float, amdahl_ceiling(p, 8)) <= 8
        assert cast(float, amdahl_ceiling(p, 8)) < cast(float, amdahl_limit(p))


def test_nested_suggestions_counted_once() -> None:
    regions = {1: _r(1, 1, 10, 50, 0.6), 2: _r(2, 1, 20, 30, 0.5), 3: _r(3, 1, 60, 70, 0.1)}
    assert math.isclose(cast(float, parallel_fraction([1, 2, 3], regions)), 0.7)
    assert math.isclose(cast(float, parallel_fraction([2, 3], regions)), 0.6)


def test_same_lines_in_other_file_not_nested() -> None:
    regions = {1: _r(1, 1, 10, 50, 0.3), 2: _r(2, 2, 20, 30, 0.2)}
    assert math.isclose(cast(float, parallel_fraction([1, 2], regions)), 0.5)


def test_identical_ranges_counted_once() -> None:
    regions = {1: _r(1, 1, 10, 50, 0.3), 2: _r(2, 1, 10, 50, 0.3)}
    assert math.isclose(cast(float, parallel_fraction([1, 2], regions)), 0.3)


def test_unknown_inputs_give_none() -> None:
    regions = {1: _r(1, 1, 10, 50, None)}
    assert parallel_fraction([1], regions) is None
    assert parallel_fraction([99], regions) is None
    assert parallel_fraction([], regions) == 0.0
    assert ceilings([99], 4, regions) == (None, None, None)


def test_fraction_clamped_to_one() -> None:
    regions = {1: _r(1, 1, 1, 5, 0.8), 2: _r(2, 1, 6, 9, 0.8)}
    assert parallel_fraction([1, 2], regions) == 1.0


def test_finite_or_none() -> None:
    assert finite_or_none(math.inf) is None
    assert finite_or_none(None) is None
    assert finite_or_none(1.23456) == 1.2346
