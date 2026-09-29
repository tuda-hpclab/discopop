# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for ContextStack, the record of currently open contexts that
TaskGraph.__calculate_context_successions carries along every path it walks."""

from __future__ import annotations

from typing import Optional

from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.ContextStack import ContextStack


def test_pushing_keeps_the_enclosing_contexts() -> None:
    outer, inner = Context(), Context()

    stack = ContextStack(outer, None)
    assert stack.as_list() == [outer]

    stack = ContextStack(inner, stack)
    assert stack.as_list() == [outer, inner]
    assert stack.innermost is inner


def test_popping_hands_back_the_context_that_was_left() -> None:
    """This is what the stack is for: after leaving a context, that context is the one a following
    sibling has to be registered behind, and it is only recoverable from here."""
    outer, inner = Context(), Context()
    stack: Optional[ContextStack] = ContextStack(inner, ContextStack(outer, None))

    assert stack is not None
    left, stack = stack.innermost, stack.enclosing
    assert left is inner

    assert stack is not None
    left, stack = stack.innermost, stack.enclosing
    assert left is outer
    assert stack is None, "an empty stack is None, not an empty instance"


def test_the_enclosing_contexts_are_shared_between_paths() -> None:
    """Why this is a linked structure and not a copied list: the succession calculation derives one
    of these per graph edge, so pushing must not cost anything proportional to the nesting depth."""
    enclosing = ContextStack(Context(), ContextStack(Context(), None))
    branch_a = ContextStack(Context(), enclosing)
    branch_b = ContextStack(Context(), enclosing)

    assert branch_a.enclosing is branch_b.enclosing is enclosing
    assert branch_a.as_list()[:2] == branch_b.as_list()[:2] == enclosing.as_list()
