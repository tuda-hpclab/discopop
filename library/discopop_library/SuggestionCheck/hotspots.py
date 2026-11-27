# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The hotspot filter of the check, like patch repair's (PatchRepair/candidates.py): a check costs agent calls, which
a loop that does not matter for the runtime is not worth (design/agent_checked_suggestions.md, §5.1)."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import HotspotInformation, classify_by_loops, hotspot_loops
from discopop_library.SuggestionCheck.unsure import Location, UnsureSuggestion

YES = "yes"
MAYBE = "maybe"
NO = "no"
# hotspot results exist, but no hotspot loop starts in the loop: there is nothing to filter it by, so it is checked
UNKNOWN = "unknown"
_NAMES = {HotspotType.YES: YES, HotspotType.MAYBE: MAYBE, HotspotType.NO: NO}


def load(dot_dp_path: str) -> HotspotInformation:
    """The hotspot loops of the project, as patch repair loads them; empty without hotspot results."""
    return load_hotspots(HotspotLoaderArguments("WARNING", False, False, dot_dp_path, True, False, True, True, True))


def classify(suggestions: Sequence[UnsureSuggestion], hotspot_information: HotspotInformation) -> Dict[int, str]:
    """The hotspot class (YES, MAYBE, NO or UNKNOWN) of each suggestion by its pattern id.

    The rule get_patterns_by_hotspot_type applies to a pattern, on the lines the pattern spans (its start_line and
    end_line as the explorer wrote them, not the loop's region): an unsure suggestion is classified as the same loop
    would be as a suggestion. Without hotspot results every suggestion is YES, so nothing is skipped."""
    if not hotspot_information:
        return {s.pattern_id: YES for s in suggestions}
    loops = hotspot_loops(hotspot_information)
    classes: Dict[int, str] = dict()
    for suggestion in suggestions:
        end = Location.parse(suggestion.data.get("end_line")) or suggestion.end
        found = classify_by_loops(suggestion.start.file_id, suggestion.start.line, end.line, loops)
        classes[suggestion.pattern_id] = UNKNOWN if found is None else _NAMES[found]
    return classes


def split(
    suggestions: Sequence[UnsureSuggestion], classes: Dict[int, str], selected: Sequence[str]
) -> Tuple[List[UnsureSuggestion], List[UnsureSuggestion]]:
    """(to check, skipped): a suggestion is skipped if its class is not selected; UNKNOWN is never skipped."""
    checked: List[UnsureSuggestion] = []
    skipped: List[UnsureSuggestion] = []
    for suggestion in suggestions:
        hotspot_class = classes.get(suggestion.pattern_id, UNKNOWN)
        if hotspot_class == UNKNOWN or hotspot_class in selected:
            checked.append(suggestion)
        else:
            skipped.append(suggestion)
    return checked, skipped
