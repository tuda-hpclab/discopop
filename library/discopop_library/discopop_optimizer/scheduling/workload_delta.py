# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Tuple, cast, Any, Union, Optional

import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.ContextMerge import ContextMerge
from discopop_library.discopop_optimizer.classes.nodes.ContextRestore import ContextRestore
from discopop_library.discopop_optimizer.classes.nodes.ContextSave import ContextSave
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshot import ContextSnapshot
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshotPop import ContextSnapshotPop
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_children,
    get_successors,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


# define aliases for type checking purposes
class RegularCosts(Tuple[int, int]):
    pass


class BranchCosts(RegularCosts):
    pass


class WorkloadStack(object):
    stack: List[
        Any
    ]  # List[Union[List[Any], RegularCosts]]  # List of WorkloadStacks or integer tuples (min_wl, max_wl)

    def __init__(self) -> None:
        self.stack = []

    def enter_new_branched_section(self) -> None:
        """add a new list to the end of self.stack"""
        innermost_stack, _ = self.__get_innermost_workload_stack()
        innermost_stack.append([])

    def exit_branched_section(self) -> None:
        """aggregate the contained branches"""
        # do nothing, as the functionality is implemented in aggregate
        pass

    def enter_new_branch(self) -> None:
        """same behavior as enter_branched_section"""
        innermost_stack, _ = self.__get_innermost_workload_stack()
        innermost_stack.append([])

    def exit_branch(self) -> None:
        """Accumulates costs of the current branch, i.e. the innermost List"""
        # get innermost stack
        innermost_stack, indices = self.__get_innermost_workload_stack()
        # accumulate innermost stack
        min_wl = 0
        max_wl = 0
        for entry in innermost_stack:
            entry_min_wl, entry_max_wl = entry
            min_wl += entry_min_wl
            max_wl += entry_max_wl

        # replace innermost stack with BranchCosts element
        cur_elem = self.stack
        if len(indices) > 0:
            for index in indices[:-1]:
                cur_elem = cur_elem[index]
            cur_elem[indices[-1]] = BranchCosts((min_wl, max_wl))

    def aggregate(self) -> None:
        # get innermost stack
        innermost_stack, indices = self.__get_innermost_workload_stack()
        min_wl = 0
        max_wl = 0
        # sum up regular costs and save branch costs in a list for later accumulation
        branch_costs: List[BranchCosts] = []
        for entry in innermost_stack:
            if isinstance(entry, BranchCosts):
                branch_costs.append(entry)
            elif isinstance(entry, RegularCosts):
                min_wl += entry[0]
                max_wl += entry[1]
            else:
                raise ValueError("Unsupported element type: " + str(type(entry)))

        # accumulate branch costs (identify minimum and maximum possible costs)
        min_branch_wl: Optional[int] = None
        max_branch_wl: Optional[int] = None
        for costs in branch_costs:
            min_costs, max_costs = costs
            if min_branch_wl is None:
                min_branch_wl = min_costs
            if max_branch_wl is None:
                max_branch_wl = max_costs
            if min_branch_wl > min_costs:
                min_branch_wl = min_costs
            if max_branch_wl < max_costs:
                max_branch_wl = max_costs

        # accumulate total costs for branched section
        min_wl += 0 if min_branch_wl is None else min_branch_wl
        max_wl += 0 if max_branch_wl is None else max_branch_wl

        # replace innermost stack with accumulated costs
        cur_elem = self.stack
        if len(indices) > 0:
            for index in indices[:-1]:
                cur_elem = cur_elem[index]
            cur_elem[indices[-1]] = RegularCosts((min_wl, max_wl))

    def register_workload(self, min_wl: int, max_wl: int) -> None:
        # get the innermost workload stack
        innermost_stack, _ = self.__get_innermost_workload_stack()
        innermost_stack.append(RegularCosts((min_wl, max_wl)))

    def get_min_workload(self) -> int:
        """sum up minimal workloads in the stack"""
        min_wl_sum = 0
        for entry in self.stack:
            if not isinstance(entry, RegularCosts):
                raise ValueError("Unsupported element type: " + str(type(entry)))
            min_wl_sum += entry[0]
        return min_wl_sum

    def get_max_workload(self) -> int:
        """sum up maximal workloads in the stack"""
        max_wl_sum = 0
        for entry in self.stack:
            if not isinstance(entry, RegularCosts):
                raise ValueError("Unsupported element type: " + str(type(entry)))
            max_wl_sum += entry[1]
        return max_wl_sum

    def __get_innermost_workload_stack(self) -> Tuple[List[Any], List[int]]:
        """identifies and returns a reference to the currently active (innermost) workload stack stored in self.stack,
        as well as the list of indices to access this element"""
        indices: List[int] = []
        innermost_stack = self.stack
        while True:
            if len(innermost_stack) == 0:
                break
            if isinstance(innermost_stack[-1], list):
                # save index
                indices.append(len(innermost_stack) - 1)
                # enter the last entry of the currently visited stack and proceed wit the search
                innermost_stack = cast(Any, innermost_stack[-1])

            else:
                # registered workload (tuple of integers) found
                break
        return innermost_stack, indices

    def __get_parent_of_innermost_stack(self) -> Optional[List[Any]]:
        """identifies and returns a reference to the parent List of the innermost workload stack"""
        parents: List[Optional[List[Any]]] = [None]
        innermost_stack = self.stack
        while True:
            if len(innermost_stack) == 0:
                break
            if isinstance(innermost_stack[-1], list):
                # update the parent before entering a new entry
                parents.append(innermost_stack)
                # enter the last entry of the currently visited stack and proceed wit the search
                innermost_stack = innermost_stack[-1]
            else:
                # registered workload (tuple of integers) found
                break
        return parents[-1]


