# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Recursive task groups and where their parallel region belongs.

A task group in a function ``F`` that reaches itself (``x = fib(n - 1); y = fib(n - 2);``, directly or through other
functions, in the tasks or elsewhere in ``F``) must not open a parallel region in ``F``: it would be a nested region on
every level of the recursion. The region belongs around the call that enters the recursion from the outside, as in
omp-tasks (``#pragma omp parallel`` / ``#pragma omp single`` before ``res = fib(n);``); in ``F`` only the tasks and
their join remain. The calls that enter the recursion are the calls to ``F`` from functions that ``F`` does not reach.
"""

from typing import Dict, Iterable, List, Optional, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function


class CallStructure:
    """The calls of the program as the PET knows them (``node_calls`` of the CUs): which function calls which one, at
    which line, and which function a call instruction calls."""

    def __init__(self, pet: PEGraphX) -> None:
        self.callees: Dict[NodeID, Set[NodeID]] = dict()
        # (calling function, called function, "file id:line" of the call)
        self.calls: List[Tuple[NodeID, NodeID, str]] = []
        self.callee_of_instruction: Dict[int, NodeID] = dict()
        for cu in all_nodes(pet, CUNode):
            if not cu.node_calls:
                continue
            try:
                caller = get_parent_function(pet, cu).id
            except AssertionError:
                continue  # a CU that belongs to no function
            for call in cu.node_calls:
                if call["cuid"] not in pet.g:
                    continue
                callee = NodeID(call["cuid"])
                self.callees.setdefault(caller, set()).add(callee)
                self.calls.append((caller, callee, str(call["atLine"])))
                if call.get("callInstId") is not None:
                    self.callee_of_instruction[int(call["callInstId"])] = callee

    def reached_from(self, functions: Iterable[NodeID]) -> Set[NodeID]:
        """The functions that are called by the given ones, directly or not (the given ones only if they call
        themselves)."""
        reached: Set[NodeID] = set()
        pending = list(functions)
        while pending:
            for callee in self.callees.get(pending.pop(), ()):
                if callee not in reached:
                    reached.add(callee)
                    pending.append(callee)
        return reached

    def reached_by_instructions(self, instruction_ids: Iterable[int]) -> Set[NodeID]:
        """The functions the given instructions call, directly or not."""
        direct = {self.callee_of_instruction[i] for i in instruction_ids if i in self.callee_of_instruction}
        return direct | self.reached_from(direct)

    def entry_call_lines(self, function: Node, instruction_ids: Iterable[int]) -> Optional[List[str]]:
        """None if ``function`` is no recursion: neither the tasks with the given instructions nor anything else of it
        reaches it again. Otherwise the lines ("file id:line") of the calls to ``function`` from functions that
        ``function`` does not reach (the entries into the recursion), sorted; empty if there is none. A group in a
        recursive function counts even if its own tasks do not recurse: its region would be nested all the same."""
        if function.id not in self.reached_by_instructions(instruction_ids) | self.reached_from([function.id]):
            return None
        recursion = self.reached_from([function.id]) | {function.id}
        lines = {line for caller, callee, line in self.calls if callee == function.id and caller not in recursion}
        return sorted(lines, key=lambda line: tuple(int(part) for part in line.split(":")))
