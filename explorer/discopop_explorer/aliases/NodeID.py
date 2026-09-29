# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import List


class NodeID(str):
    # simpler but still strong typing alternative:
    # NodeID = NewType("NodeID", str) or remove __init__
    def __init__(self, id_string: str):
        # check format of newly created NodeID's
        if ":" not in id_string:
            raise ValueError("Mal-formatted NodeID: ", id_string)
        split_id: List[str] = id_string.split(":")
        if len(split_id) != 2:
            raise ValueError("Mal-formatted NodeID: ", id_string)
        try:
            int(split_id[0])
            int(split_id[1])
        except ValueError:
            raise ValueError("Mal-formatted NodeID: ", id_string)
