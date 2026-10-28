# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The callpath states of the profiler: which calls led to the instance of a function that made an access.

``stateID_to_callpath_mapping.txt`` is a prefix tree, one line ``<state id> <parent state id> <label>`` per state; the
label is a function name (``put``), a call (``call_68``: the call instruction with the id 68) or a loop state. The
state ids of a dependence tell which call of a function that several callers share produced it.
"""

import os
import re
from typing import Dict, Optional, Set, Tuple

# state id -> (parent state id, label)
CallpathTree = Dict[str, Tuple[str, str]]

_CALL_LABEL = re.compile(r"call_(\d+)$")


def read_callpath_tree(path: str) -> CallpathTree:
    """The callpath tree of the file; empty if it does not exist."""
    tree: CallpathTree = dict()
    if not os.path.exists(path):
        return tree
    with open(path, "r") as f:
        for line in f:
            fields = line.split()
            if len(fields) >= 3 and not fields[0].startswith("#"):
                tree[fields[0]] = (fields[1], fields[2])
    return tree


def call_instructions_of_state(tree: CallpathTree, state_id: Optional[str]) -> Optional[Set[int]]:
    """The ids of the call instructions on the callpath of the state, from the root to the state. None if the state is
    unknown (no state recorded, or not in the tree): the callpath cannot be told."""
    if state_id is None or state_id not in tree:
        return None
    calls: Set[int] = set()
    visited: Set[str] = set()
    current = state_id
    while current in tree and current not in visited:
        visited.add(current)
        parent, label = tree[current]
        match = _CALL_LABEL.match(label)
        if match:
            calls.add(int(match.group(1)))
        current = parent
    return calls