def get_workload_delta_for_cu_node(experiment: Experiment, node_id: int) -> Tuple[int, int, int]:
    """Estimates the expected deviation between different branches in the given node and returns the resulting delta
    as well as the total min / max workloads.
    Unit: same as workload"""
    # get specified node and get delta_wl from specified node
    workload_stack = __parse_node(experiment, node_id, WorkloadStack())
    cu_max_wl = workload_stack.get_max_workload()
    cu_min_wl = workload_stack.get_min_workload()
    delta_workload = workload_stack.get_max_workload() - workload_stack.get_min_workload()

    return delta_workload, cu_min_wl, cu_max_wl


def __parse_node(
    experiment: Experiment,
    node_id: int,
    workload_stack: WorkloadStack,
    ignore_successors: bool = False,
    iteration_factor: int = 1,
) -> WorkloadStack:
    """Calculates the min / max workload and returns them plus the updated WorkloadStack"""
    node_data = data_at(experiment.optimization_graph, node_id)

    min_wl, max_wl = 0, 0
    last_visited_node_id = node_id

    # modify the workload_stack if necessary
    #  ContextSnapshot --> enter recursion
    #  ContextRestore --> start enter new branch
    #  ContextSave --> end of branch
    #  ContextMerge --> end of branched section, calculate min / max (aggregate)
    #  ContextSnapshotPop -> exit recursion
    if type(node_data) == ContextSnapshot:
        workload_stack.enter_new_branched_section()
    elif type(node_data) == ContextRestore:
        workload_stack.enter_new_branch()
    elif type(node_data) == ContextSave:
        workload_stack.exit_branch()
    elif type(node_data) == ContextMerge:
        workload_stack.aggregate()
    elif type(node_data) == ContextSnapshotPop:
        workload_stack.exit_branched_section()

    # calculate the workload of the current node and register it in the stack
    #  add workload of the current node to min / max
    if isinstance(node_data, Workload):
        min_wl = (node_data.sequential_workload or 0) + (node_data.parallelizable_workload or 0)
        max_wl = min_wl
        # apply iteration factor if requested
        min_wl *= iteration_factor
        max_wl *= iteration_factor
        workload_stack.register_workload(min_wl, max_wl)

    # register children
    if type(node_data) == Loop:
        iteration_factor = node_data.iterations
    else:
        iteration_factor = 1
    for child_id in get_children(experiment.optimization_graph, node_id):
        workload_stack = __parse_node(experiment, child_id, workload_stack, iteration_factor=iteration_factor)

    # set next node
    successors = get_successors(experiment.optimization_graph, node_id)

    # continue calculation with successor of node
    # at this point in the OPT Graphs lifecycle, successors can either be empty or have exactly one entry
    if len(successors) == 0:
        # return if none exists
        return workload_stack

    # get min and max workload for successor
    if not ignore_successors:
        workload_stack = __parse_node(experiment, successors[0], workload_stack)

    return workload_stack
