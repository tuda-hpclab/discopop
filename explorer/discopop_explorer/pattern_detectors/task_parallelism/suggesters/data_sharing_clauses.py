# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import line_contained_in_region


def suggest_shared_clauses_for_all_tasks_in_function_body(
    pet: PEGraphX, suggestions: List[PatternInfo]
) -> List[PatternInfo]:
    """Marks unmentioned variables as shared, if they occur as shared in a different task suggestions
    inside the parent functions body.
    :param: pet: PET graph
    :param: suggestions: List[PatternInfo]
    :return: List[PatternInfo]
    """
    task_suggestions = [s for s in [t for t in suggestions if type(t) == TaskParallelismInfo] if s.type is TPIType.TASK]
    for ts in task_suggestions:
        if ts.shared:
            # iterate over parent function(s)
            for parent_function in [
                pet.node_at(e[0])
                for e in in_edges(pet, ts._node.id, EdgeType.CHILD)
                if isinstance(pet.node_at(e[0]), FunctionNode)
            ]:
                # get task suggestions in parent functions scope
                for other_suggestion in task_suggestions:
                    if not (
                        line_contained_in_region(
                            other_suggestion.start_line,
                            parent_function.start_position(),
                            parent_function.end_position(),
                        )
                        and line_contained_in_region(
                            other_suggestion.end_line,
                            parent_function.start_position(),
                            parent_function.end_position(),
                        )
                    ):
                        # other suggestion not part of parent function
                        continue
                    # mark shared variables of ts as shared in other_suggestion, if not already mentioned
                    for var in ts.shared:
                        if var in other_suggestion.shared:
                            continue
                        if var in other_suggestion.private:
                            continue
                        if var in other_suggestion.first_private:
                            continue
                        other_suggestion.shared.append(var)

    return suggestions
