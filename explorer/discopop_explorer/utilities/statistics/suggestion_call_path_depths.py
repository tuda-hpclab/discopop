# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Dict, Set
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.utilities.statistics.utilities.call_path_depth import get_outgoing_call_path_depth
from discopop_library.result_classes.DetectionResult import DetectionResult


def get_suggestion_call_path_depths(res: DetectionResult) -> Dict[int, int]:
    res_dict: Dict[int, int] = dict()

    # collect NodeIDs where suggestions are located
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            res_dict[pattern.pattern_id] = get_outgoing_call_path_depth(res.pet, res.pet.node_at(pattern.node_id))

    return res_dict
