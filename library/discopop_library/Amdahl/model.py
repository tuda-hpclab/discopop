# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Amdahl ceilings for a set of applied parallelization suggestions.

For a set of suggestions, ``p`` is the fraction of the sequential runtime spent in the
regions those suggestions parallelize. Amdahl's law then bounds the achievable speedup:

* ``amdahl_ceiling(p, n) = 1 / ((1 - p) + p / n)`` for ``n`` threads, and
* ``amdahl_limit(p) = 1 / (1 - p)`` for an unlimited number of threads.

``p`` is an *estimate*: region runtimes come from the instrumented hotspot-detection
runs (``Hotspots.json``), not from the measured program. Every function returns None
rather than a guess when an input is unknown, so a consumer can leave the point out.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class SuggestionRegion:
    """The source range one suggestion parallelizes and its share of the program's runtime."""

    suggestion_id: int
    file_id: int
    start_line: int
    end_line: int
    # region runtime / whole-program runtime, None if no hotspot region matched
    time_share: Optional[float]


def parallel_fraction(suggestion_ids: Iterable[int], regions: Dict[int, SuggestionRegion]) -> Optional[float]:
    """Fraction of the sequential runtime covered by the suggestions, or None if unknown.

    A suggestion whose region is nested inside another selected suggestion's region (same
    file, contained line range) is already covered by it and is counted once. The empty
    set covers nothing: p = 0.
    """
    selected: List[SuggestionRegion] = []
    for suggestion_id in suggestion_ids:
        region = regions.get(int(suggestion_id))
        if region is None or region.time_share is None:
            return None
        selected.append(region)
    # outermost first; identical ranges keep one representative
    selected.sort(key=lambda r: (r.file_id, r.start_line, -r.end_line, r.suggestion_id))
    kept: List[SuggestionRegion] = []
    for region in selected:
        if any(
            k.file_id == region.file_id and k.start_line <= region.start_line and region.end_line <= k.end_line
            for k in kept
        ):
            continue
        kept.append(region)
    total = sum(r.time_share for r in kept if r.time_share is not None)
    return max(0.0, min(1.0, total))


def amdahl_ceiling(p: Optional[float], threads: int) -> Optional[float]:
    """Speedup bound for parallel fraction ``p`` on ``threads`` threads (None if unknown)."""
    if p is None or threads < 1:
        return None
    return 1.0 / ((1.0 - p) + p / threads)


def amdahl_limit(p: Optional[float]) -> Optional[float]:
    """Speedup bound for an unlimited number of threads; ``math.inf`` if p == 1, None if unknown."""
    if p is None:
        return None
    if p >= 1.0:
        return math.inf
    return 1.0 / (1.0 - p)


def finite_or_none(value: Optional[float]) -> Optional[float]:
    """Rounded value for JSON: None and infinity (not valid JSON) both become None."""
    if value is None or math.isinf(value) or math.isnan(value):
        return None
    return round(value, 4)


def ceilings(
    suggestion_ids: Iterable[int], threads: int, regions: Dict[int, SuggestionRegion]
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(parallel fraction, ceiling at ``threads``, ceiling at unlimited threads)."""
    p = parallel_fraction(suggestion_ids, regions)
    return p, amdahl_ceiling(p, threads), amdahl_limit(p)
