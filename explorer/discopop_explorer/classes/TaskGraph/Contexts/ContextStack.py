# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import List, Optional

from discopop_explorer.classes.TaskGraph.Contexts.Context import Context


class ContextStack:
    """The contexts a traversal of the TaskGraph is currently inside, innermost first. An empty
    stack is represented by None rather than by an instance.

    __calculate_context_successions carries one of these along every path it walks, together with
    the context that most recently ended at the current level. Entering a context pushes it;
    leaving one pops it and hands it back as exactly that "most recently ended" context, which is
    what the next context entered at the level is registered behind.

    The stack is immutable, so all paths derived from a node share the tail they have in common:
    pushing allocates one cell, popping allocates nothing, and passing the stack to a successor
    copies nothing. The list this replaced was rebuilt into a tuple once per graph edge, so every
    edge cost time and memory proportional to the current nesting depth - the dominating cost of
    the pass on deeply nested code."""

    __slots__ = ("innermost", "enclosing")

    innermost: Context
    enclosing: Optional[ContextStack]

    def __init__(self, innermost: Context, enclosing: Optional[ContextStack] = None) -> None:
        self.innermost = innermost
        self.enclosing = enclosing

    def as_list(self) -> List[Context]:
        """The open contexts from the outermost to the innermost one. For debugging and tests."""
        contexts: List[Context] = []
        current: Optional[ContextStack] = self
        while current is not None:
            contexts.append(current.innermost)
            current = current.enclosing
        contexts.reverse()
        return contexts
