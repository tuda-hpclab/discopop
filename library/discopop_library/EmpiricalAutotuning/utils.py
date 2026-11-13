# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
from typing import Dict, List, Set

from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.PatchApplicator.outside_project import (
    find_outside_project_targets,
    log_skipped_outside_suggestions,
)
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


def exclude_outside_project_patterns(
    dtres: DetectionResult, dot_dp_path: str, logger: logging.Logger
) -> Dict[str, List[str]]:
    """Prune the in-memory pattern storage of every suggestion that patches files outside the project.

    The autotuner works in several copies of the project at once, which do not isolate files outside of it: such
    a suggestion would modify the shared original concurrently and nothing would restore it. They are skipped (and
    logged), a manual application is the only way to apply them. Returns the skipped suggestions with their outside
    targets. Like :func:`restrict_patterns_to_ids`, this changes only the in-memory ``dtres``.
    """
    all_ids = [
        str(pattern.pattern_id)
        for pattern_type in dtres.patterns.__dict__
        for pattern in dtres.patterns.__dict__[pattern_type]
    ]
    outside = find_outside_project_targets(dot_dp_path, all_ids)
    if outside:
        log_skipped_outside_suggestions(logger, "Autotuner", outside)
        for pattern_type in dtres.patterns.__dict__:
            dtres.patterns.__dict__[pattern_type] = [
                pattern for pattern in dtres.patterns.__dict__[pattern_type] if str(pattern.pattern_id) not in outside
            ]
    return outside
