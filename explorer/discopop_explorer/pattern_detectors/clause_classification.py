# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Post-processing of OpenMP data sharing clause classifications.

Used by the do-all detection (see new_do_all_detector.py) as well as by the loop collapse analysis
(see loop_collapse_analysis.py), so that both apply one and the same precedence between the
clauses.
"""

import re
from typing import Iterable, List, Set, Tuple

from discopop_explorer.utilities.ASTUtils.OuterReferences import OuterReference


def merge_classifications(
    first_private: Set[str],
    private: Set[str],
    last_private: Set[str],
    shared: Set[str],
) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Resolves variables which got classified into more than one data sharing clause down to a
    single, valid classification."""
    new_first_private: Set[str] = set()
    new_private: Set[str] = set()
    new_last_private: Set[str] = set()
    new_shared: Set[str] = set()

    remove_from_private: Set[str] = set()
    remove_from_first_private: Set[str] = set()
    remove_from_last_private: Set[str] = set()
    remove_from_shared: Set[str] = set()

    # Rule 1: firstprivate is more restrictive than private
    remove_from_private = first_private.intersection(private)
    # Rule 2: lastprivate is more restrictive than private
    remove_from_private = remove_from_private.union(last_private.intersection(private))
    # Rule 3: shared is less restrictive than first_private or last_private
    remove_from_shared = shared.intersection(first_private.union(last_private))
    # Rule 4: if a variable is classifyable as shared and private, select shared.
    remove_from_private = remove_from_private.union(shared.intersection(private))

    new_first_private = first_private - remove_from_first_private
    new_last_private = last_private - remove_from_last_private
    new_private = private - remove_from_private
    new_shared = shared - remove_from_shared

    return new_first_private, new_private, new_last_private, new_shared


def filter_classifications(
    known_vars: Set[str],
    first_private: Set[str],
    private: Set[str],
    last_private: Set[str],
    shared: Set[str],
) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """Removes variables which are not in scope at the location the pragma will be inserted at.

    For a collapsed loop nest this is what keeps variables declared inside the outer loop body out
    of the collapsed construct's clauses.
    """
    new_first_private: Set[str] = set()
    new_private: Set[str] = set()
    new_last_private: Set[str] = set()
    new_shared: Set[str] = set()

    remove_from_private: Set[str] = set()
    remove_from_first_private: Set[str] = set()
    remove_from_last_private: Set[str] = set()
    remove_from_shared: Set[str] = set()

    # perform filtering
    for var in first_private:
        if var not in known_vars:
            remove_from_first_private.add(var)
    for var in private:
        if var not in known_vars:
            remove_from_private.add(var)
    for var in last_private:
        if var not in known_vars:
            remove_from_last_private.add(var)
    for var in shared:
        if var not in known_vars:
            remove_from_shared.add(var)

    new_first_private = first_private - remove_from_first_private
    new_last_private = last_private - remove_from_last_private
    new_private = private - remove_from_private
    new_shared = shared - remove_from_shared

    return new_first_private, new_private, new_last_private, new_shared


# types which cannot be copied or whose whole point is to be shared between threads: a private or firstprivate copy
# does not compile (atomics, streams, threads) or removes the synchronization (mutexes, locks)
_SHARED_BY_NATURE = re.compile(
    r"\b(std::(atomic\w*|\w*mutex\w*|condition_variable\w*|once_flag|thread|jthread|unique_ptr|"
    r"basic_\w*stream\w*|\w*stream|\w*fstream|\w*stringstream|barrier|latch|counting_semaphore|binary_semaphore|"
    r"stop_source|lock_guard|unique_lock|scoped_lock)|omp_lock_t|omp_nest_lock_t|pthread_\w+_t)\b"
)


def _is_shared_by_nature(ref: OuterReference) -> bool:
    return _SHARED_BY_NATURE.search(ref.logical_type or "") is not None


def _is_class_like(ref: OuterReference) -> bool:
    """A variable which is neither a pointer nor a reference nor an array, and whose type is not a builtin."""
    type_str = ref.logical_type or ""
    if any(c in type_str for c in "*&["):
        return False
    builtin = {
        "bool", "char", "signed char", "unsigned char", "short", "unsigned short", "int", "unsigned int", "long",
        "unsigned long", "long long", "unsigned long long", "float", "double", "long double", "size_t",
        "std::size_t", "ptrdiff_t", "std::ptrdiff_t", "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t",
        "uint16_t", "uint32_t", "uint64_t", "std::int8_t", "std::int16_t", "std::int32_t", "std::int64_t",
        "std::uint8_t", "std::uint16_t", "std::uint32_t", "std::uint64_t",
    }  # fmt: skip
    return type_str.replace("const ", "").strip() not in builtin


