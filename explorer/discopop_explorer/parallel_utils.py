# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Sequence, Set, Tuple, TypeVar

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_library.StatusReporting.console import progress

T = TypeVar("T")
R = TypeVar("R")


def gil_enabled() -> bool:
    """False on a free-threaded interpreter (python3.14t) whose GIL is off: only there threads run in parallel."""
    check = getattr(sys, "_is_gil_enabled", None)
    return True if check is None else bool(check())


def effective_workers(jobs: Optional[int]) -> int:
    """Number of threads to use for `jobs` (the --jobs option: None = as many as there are CPUs, 0 and 1 = serial).

    With the GIL, threads do not speed up the pure Python work of the explorer, so the work runs serially there."""
    if jobs is not None and jobs <= 1:
        return 1
    if gil_enabled():
        return 1
    return max(1, jobs if jobs is not None else (os.cpu_count() or 1))


def parallel_map(fn: Callable[[T], R], items: Sequence[T], workers: int, desc: str = "") -> List[R]:
    """[fn(item) for item in items], run on `workers` threads. The result is in the order of `items`, whatever the
    order in which the calls finish, and an exception of a call is raised here (the calls not started yet are
    cancelled). `fn` must not modify anything another call reads: the calls share all objects they are given.
    Progress is reported by the calling thread only."""
    if workers <= 1 or len(items) <= 1:
        return [fn(item) for item in progress(items, desc=desc)]
    executor = ThreadPoolExecutor(max_workers=min(workers, len(items)))
    try:
        return list(progress(executor.map(fn, items), total=len(items), desc=desc))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def pet_function_metadata_parse_func(pet: PEGraphX, func_node: FunctionNode) -> Tuple[NodeID, Any, Set[NodeID]]:
    """Children and reachability of one function. Reads the graph, writes only func_node.children_cu_ids, so calls
    for different functions can run at the same time."""
    stack: List[Node] = direct_children(pet, func_node)
    func_node.children_cu_ids = [node.id for node in stack]
    local_children: Set[NodeID] = set()

    while stack:
        child = stack.pop()
        local_children.add(child.id)
        children = direct_children(pet, child)
        func_node.children_cu_ids.extend([node.id for node in children])
        stack.extend(children)

    local_reachability_dict = func_node.calculate_reachability_pairs(pet)
    local_result = func_node.id, local_reachability_dict, local_children
    return local_result
