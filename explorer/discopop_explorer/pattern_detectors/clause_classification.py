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

from typing import Set, Tuple


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
