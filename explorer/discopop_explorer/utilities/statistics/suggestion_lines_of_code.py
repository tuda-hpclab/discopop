# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Dict, List, Set
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_library.result_classes.DetectionResult import DetectionResult


def get_suggestion_immediate_lines_of_code(res: DetectionResult) -> Dict[int, int]:  # pattern_id: lines of code
    # immediate lines of code --> scope size without following function calls
    res_dict: Dict[int, int] = dict()

    # collect scope sizes without following function calls
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            start_line_num = int(pattern.start_line.split(":")[1])
            end_line_num = int(pattern.end_line.split(":")[1])
            res_dict[pattern.pattern_id] = end_line_num - start_line_num

    return res_dict


def get_suggestion_lines_of_code_including_calls(
    res: DetectionResult,
) -> Dict[int, int]:  # pattern_id : lines of inlined code
    # lines of code are counted as if every function call would be inlined
    res_dict: Dict[int, int] = dict()

    # step 1: get immediate lines of code per pattern
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            start_line_num = int(pattern.start_line.split(":")[1])
            end_line_num = int(pattern.end_line.split(":")[1])
            res_dict[pattern.pattern_id] = end_line_num - start_line_num

    # step 2: add lines of code from function calls
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            pattern_base_node = res.pet.node_at(pattern.node_id)
            # get subtree of pattern base node and collect line ids
            subtree = subtree_of_type(res.pet, pattern_base_node)
            lines_in_subtree: Set[LineID] = set()
            for node in subtree:
                for line_num_in_scope in range(node.start_line, node.end_line + 1):
                    lines_in_subtree.add(LineID(str(node.file_id) + ":" + str(line_num_in_scope)))
            # count distinct line ids and add to the result
            res_dict[pattern.pattern_id] += len(lines_in_subtree)

    return res_dict
