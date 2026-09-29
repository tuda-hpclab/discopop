# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from typing import Dict, Set
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.utilities.statistics.utilities.num_function_calls import get_num_function_calls
from discopop_library.result_classes.DetectionResult import DetectionResult


def get_suggestion_num_function_calls(res: DetectionResult) -> Dict[int, int]:
    res_dict: Dict[int, int] = dict()

    # collect number of function calls in entire subtree of a parallelization suggestion
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            res_dict[pattern.pattern_id] = get_num_function_calls(res.pet, res.pet.node_at(pattern.node_id), [])

    return res_dict
