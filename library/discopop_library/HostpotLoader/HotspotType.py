# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum
from typing import List


class HotspotType(IntEnum):
    NO = 0
    YES = 1
    MAYBE = 2


def get_HotspotType_from_string(input: str) -> HotspotType:
    if input == "NO":
        return HotspotType.NO
    if input == "YES":
        return HotspotType.YES
    if input == "MAYBE":
        return HotspotType.MAYBE
    raise ValueError("Unknown Hotspot type: " + input)


def parse_hotspot_types(input: str) -> List[HotspotType]:
    """Parse a comma separated list of hotspot types, e.g. "yes,maybe".

    Case insensitive and tolerant of surrounding whitespace, so it accepts the
    same spelling the autotuner's -ht/--hotspot-types option uses. Duplicates
    are collapsed, the given order is preserved. Raises ValueError for an
    unknown type name or an empty selection, leaving it to the caller to turn
    that into a suitable error message.
    """
    result: List[HotspotType] = []
    for element in input.split(","):
        name = element.strip().upper()
        if not name:
            continue
        hotspot_type = get_HotspotType_from_string(name)
        if hotspot_type not in result:
            result.append(hotspot_type)
    if not result:
        raise ValueError("No hotspot type given.")
    return result
