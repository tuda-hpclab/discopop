# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum


class HotspotNodeType(IntEnum):
    FUNCTION = 0
    LOOP = 1


def get_HotspotNodeType_from_string(input: str) -> HotspotNodeType:
    if input == "LOOP":
        return HotspotNodeType.LOOP
    if input == "FUNCTION":
        return HotspotNodeType.FUNCTION

    raise ValueError("Unknown Hotspot Node type: " + input)