def complete_clauses_from_ast(
    outer_references: Iterable[OuterReference],
    loop_variables: Set[str],
    first_private: Set[str],
    private: Set[str],
    last_private: Set[str],
    shared: Set[str],
) -> List[Tuple[str, str]]:
    """Classifies the variables the loop refers to which the profile did not classify, from the syntax tree.

    The clause sets are extended in place. Returns, for every classification which is a decision made without
    evidence from the profile, the name of the variable and one sentence for the suggestion to show.

    A variable is classified as shared only if nothing in the loop can write it. That is established from the tree:
    it is const, or no assignment, address-of, non-const reference binding or call of a non-const method on it occurs.
    Writes through a pointer or into the elements of a container (``out[i] = x``) are not writes to the variable.
    Everything else is uncertain:
    - modified through a call whose effect the profile does not attribute (``tmp.reset()``): a local object of value
      type is a scratch object and gets private (lastprivate if it is used after the loop, firstprivate if its
      declaration does not show a default constructor); any other variable (a parameter, a reference, a pointer, a
      container passed by reference) is the data the iterations work on and stays shared. A scalar whose address is
      passed on is firstprivate. All are noted.
    - written, or its address escapes: firstprivate, noted.
    - of a type which is shared by nature (lock, atomic, stream): shared, noted, as a copy does not compile or removes
      the synchronization.
    Globals are shared, as default(none) requires them to be listed.
    """
    notes: List[Tuple[str, str]] = []

    def note(name: str, text: str) -> None:
        notes.append((name, text))

    classified = first_private | private | last_private | shared
    for ref in outer_references:
        name = ref.name
        if name in classified or name in loop_variables:
            continue
        if ref.is_static or ref.is_global:
            shared.add(name)
            continue
        if _is_shared_by_nature(ref) and (ref.modified_via_call or ref.maybe_written or ref.address_escapes):
            shared.add(name)
            note(
                name,
                f"'{name}' is of a type which is shared between threads by nature (a lock, an atomic, a stream): "
                "classified shared.",
            )
            continue
        if ref.modified_via_call:
            lines = ", ".join(str(line) for line in sorted(ref.call_lines)) or "?"
            unattributed = (
                f"'{name}' is modified through calls (line {lines}) which the profile does not attribute to it"
            )
            written_type = ref.logical_type or ""
            if ref.modified_as_object and ref.decl_kind == "VarDecl" and _is_class_like(ref):
                # a local object whose methods are called: a scratch object, unless it is the data the iterations
                # work on. A private copy is default-constructed, which only a declaration without arguments proves
                # to be possible.
                if not ref.default_constructed:
                    first_private.add(name)
                    note(
                        name,
                        f"{unattributed}: classified firstprivate (a copy of the object per thread), as private "
                        "needs a default constructor. Check that every iteration initializes it.",
                    )
                elif ref.used_after_loop:
                    last_private.add(name)
                    note(
                        name,
                        f"{unattributed}: classified lastprivate, as it is used after the loop. "
                        "Check that every iteration initializes it.",
                    )
                else:
                    private.add(name)
                    note(
                        name,
                        f"{unattributed}: classified private. Check that every iteration initializes it, "
                        "otherwise the loop is not a do-all.",
                    )
            elif not _is_class_like(ref) and "[" not in written_type and "&" not in written_type:
                # a scalar whose address is passed on: a copy per thread cannot lose a write to shared data
                first_private.add(name)
                note(name, f"{unattributed}: classified firstprivate.")
            else:
                # data the iterations work on (a parameter, a reference, a container, an array): the calls write its
                # elements, and a private copy would lose them
                shared.add(name)
                note(name, f"{unattributed}: classified shared. Check that the iterations do not write the same state.")
            continue
        if ref.maybe_written or (ref.address_escapes and not ref.is_const):
            first_private.add(name)
            reason = "written in the loop" if ref.maybe_written else "its address is passed on outside of the loop"
            note(
                name,
                f"'{name}': {reason} and the profile does not cover it: classified firstprivate"
                + (" (a copy of the whole object per thread)." if _is_class_like(ref) else "."),
            )
            continue
        shared.add(name)
    return notes
