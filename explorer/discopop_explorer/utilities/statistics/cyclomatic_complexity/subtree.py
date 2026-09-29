# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import TYPE_CHECKING, List, cast

from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult
    from discopop_explorer.utilities.statistics.cyclomatic_complexity.cc_dictionary import CC_DICT
    from discopop_explorer.aliases.NodeID import NodeID

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type


def get_subtree_cyclomatic_complexity_from_calls(
    arguments: ExplorerArguments, res: DetectionResult, cc_dict: CC_DICT, root_node_id: NodeID
) -> int:
    subtree = subtree_of_type(res.pet, res.pet.node_at(root_node_id))
    # collect called functions
    called_functions: List[FunctionNode] = []
    for node in subtree:
        out_call_edges = out_edges(res.pet, node.id, EdgeType.CALLSNODE)
        for _, target, _ in out_call_edges:
            called_functions.append(cast(FunctionNode, res.pet.node_at(target)))
    # identify cyclomatic complexities for called functions by matching against cc_dict entries
    # due to overloading or name extensions (i.e. get_a vs. get_a_and_b), select the shortest function name that matches
    cyclomatic_complexities: List[int] = []
    for func in called_functions:
        if func.file_id not in cc_dict:
            continue
        candidates: List[str] = []
        for clean_func_name in cc_dict[func.file_id]:
            if clean_func_name in func.name:
                candidates.append(clean_func_name)
        sorted_candidates = sorted(candidates, key=lambda x: len(x))
        if len(sorted_candidates) > 0:
            best_match = sorted_candidates[0]
            cyclomatic_complexities.append(cc_dict[func.file_id][best_match])

    # sum cyclomatic complexities of called functions
    return sum(cyclomatic_complexities)
