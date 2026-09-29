# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum
import logging
from typing import List, Optional, Tuple, cast

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext

logger = logging.getLogger("Explorer")


def get_context_call_stack(origin: Context) -> List[Context]:
    stack: List[Context] = []
    current_ctx: Optional[Context] = origin
    while current_ctx is not None:
        if (
            isinstance(current_ctx, FunctionContext)
            or isinstance(current_ctx, LoopParentContext)
            or isinstance(current_ctx, IterationContext)
        ):
            stack.append(current_ctx)
        current_ctx = current_ctx.parent_context
    return list(reversed(stack))


class CallStackElementType(IntEnum):
    FUNCTION = 0
    LOOP = 1
    ITERATION = 2


def convert_callstacks_to_lineIDs(pet: PEGraphX, callstack: List[Context]) -> List[Tuple[CallStackElementType, LineID]]:
    result: List[Tuple[CallStackElementType, LineID]] = []
    for call_stack_elem in callstack:
        # determine call stack element type
        if isinstance(call_stack_elem, FunctionContext):
            cse_type = CallStackElementType.FUNCTION
        elif isinstance(call_stack_elem, LoopParentContext):
            cse_type = CallStackElementType.LOOP
        elif isinstance(call_stack_elem, IterationContext):
            cse_type = CallStackElementType.ITERATION
        else:
            raise ValueError("Unsupported call stack element type: " + str(type(call_stack_elem)))
        # determine call stack element line id
        if cse_type == CallStackElementType.FUNCTION:
            lookup_node_id = cast(FunctionContext, call_stack_elem).parent_function
        elif cse_type == CallStackElementType.LOOP:
            lookup_node_id = cast(LoopParentContext, call_stack_elem).parent_loop
        elif cse_type == CallStackElementType.ITERATION:
            lookup_node_id = cast(
                LoopParentContext, cast(IterationContext, call_stack_elem).belongs_to_context
            ).parent_loop
        else:
            raise ValueError("Unsupported cse_type: " + str(cse_type))
        if lookup_node_id is None:
            logger.warning("Empty PETNodeID found! Ignoring call stack element: " + str(call_stack_elem))
            continue
        line_id = pet.node_at(lookup_node_id).start_position()
        result.append((cse_type, line_id))

    return result
