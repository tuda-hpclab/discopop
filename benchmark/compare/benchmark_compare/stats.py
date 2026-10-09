# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The statistics behind the comparison: medians, changes, the Mann-Whitney U test and the verdict."""

from __future__ import annotations

import itertools
import math
import statistics
from typing import List, Optional, Sequence

# a change is flagged when it is larger than this (relative to the version compared with) ...
DEFAULT_THRESHOLD = 0.10
# ... and, where repeated measurements exist, significant at this level
DEFAULT_ALPHA = 0.05

# above this many ways to split the samples, the exact test gives way to the normal approximation
_EXACT_TEST_LIMIT = 200_000

REGRESSION = "regression"
IMPROVEMENT = "improvement"
UNCHANGED = "unchanged"
UNKNOWN = "unknown"


def median(values: Sequence[float]) -> float:
    usable = [value for value in values if math.isfinite(value)]
    return statistics.median(usable) if usable else math.nan


def geometric_mean(values: Sequence[float]) -> float:
    usable = [value for value in values if math.isfinite(value) and value > 0.0]
    if not usable:
        return math.nan
    return math.exp(sum(math.log(value) for value in usable) / len(usable))


def relative_change(base: float, head: float) -> float:
    """``head`` relative to ``base``: 0.1 is 10% more, -0.1 is 10% less."""
    if not (math.isfinite(base) and math.isfinite(head)) or base <= 0.0:
        return math.nan
    return head / base - 1.0


def _ranks(values: Sequence[float]) -> List[float]:
    """The rank of every value (1-based), ties sharing the mean of their ranks."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in order[position : end + 1]:
            ranks[index] = shared
        position = end + 1
    return ranks


def mann_whitney_p(first: Sequence[float], second: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test: how likely the two samples are this far apart by chance.

    Small samples (the usual case: a handful of repetitions per version) are tested exactly, by enumerating
    every way of splitting the pooled ranks; larger ones use the normal approximation with tie correction.
    Returns NaN when a sample is empty.
    """
    first = [value for value in first if math.isfinite(value)]
    second = [value for value in second if math.isfinite(value)]
    n1, n2 = len(first), len(second)
    if n1 == 0 or n2 == 0:
        return math.nan
    ranks = _ranks([*first, *second])
    if len(set(ranks)) == 1:
        return 1.0
    expected = n1 * (n1 + n2 + 1) / 2.0
    observed = abs(sum(ranks[:n1]) - expected)

    if math.comb(n1 + n2, n1) <= _EXACT_TEST_LIMIT:
        # a small tolerance, so that rank sums equal to the observed one are not lost to rounding
        extreme = sum(
            1 for chosen in itertools.combinations(ranks, n1) if abs(sum(chosen) - expected) >= observed - 1e-9
        )
        return extreme / math.comb(n1 + n2, n1)

    total = n1 + n2
    tie_term = sum(count**3 - count for count in _tie_counts(ranks))
    variance = n1 * n2 / 12.0 * ((total + 1) - tie_term / (total * (total - 1)))
    if variance <= 0.0:
        return 1.0
    z = max(observed - 0.5, 0.0) / math.sqrt(variance)
    return math.erfc(z / math.sqrt(2.0))


def _tie_counts(ranks: Sequence[float]) -> List[int]:
    counts: dict[float, int] = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    return [count for count in counts.values() if count > 1]


def classify(
    change: float,
    p_value: Optional[float],
    threshold: float = DEFAULT_THRESHOLD,
    alpha: float = DEFAULT_ALPHA,
) -> str:
    """The verdict on a change: larger than the threshold and, if measured repeatedly, significant.

    ``p_value`` is None for quantities without repetitions (binary sizes, single breakdown runs), which are then
    judged by the threshold alone. Lower is better for everything compared here.
    """
    if not math.isfinite(change):
        return UNKNOWN
    significant = p_value is None or (math.isfinite(p_value) and p_value < alpha)
    if change > threshold and significant:
        return REGRESSION
    if change < -threshold and significant:
        return IMPROVEMENT
    return UNCHANGED
