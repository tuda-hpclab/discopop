# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Set, Tuple

from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.result_classes.DetectionResult import DetectionResult


def get_applicable_suggestion_ids(file_id: int, start_line: int, dtres: DetectionResult) -> List[SUGGESTION_ID]:
    """Identify suggestions where start position matches the given start position and return their ids."""
    res: List[int] = []
    for pattern_type in dtres.patterns.__dict__:
        for pattern in dtres.patterns.__dict__[pattern_type]:
            if pattern.start_line == str(file_id) + ":" + str(start_line) and pattern.applicable_pattern:
                res.append(pattern.pattern_id)
    return res


def restrict_patterns_to_ids(dtres: DetectionResult, allowed_ids: Set[int]) -> List[int]:
    """Prune the in-memory pattern storage to only the allowed suggestion ids.

    Every optimization algorithm derives its candidate suggestions from
    ``dtres.patterns`` (via ``get_patterns_by_hotspot_type`` /
    ``PatternStorage.get_pattern_ids``), so filtering the storage once here
    restricts the entire search space for all algorithms. ``dtres`` is an
    in-memory object that is never written back to disk, so this has no
    side effects beyond the current run. Returns the sorted list of ids kept.
    """
    kept: List[int] = []
    for pattern_type in dtres.patterns.__dict__:
        remaining = [pattern for pattern in dtres.patterns.__dict__[pattern_type] if pattern.pattern_id in allowed_ids]
        dtres.patterns.__dict__[pattern_type] = remaining
        kept.extend(pattern.pattern_id for pattern in remaining)
    return sorted(kept)
