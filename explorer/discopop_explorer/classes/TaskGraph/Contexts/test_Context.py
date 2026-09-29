# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the Context relation traversals.

The containment (parent_context / contained_contexts) and succession (predecessor /
successor) relations are built by TaskGraph's __calculate_context_nesting and
__calculate_context_successions, neither of which guarantees acyclicity, and both grow
with the amount of inlined code. Traversing them must therefore neither recurse (Python's
recursion limit is reached by well-formed structures alone) nor assume acyclicity.

Cyclic structures are wired up by assigning the fields directly, because the registration
methods reject the cycles they are able to detect - which is tested separately below."""

from __future__ import annotations

from typing import List, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

# comfortably above CPython's default recursion limit of 1000
LONG_CHAIN_LENGTH = 3000
# get_contained_contexts_in_sequence takes the PET graph but only walks the context relations
NO_PET = cast(PEGraphX, None)


def _make_contexts(amount: int) -> List[Context]:
    return [Context() for _ in range(amount)]


def _link_sequence(contexts: List[Context]) -> None:
    for predecessor, successor in zip(contexts, contexts[1:]):
        predecessor.register_successor_context(successor)


def _nest(parent: Context, child: Context) -> None:
    parent.contained_contexts.add(child)
    child.parent_context = parent


# --- traversal termination ----------------------------------------------------------------


def test_get_contained_contexts_in_sequence_reports_nested_contexts_before_the_successor() -> None:
    """The enumeration is a pre-order walk: a context, then what it contains, then its
    successor."""
    region, first, first_child, second = _make_contexts(4)
    _nest(region, first)
    _nest(region, second)
    _nest(first, first_child)
    first.register_successor_context(second)

    assert region.get_contained_contexts_in_sequence(NO_PET) == [first, first_child, second]


def test_get_contained_contexts_in_sequence_terminates_on_cyclic_successor_chain() -> None:
    region, first, second, third = _make_contexts(4)
    for ctx in (first, second, third):
        _nest(region, ctx)
    _link_sequence([first, second, third])
    third.successor = first  # closes the cycle
    first.predecessor = None  # ... and keeps first the entry of the sequence

    result = region.get_contained_contexts_in_sequence(NO_PET)

    assert result == [first, second, third]


def test_get_contained_contexts_in_sequence_terminates_on_cyclic_containment() -> None:
    region, outer, inner = _make_contexts(3)
    _nest(region, outer)
    _nest(outer, inner)
    inner.contained_contexts.add(outer)  # closes the cycle

    result = region.get_contained_contexts_in_sequence(NO_PET)

    assert set(result) == {outer, inner}
    assert len(result) == len(set(result))


def test_get_contained_contexts_in_sequence_survives_long_successor_chain() -> None:
    """A sequence of contexts is a linked list; walking it recursively costs one stack frame
    per element and overflows long before the amount of contexts a real program produces."""
    region = Context()
    chain = _make_contexts(LONG_CHAIN_LENGTH)
    for ctx in chain:
        _nest(region, ctx)
    _link_sequence(chain)

    assert region.get_contained_contexts_in_sequence(NO_PET) == chain


def test_get_contained_contexts_in_sequence_survives_deep_nesting() -> None:
    nested = _make_contexts(LONG_CHAIN_LENGTH)
    for parent, child in zip(nested, nested[1:]):
        _nest(parent, child)

    assert nested[0].get_contained_contexts_in_sequence(NO_PET) == nested[1:]


def test_get_contained_contexts_and_nodes_survive_deep_nesting() -> None:
    nested = _make_contexts(LONG_CHAIN_LENGTH)
    for parent, child in zip(nested, nested[1:]):
        _nest(parent, child)

    assert nested[0].get_contained_contexts(inclusive=True) == set(nested[1:])
    assert nested[0].get_contained_nodes(inclusive=True) == []


def test_get_contained_contexts_terminates_on_cyclic_containment() -> None:
    outer, inner = _make_contexts(2)
    _nest(outer, inner)
    inner.contained_contexts.add(outer)

    assert outer.get_contained_contexts(inclusive=True) == {inner}


# --- region boundary ----------------------------------------------------------------------


def test_get_contained_contexts_in_sequence_does_not_leave_the_enclosing_region() -> None:
    """Nothing stops a successor chain from pointing out of the enclosing context if the
    structure is malformed. Following it would report contexts - and through them CUs - from
    unrelated parts of the program as part of this region's sequence."""
    region, inside, outside_region, outside = _make_contexts(4)
    _nest(region, inside)
    _nest(outside_region, outside)
    inside.successor = outside
    outside.predecessor = inside

    assert region.get_contained_contexts_in_sequence(NO_PET) == [inside]


# --- deterministic order ------------------------------------------------------------------


def test_get_sequence_entry_contexts_is_ordered_by_creation() -> None:
    """contained_contexts is a set, so the enumeration order of independent sequences within
    one region would otherwise vary between runs."""
    region = Context()
    entries = _make_contexts(16)
    for ctx in entries:
        _nest(region, ctx)

    assert region.get_sequence_entry_contexts() == entries
    assert region.get_contained_contexts_in_sequence(NO_PET) == entries


# --- cycle rejection on registration ------------------------------------------------------


def test_add_contained_context_rejects_an_ancestor() -> None:
    outer, inner = _make_contexts(2)
    outer.add_contained_context(inner)
    inner.register_parent_context(outer)

    inner.add_contained_context(outer)

    assert outer not in inner.contained_contexts


def test_register_parent_context_rejects_a_descendant() -> None:
    outer, inner = _make_contexts(2)
    outer.add_contained_context(inner)
    inner.register_parent_context(outer)

    outer.register_parent_context(inner)

    assert outer.parent_context is None


def test_register_successor_context_rejects_its_own_predecessor() -> None:
    first, second = _make_contexts(2)
    first.register_successor_context(second)

    second.register_successor_context(first)

    assert second.successor is None
    assert first.predecessor is None
