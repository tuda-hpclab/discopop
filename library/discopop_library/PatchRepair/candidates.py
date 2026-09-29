# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which suggestions the repair tool considers, and in which order.

The candidate list is the intersection of three things: the suggestions the explorer
found, the hotspot buckets the caller asked for, and the ids the patch generator
actually produced patches for. A suggestion missing from any of them has nothing to
repair -- either it does not exist, or it is not worth repairing, or there is no
patch to hand to an agent.
"""

from dataclasses import dataclass
import logging
import os
from typing import Dict, List, Optional

import jsonpickle  # type: ignore

from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.result_classes.DetectionResult import DetectionResult

logger = logging.getLogger("PatchRepair").getChild("candidates")

# Hot first: a --max-repairs budget is then spent where a working parallelization
# actually pays off, and an interrupted run has done the valuable work already.
HOTSPOT_PRIORITY = [HotspotType.YES, HotspotType.MAYBE, HotspotType.NO]

HOTSPOT_TYPE_NAMES = {HotspotType.YES: "yes", HotspotType.MAYBE: "maybe", HotspotType.NO: "no"}


@dataclass
class Candidate:
    suggestion_id: int
    hotspot_type: str


def load_detection_result(dot_dp_path: str) -> DetectionResult:
    dump_path = os.path.join(dot_dp_path, "explorer", "detection_result_dump.json")
    if not os.path.exists(dump_path):
        raise FileNotFoundError(
            "No detection result found. Please execute the discopop_explorer in advance."
            + "\nExpected file: "
            + dump_path
        )
    with open(dump_path, "r") as f:
        result: DetectionResult = jsonpickle.decode(f.read(), keys=True)
    return result


def suggestion_ids_with_patches(patch_generator_path: str) -> List[int]:
    """The ids the patch generator produced a patch directory for."""
    if not os.path.exists(patch_generator_path):
        return []
    ids: List[int] = []
    for entry in os.listdir(patch_generator_path):
        if not entry.isdigit():
            continue
        if not os.path.isdir(os.path.join(patch_generator_path, entry)):
            continue
        ids.append(int(entry))
    return sorted(ids)


def hotspot_type_by_suggestion(arguments: PatchRepairArguments, detection_result: DetectionResult) -> Dict[int, str]:
    """Map every suggestion id to its hotspot bucket name.

    Falls back to classifying everything as ``yes`` when no hotspot information
    exists, mirroring ``get_patterns_by_hotspot_type``: without measurements there is
    no basis for calling a suggestion cold, and skipping it would be a guess.
    """
    hsl_arguments = HotspotLoaderArguments(
        "WARNING", arguments.write_log, False, arguments.dot_dp_path, True, False, True, True, True
    )
    hotspot_information = load_hotspots(hsl_arguments)
    by_type = get_patterns_by_hotspot_type(detection_result, hotspot_information)
    mapping: Dict[int, str] = {}
    for hotspot_type in HOTSPOT_PRIORITY:
        for suggestion_id in by_type.get(hotspot_type, []):
            mapping[suggestion_id] = HOTSPOT_TYPE_NAMES[hotspot_type]
    return mapping


def collect_candidates(
    arguments: PatchRepairArguments, detection_result: Optional[DetectionResult] = None
) -> List[Candidate]:
    """The suggestions to consider, hottest first."""
    if detection_result is None:
        detection_result = load_detection_result(arguments.dot_dp_path)

    with_patches = suggestion_ids_with_patches(arguments.patch_generator_path)
    if not with_patches:
        logger.warning("No patches found in " + arguments.patch_generator_path + ".")
        return []

    by_suggestion = hotspot_type_by_suggestion(arguments, detection_result)

    explicit = arguments.explicit_suggestion_ids()
    if explicit is not None:
        # An explicitly named id is repaired whatever its hotspot type says: the caller
        # has already decided it is worth the effort.
        missing = [suggestion_id for suggestion_id in explicit if suggestion_id not in with_patches]
        if missing:
            logger.warning("No patch was generated for the requested suggestions: " + str(sorted(missing)))
        return [
            Candidate(suggestion_id, by_suggestion.get(suggestion_id, "unknown"))
            for suggestion_id in explicit
            if suggestion_id in with_patches
        ]

    selected_types = arguments.selected_hotspot_types()
    candidates: List[Candidate] = []
    skipped: List[int] = []
    for hotspot_type in HOTSPOT_PRIORITY:
        type_name = HOTSPOT_TYPE_NAMES[hotspot_type]
        for suggestion_id in sorted(with_patches):
            if by_suggestion.get(suggestion_id) != type_name:
                continue
            if type_name in selected_types:
                candidates.append(Candidate(suggestion_id, type_name))
            else:
                skipped.append(suggestion_id)

    # A suggestion the hotspot loader never classified has no bucket to filter it by.
    # Dropping it silently would make it invisible, so it is considered last.
    unclassified = [
        suggestion_id
        for suggestion_id in sorted(with_patches)
        if suggestion_id not in by_suggestion and suggestion_id not in skipped
    ]
    candidates.extend(Candidate(suggestion_id, "unknown") for suggestion_id in unclassified)

    if skipped:
        logger.info(
            "Skipping "
            + str(len(skipped))
            + " suggestion(s) whose hotspot type is not in "
            + arguments.hotspot_types
            + ": "
            + str(sorted(skipped))
        )
    return candidates
