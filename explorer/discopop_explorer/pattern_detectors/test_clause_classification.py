# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the completion of the data sharing clauses from the syntax tree (complete_clauses_from_ast)."""

from __future__ import annotations

from typing import Any, Set

from discopop_explorer.pattern_detectors.clause_classification import complete_clauses_from_ast
from discopop_explorer.utilities.ASTUtils.OuterReferences import OuterReference


class _Sets:
    def __init__(self) -> None:
        self.first_private: Set[str] = set()
        self.private: Set[str] = set()
        self.last_private: Set[str] = set()
        self.shared: Set[str] = set()

    def complete(self, refs: list[OuterReference], loop_variables: Set[str] | None = None) -> list[tuple[str, str]]:
        return complete_clauses_from_ast(
            refs, loop_variables or set(), self.first_private, self.private, self.last_private, self.shared
        )


def ref(name: str, type_str: str = "double", **flags: Any) -> OuterReference:
    decl_kind = flags.pop("decl_kind", "VarDecl")
    return OuterReference(name=name, decl_id="0x" + name, decl_kind=decl_kind, type=type_str, **flags)


def test_unwritten_variables_become_shared_without_a_note() -> None:
    sets = _Sets()

    notes = sets.complete(
        [ref("n", "std::size_t"), ref("k", "const double", is_const=True), ref("in", "std::span<const double>")]
    )

    assert sets.shared == {"n", "k", "in"}
    assert notes == []


def test_classified_variables_and_loop_variables_are_left_alone() -> None:
    sets = _Sets()
    sets.private.add("x")

    sets.complete([ref("x", maybe_written=True), ref("i", "std::size_t")], loop_variables={"i"})

    assert sets.private == {"x"} and sets.shared == set() and sets.first_private == set()


def test_a_written_variable_without_profile_evidence_is_firstprivate() -> None:
    sets = _Sets()

    notes = sets.complete([ref("total", maybe_written=True)])

    assert sets.first_private == {"total"}
    assert len(notes) == 1 and notes[0][0] == "total" and "'total'" in notes[0][1]


def test_an_escaping_alias_makes_a_read_only_variable_uncertain_but_not_a_const_one() -> None:
    sets = _Sets()

    sets.complete([ref("a", address_escapes=True), ref("c", "const double", is_const=True, address_escapes=True)])

    assert sets.first_private == {"a"} and sets.shared == {"c"}


def test_scratch_object_is_private_and_flagged() -> None:
    sets = _Sets()

    notes = sets.complete(
        [
            ref(
                "tmp",
                "Acc",
                maybe_written=True,
                modified_via_call=True,
                modified_as_object=True,
                call_lines=[7],
                default_constructed=True,
            )
        ]
    )

    assert sets.private == {"tmp"}
    assert len(notes) == 1 and "line 7" in notes[0][1] and "private" in notes[0][1]


def test_scratch_object_used_after_the_loop_is_lastprivate() -> None:
    sets = _Sets()

    sets.complete(
        [
            ref(
                "tmp",
                "Acc",
                maybe_written=True,
                modified_via_call=True,
                modified_as_object=True,
                used_after_loop=True,
                default_constructed=True,
            )
        ]
    )

    assert sets.last_private == {"tmp"}


def test_scratch_object_without_default_constructor_is_firstprivate_not_private() -> None:
    sets = _Sets()

    notes = sets.complete(
        [ref("si", "SynapticInput", maybe_written=True, modified_via_call=True, modified_as_object=True)]
    )

    assert sets.first_private == {"si"} and sets.private == set()
    assert "default constructor" in notes[0][1]


def test_container_passed_by_mutable_reference_stays_shared_and_is_flagged() -> None:
    sets = _Sets()

    notes = sets.complete([ref("grid", "std::vector<double>", maybe_written=True, modified_via_call=True)])

    assert sets.shared == {"grid"} and sets.private == set() and sets.first_private == set()
    assert len(notes) == 1


def test_parameter_whose_methods_are_called_stays_shared() -> None:
    """A parameter is the data the iterations work on, not a scratch object."""
    sets = _Sets()

    sets.complete(
        [
            ref(
                "acc",
                "Acc &",
                decl_kind="ParmVarDecl",
                maybe_written=True,
                modified_via_call=True,
                modified_as_object=True,
            )
        ]
    )

    assert sets.shared == {"acc"}


def test_scalar_whose_address_is_passed_is_firstprivate() -> None:
    sets = _Sets()

    sets.complete([ref("t", "double", maybe_written=True, modified_via_call=True)])

    assert sets.first_private == {"t"}


def test_static_local_is_shared() -> None:
    sets = _Sets()

    sets.complete([ref("counter", "int", is_static=True, maybe_written=True)])

    assert sets.shared == {"counter"}


def test_global_is_shared_without_a_note() -> None:
    """default(none) requires a global to be listed; it is never private."""
    sets = _Sets()

    notes = sets.complete([ref("g_scale", "double", is_global=True, maybe_written=True)])

    assert sets.shared == {"g_scale"} and notes == []


def test_a_lock_is_shared_even_though_its_methods_are_called() -> None:
    """A private copy of a mutex removes the mutual exclusion."""
    sets = _Sets()

    notes = sets.complete(
        [
            ref(
                "m",
                "std::mutex",
                maybe_written=True,
                modified_via_call=True,
                modified_as_object=True,
                default_constructed=True,
            )
        ]
    )

    assert sets.shared == {"m"} and sets.private == set() and sets.first_private == set()
    assert notes[0][0] == "m"


def test_an_atomic_is_shared_not_copied() -> None:
    sets = _Sets()

    sets.complete(
        [ref("count", "std::atomic<int>", maybe_written=True, modified_via_call=True, modified_as_object=True)]
    )

    assert sets.shared == {"count"} and sets.first_private == set()


def test_a_typedef_does_not_hide_a_scalar() -> None:
    """``using real = double``: the resolved type decides, so the scalar whose address is passed on is firstprivate and
    not treated as an object."""
    sets = _Sets()

    sets.complete([ref("t", "real", desugared_type="double", maybe_written=True, modified_via_call=True)])

    assert sets.first_private == {"t"} and sets.shared == set()


def test_a_typedef_of_a_class_is_still_a_class() -> None:
    sets = _Sets()

    sets.complete(
        [
            ref(
                "tmp",
                "Scratch",
                desugared_type="Acc",
                maybe_written=True,
                modified_via_call=True,
                modified_as_object=True,
                default_constructed=True,
            )
        ]
    )

    assert sets.private == {"tmp"}
