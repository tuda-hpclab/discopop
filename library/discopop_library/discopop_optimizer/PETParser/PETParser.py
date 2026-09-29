# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import logging
import os
import pstats
from typing import Dict, List, Optional, Tuple, Set, cast

import networkx as nx  # type: ignore
import warnings

from sympy import Integer  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.utils import calculate_workload
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.discopop_optimizer.PETParser.DataAccesses.FromCUs import (
    get_data_accesses_for_cu,
)
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.edges.SuccessorEdge import SuccessorEdge
from discopop_library.discopop_optimizer.classes.nodes.ContextMerge import ContextMerge
from discopop_library.discopop_optimizer.classes.nodes.ContextRestore import ContextRestore
from discopop_library.discopop_optimizer.classes.nodes.ContextSave import ContextSave
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshot import ContextSnapshot
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshotPop import ContextSnapshotPop
from discopop_library.discopop_optimizer.classes.nodes.FunctionReturn import FunctionReturn
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.classes.types.DataAccessType import ReadDataAccess, WriteDataAccess
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    add_call_edge,
    add_dataflow_edge,
    get_all_nodes_in_function,
    get_all_parents,
    get_nodes_by_functions,
    get_out_call_edges,
    get_path_entry,
    get_predecessors,
    get_successors,
    get_children,
    add_successor_edge,
    add_child_edge,
    add_temporary_edge,
    redirect_edge,
    convert_temporary_edges,
    get_all_function_nodes,
    get_read_and_written_data_from_subgraph,
    remove_edge,
    show_function,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from time import time

logger = logging.getLogger("Optimizer")


class PETParser(object):
    pet: PEGraphX
    graph: nx.DiGraph
    next_free_node_id: int
    cu_id_to_graph_node_id: Dict[NodeID, int]
    experiment: Experiment
    in_data_flow: Dict[int, Set[int]]
    out_data_flow: Dict[int, Set[int]]
    invalid_functions: Set[int]

    def __init__(self, experiment: Experiment):
        self.pet = experiment.detection_result.pet
        self.graph = nx.DiGraph()
        self.next_free_node_id = 0
        self.cu_id_to_graph_node_id = dict()
        self.experiment = experiment
        self.invalid_functions = set()

    def parse(self) -> Tuple[nx.DiGraph, int]:
        if self.experiment.arguments.verbose:
            print("PARSING PET")
        self.__add_cu_nodes()
        if self.experiment.arguments.verbose:
            print("added cu nodes")
        self.__add_functions()
        if self.experiment.arguments.verbose:
            print("added functions")
        self.__add_pet_successor_edges()
        if self.experiment.arguments.verbose:
            print("added successor edges")
        self.__add_loop_nodes()
        if self.experiment.arguments.verbose:
            print("added loop nodes")

        if self.experiment.arguments.verbose:
            print("remove non-hotspot function bodys")
        self.__remove_non_hotspot_function_bodys()

        # self.__add_branch_return_node()

        # self.__new_parse_branched_sections()

        if self.experiment.arguments.verbose:
            print("pruning graphs based on taken branches. Pruning level: ", self.experiment.arguments.pruning_level)
        self.__prune_branches()
        if self.experiment.arguments.verbose:
            print("\tDone.")

        self.__flatten_function_graphs()

        # remove invalid functions
        self.__remove_invalid_functions()

        convert_temporary_edges(self.graph)
        if self.experiment.arguments.verbose:
            print("converted temporary edges")

        if self.experiment.arguments.verbose:
            print("Propagating read/write information...")
        self.__propagate_reads_and_writes()
        if self.experiment.arguments.verbose:
            print("Propagated read/write information")

        #        self.__mark_branch_affiliation()
        #        print("marked branch affiliations")
        #        show(self.graph)
        # self.__calculate_data_flow()
        # self.__new_calculate_data_flow()
        #        if self.experiment.arguments.verbose:
        #            print("calculated data flow")
        # show(self.graph)
        # import sys
        # sys.exit(0)

        # remove invalid functions
        self.__remove_invalid_functions()

        # add function return node
        self.__add_function_return_node()

        # add calling edges
        self.__add_calling_edges()

        logger.info("Inlining read and write information from function calls..")
        # note: inlining at this position is a cheap but less reliable alternative to propagating everythin on function calls.
        # note: full propagation leads to issues with WriteDataAccess unique ids and potentially broken results
        self.__inline_reads_and_writes_from_call()
        logger.info("Inlining read and write information from function calls done.")

        if self.experiment.arguments.pin_function_calls_to_host:
            self.__pin_function_calls_to_host()

        return self.graph, self.next_free_node_id

    def get_new_node_id(self) -> int:
        """returns the next free node id and increments the counter"""
        buffer = self.next_free_node_id
        self.next_free_node_id += 1
        return buffer

    def __pin_function_calls_to_host(self) -> None:
        host_device_id = self.experiment.get_system().get_host_device_id()
        logger.info("Pinning functions and function calls to host device: " + str(host_device_id))
        for node in get_all_function_nodes(self.graph):
            node_data = data_at(self.graph, node)
            if node_data.device_id != host_device_id:
                logger.info("\tPinning function node: " + str(node))
                data_at(self.graph, node).device_id = host_device_id
        for node in self.graph.nodes:
            node_data = data_at(self.graph, node)
            if node_data.device_id != host_device_id:
                if len(get_out_call_edges(self.graph, node)) > 0:
                    logger.info("\tPinning calling node: " + str(node))
                    data_at(self.graph, node).device_id = host_device_id

    def __add_calling_edges(self) -> None:
        all_function_nodes = get_all_function_nodes(self.graph)

        for node in self.graph.nodes:
            node_data = data_at(self.graph, node)
            if type(node_data) != Workload:
                continue
            # get functions called by the node
            if node_data.original_cu_id is None:
                raise ValueError("Node: " + str(node) + " has no original_cu_id")
            for out_call_edge in out_edges(
                self.experiment.detection_result.pet, node_data.original_cu_id, etype=EdgeType.CALLSNODE
            ):
                # create a call edge to the function
                for function in all_function_nodes:
                    if data_at(self.graph, function).original_cu_id == out_call_edge[1]:
                        add_call_edge(self.graph, node, function)

    def __prune_branches(self) -> None:
        """Prune branches based on the measured likelihood of execution"""
        # check if branch information exists. If not, skip this step.
        if self.experiment.arguments.pruning_level == 0:
            if self.experiment.arguments.verbose:
                print("\tPruning level 0. Skipping.")
            return
        if not os.path.exists("profiler/cu_taken_branch_counter_output.txt"):
            if self.experiment.arguments.verbose:
                print("\tNo information on taken branches found. Skipping.")
            return
        # load observed branching information
        branch_counter_dict: Dict[str, Dict[str, int]] = dict()
        with open("profiler/cu_taken_branch_counter_output.txt", "r") as f:
            for line in f.readlines():
                line = line.replace("\n", "")
                split_line = line.split(";")
                source_cu_id = split_line[0]
                target_cu_id = split_line[1]
                counter = int(split_line[2])
                if source_cu_id not in branch_counter_dict:
                    branch_counter_dict[source_cu_id] = dict()
                branch_counter_dict[source_cu_id][target_cu_id] = counter
        print("Branch counter dict: ")
        print(branch_counter_dict)

        # convert counters to likelihood
        branch_likelihood_dict: Dict[str, Dict[str, float]] = dict()
        for source_cu_id in branch_counter_dict:
            total_counter = 0
            for target_cu_id in branch_counter_dict[source_cu_id]:
                total_counter += branch_counter_dict[source_cu_id][target_cu_id]
            branch_likelihood_dict[source_cu_id] = dict()
            for target_cu_id in branch_counter_dict[source_cu_id]:
                branch_likelihood_dict[source_cu_id][target_cu_id] = (
                    branch_counter_dict[source_cu_id][target_cu_id] / total_counter
                )

        print("Branch likelihood dict:")
        print(branch_likelihood_dict)

        # fix branch likelihood, necessary due to different structure of BB vs. Optimization graph

        for function in get_all_function_nodes(self.graph):
            print("pruning function: ", cast(FunctionRoot, data_at(self.graph, function)).name)
            verbose_print_pruning_statistics = False
            if self.experiment.arguments.verbose:
                ct = 0
                for node in get_all_nodes_in_function(self.graph, function):
                    if len(get_successors(self.graph, node)) > 1:
                        ct += 1
                if ct > 0:
                    verbose_print_pruning_statistics = True
                    print("\tpath splits before pruning: ", ct)
            # calculate node likelihoods
            node_likelihood_dict: Dict[int, float] = dict()
            # initialize
            queue: List[int] = []
            for node in get_all_nodes_in_function(self.graph, function):
                if len(get_predecessors(self.graph, node)) == 0:
                    node_likelihood_dict[node] = 1
                queue.append(node)
            # calculate node likelihoods by traversing the graph
            while len(queue) > 0:
                current_node = queue.pop(0)  # BFS
                if current_node in node_likelihood_dict:
                    continue
                predecessors = get_predecessors(self.graph, current_node)
                # if node likelihoods for all predecessors exist, calculate the likelihood for current_node
                valid_target = True
                for pred in predecessors:
                    if pred not in node_likelihood_dict:
                        valid_target = False
                        # add the missing predecessor to the queue
                        if pred not in queue:
                            queue.append(pred)
                        break
                if valid_target:
                    current_node_cu_id = data_at(self.graph, current_node).original_cu_id
                    # calculate likelihood for current_node
                    likelihood = 0.0
                    for pred in predecessors:
                        pred_cu_id = data_at(self.graph, pred).original_cu_id
                        edge_likelihood = 1.0  # fallback if no data exists or not a branching point
                        if len(get_successors(self.graph, pred)) > 1:
                            if pred_cu_id in branch_likelihood_dict:
                                if current_node_cu_id in branch_likelihood_dict[pred_cu_id]:
                                    edge_likelihood = branch_likelihood_dict[pred_cu_id][current_node_cu_id]
                                else:
                                    # branch was not executed
                                    edge_likelihood = 0

                        likelihood += node_likelihood_dict[pred] * edge_likelihood
                    node_likelihood_dict[current_node] = likelihood

                    # add successors to queue
                    queue += [s for s in get_successors(self.graph, current_node) if s not in queue]

                else:
                    # add current_node to the queue for another try
                    queue.append(current_node)

            keep_nodes: List[int] = []
            if self.experiment.arguments.pruning_level == 1:
                # calculate branches which are executed in 80% of the observed cases
                keep_nodes = self.__identify_most_likely_paths_80_percent_cutoff(branch_likelihood_dict, function)
            elif self.experiment.arguments.pruning_level == 2:
                # calculate best branches using upwards search using branch and node likelihoods
                keep_nodes = self.__identify_most_likely_path(node_likelihood_dict, function)
            else:
                raise ValueError("Unknown pruning level: ", self.experiment.arguments.pruning_level)

            # prune the graph
            function_nodes = get_all_nodes_in_function(self.graph, function)
            to_be_removed: List[int] = [n for n in function_nodes if n not in keep_nodes]
            for n in to_be_removed:
                self.graph.remove_node(n)

            if self.experiment.arguments.verbose and verbose_print_pruning_statistics:
                ct = 0
                for node in get_all_nodes_in_function(self.graph, function):
                    if len(get_successors(self.graph, node)) > 1:
                        ct += 1
                print("\tpath splits after pruning: ", ct)

    def __identify_most_likely_paths_80_percent_cutoff(
        self, branch_likelihood_dict: Dict[str, Dict[str, float]], function: int
    ) -> List[int]:
        """Traverse graph downwards and return a list of the nodes visited if all branches were taken that constitute a sum of at least 80% of the observed cases."""
        keep_nodes: List[int] = []
        queue: List[int] = []
        # get path entries points
        for node in get_all_nodes_in_function(self.graph, function):
            if len(get_predecessors(self.graph, node)) == 0:
                queue.append(node)

        while len(queue) > 0:
            current = queue.pop()
            current_cu_id = data_at(self.graph, current).original_cu_id
            keep_nodes.append(current)

            # get successors and their cu ids
            successors = get_successors(self.graph, current)
            if len(successors) < 2:
                queue += [s for s in successors if s not in queue and s not in keep_nodes]
                continue
            successor_cus = [(s, data_at(self.graph, s).original_cu_id) for s in successors]

            # get likelihoods for transitions to successors
            if current_cu_id not in branch_likelihood_dict:
                warnings.warn(
                    "No branch counters available for path split at CU Node: "
                    + str(current_cu_id)
                    + ". Fallback: Preserving all successors."
                )
                # fallback: preserve all successors
                queue += [s for s in successors if s not in queue and s not in keep_nodes]
                continue
            else:
                successor_likelihood = []
                for succ, succ_cu_id in successor_cus:
                    if succ_cu_id not in branch_likelihood_dict[current_cu_id]:
                        successor_likelihood.append((succ, succ_cu_id, 0.0))
                    else:
                        successor_likelihood.append(
                            (succ, succ_cu_id, branch_likelihood_dict[current_cu_id][succ_cu_id])
                        )

                # select successors until total probability is > THRESHOLD
                threshold = 0.8
                total_probability = 0.0
                for succ, succ_cu_id, succ_prob in sorted(successor_likelihood, reverse=True, key=lambda x: x[2]):
                    if total_probability < threshold:
                        queue.append(succ)
                        total_probability += succ_prob
                    else:
                        break

        return keep_nodes

    def __identify_most_likely_path(self, node_likelihood_dict: Dict[int, float], function: int) -> List[int]:
        """Traverse graph upwards and return a list of the most likely nodes which constitute the most likely execution path."""
        keep_nodes: List[int] = []
        queue: List[int] = []
        # get path end points
        for node in get_all_nodes_in_function(self.graph, function):
            if len(get_successors(self.graph, node)) == 0:
                queue.append(node)

        while len(queue) > 0:
            current = queue.pop()
            keep_nodes.append(current)
            # identify most likely predecessor
            predecessor_likelihoods: List[Tuple[int, float]] = []
            for pred in get_predecessors(self.graph, current):
                predecessor_likelihoods.append((pred, node_likelihood_dict[pred]))
            if len(predecessor_likelihoods) == 0:
                # path entry reached
                continue
            most_likely_predecessor = sorted(predecessor_likelihoods, reverse=True, key=lambda x: x[1])[0][0]
            # add most likely predecessor to the queue and thus keep_nodes
            queue.append(most_likely_predecessor)

        return keep_nodes

    def __flatten_function_graphs(self) -> None:
        # TODO: remove deepcopies by storing data independently from the nodes

        for function in get_all_function_nodes(self.graph):
            function_node = cast(FunctionRoot, data_at(self.graph, function))
            print("Flattening function:", function_node.original_cu_id, function_node.name)
            # prepare individual branches by replacing nodes with more than one predecessor
            # effectively, this leads to a full duplication of all possible branches

            modification_found = True
            dbg_show = False
            timeout = 30
            try:
                start_time = int(time())
                print("\tfixing predecessors")
                queue = get_all_nodes_in_function(self.graph, function)
                while modification_found:
                    modification_found = False
                    iteration_time = int(time())
                    if iteration_time - start_time > timeout:
                        # show_function(self.graph, function_node, show_dataflow=False, show_mutex_edges=False)

                        ## dbg show profiling data
                        if self.experiment.arguments.profiling and self.experiment.profile is not None:
                            self.experiment.profile.disable()
                            if os.path.exists("optimizer_profile.txt"):
                                os.remove("optimizer_profile.txt")
                            with open("optimizer_profile.txt", "w+") as f:
                                stats = (
                                    pstats.Stats(self.experiment.profile, stream=f).sort_stats("time").reverse_order()
                                )
                                stats.print_stats()
                        raise TimeoutError("Timeout expired.")

                    # for node in get_all_nodes_in_function(self.graph, function):
                    while len(queue) > 0:
                        node = queue.pop(0)
                        if node not in self.graph.nodes:
                            continue
                        if len(get_predecessors(self.graph, node)) > 1:
                            modification_found, modified_nodes = self.__fix_too_many_predecessors(node)
                            # queue += [n for n in modified_nodes if n not in queue]
                            queue += modified_nodes
                            if modification_found:
                                dbg_show = True
                                break
                #            if dbg_show:
                #                show_function(self.graph, function_node, show_dataflow=False, show_mutex_edges=False)

                # combine branches by adding context nodes
                # effectively, this step creates a single, long branch from the functions body
                modification_found = True
                dbg_show = False
                print("\tfixing successors")
                start_time = int(time())
                while modification_found:
                    modification_found = False
                    iteration_time = int(time())
                    if iteration_time - start_time > timeout:
                        ## dbg show profiling data
                        if self.experiment.arguments.profiling and self.experiment.profile is not None:
                            self.experiment.profile.disable()
                            if os.path.exists("optimizer_profile.txt"):
                                os.remove("optimizer_profile.txt")
                            with open("optimizer_profile.txt", "w+") as f:
                                stats = (
                                    pstats.Stats(self.experiment.profile, stream=f).sort_stats("time").reverse_order()
                                )
                                stats.print_stats()
                        raise TimeoutError("Timeout expired.")

                    for node in get_all_nodes_in_function(self.graph, function):
                        if len(get_successors(self.graph, node)) > 1:
                            modification_found = self.__fix_too_many_successors(node, dbg_function_node=function_node)
                            if modification_found:
                                dbg_show = True
                                break
            #            if dbg_show:
            #                show_function(self.graph, function_node, show_dataflow=False, show_mutex_edges=False)

            except TimeoutError:
                print("\tTimeout after: ", timeout, "s")
                self.invalid_functions.add(function)

    def __fix_too_many_successors(self, node: int, dbg_function_node: Optional[FunctionRoot] = None) -> bool:
        """Return True if a graph modification has been applied. False otherwise."""
        retval = False

        # check if a node with more than one successor is located on any of the branches starting at node
        # if so, this node is not suited for the application of a fix.
        # Effectively, this leads to a bottom-up branch combination.
        succeeding_branches: List[Tuple[int, int]] = []  # (branch_entry, branch_exit)
        for succ in get_successors(self.graph, node):
            # traverse succeeding branches to check for contained path splits
            queue = [succ]
            branch_end = None
            while len(queue) > 0:
                current = queue.pop()
                successors = get_successors(self.graph, current)
                if len(successors) > 1:
                    # node not suited for fix application
                    return False
                if len(successors) == 0:
                    branch_end = current
                queue += [s for s in successors if s not in queue]
            # end of branch reached without encountering a path split.
            assert branch_end  # != None
            succeeding_branches.append((succ, branch_end))

        # none of the succeeding paths contained a path split.
        # --> node qualifies for the application of a fix

        # create context snapshot
        context_snapshot_id = self.get_new_node_id()
        self.graph.add_node(context_snapshot_id, data=ContextSnapshot(context_snapshot_id, self.experiment))
        add_successor_edge(self.graph, node, context_snapshot_id)

        # create and connect create merge node and snapshot pop node
        context_merge_node_id = self.get_new_node_id()
        self.graph.add_node(context_merge_node_id, data=ContextMerge(context_merge_node_id, self.experiment))
        context_snapshot_pop_node_id = self.get_new_node_id()
        self.graph.add_node(
            context_snapshot_pop_node_id, data=ContextSnapshotPop(context_snapshot_pop_node_id, self.experiment)
        )
        add_successor_edge(self.graph, context_merge_node_id, context_snapshot_pop_node_id)

        # separate branches from node
        for branch_entry, branch_exit in succeeding_branches:
            remove_edge(self.graph, node, branch_entry)

        # linearize branches
        combined_branch_entry = None
        combined_branch_exit = None
        for branch_entry, branch_exit in succeeding_branches:
            # create and prepend context restore node to branch
            context_restore_id = self.get_new_node_id()
            self.graph.add_node(
                context_restore_id,
                data=ContextRestore(context_restore_id, self.experiment),
            )
            add_successor_edge(self.graph, context_restore_id, branch_entry)

            # append context save node to the branch
            context_save_id = self.get_new_node_id()
            self.graph.add_node(context_save_id, data=ContextSave(context_save_id, self.experiment))
            add_successor_edge(self.graph, branch_exit, context_save_id)

            # concatenate the branch to the prior branch
            if combined_branch_entry is None:
                combined_branch_entry = context_restore_id
                if combined_branch_exit is None:
                    combined_branch_exit = context_save_id
                    # initialization with first branch completed
                    continue
            if combined_branch_exit is None:
                raise ValueError("combined_branch_exit must not be None")
            add_successor_edge(self.graph, combined_branch_exit, context_restore_id)

            # update combined_branch_exit
            combined_branch_exit = context_save_id

        # connect linearized branch with merge and snapshot pop
        add_successor_edge(self.graph, cast(int, combined_branch_exit), context_merge_node_id)
        combined_branch_exit = context_snapshot_pop_node_id

        # connect context snapshot with combined_branch_entry
        add_successor_edge(self.graph, context_snapshot_id, cast(int, combined_branch_entry))

        retval = True
        return retval

    def __fix_too_many_predecessors(self, node: int) -> Tuple[bool, List[int]]:
        """Return True if a graph modification has been applied. False otherwise."""
        retval = False
        modified_nodes: List[int] = []

        # check if node is a good candidate (i.e. one that is not succeeded by a path merge)

        queue = get_successors(self.graph, node)
        while len(queue) > 0:
            current = queue.pop()
            if len(get_predecessors(self.graph, current)) > 1:
                # at least one successor branch of node contains a path merge. hence, node is not a good candidate.
                return False, [node]
            queue += [s for s in get_successors(self.graph, current) if s not in queue]

        # node is a good candidate. Apply the transformation.
        for pred in get_predecessors(self.graph, node):
            new_node_id = self.get_new_node_id()
            node_copy_data = copy.deepcopy(data_at(self.graph, node))
            node_copy_data.node_id = new_node_id
            node_copy = self.graph.add_node(new_node_id, data=node_copy_data)
            modified_nodes.append(new_node_id)
            # copy non-successors type incoming edges
            for in_edge in self.graph.in_edges(node, data="data"):
                if type(in_edge[2]) == SuccessorEdge:
                    continue
                edge_type = type(in_edge[2])
                self.graph.add_edge(in_edge[0], new_node_id, data=edge_type())
                modified_nodes.append(in_edge[0])
            # connect copied node to pred
            self.graph.add_edge(pred, new_node_id, data=SuccessorEdge())
            modified_nodes.append(pred)

            # copy outgoing edges
            for out_edge in self.graph.out_edges(node, data="data"):
                edge_type = type(out_edge[2])
                self.graph.add_edge(new_node_id, out_edge[1], data=edge_type())
                modified_nodes.append(out_edge[1])

        # delete node
        self.graph.remove_node(node)

        retval = True
        return retval, list(dict.fromkeys(modified_nodes))

    def __remove_non_hotspot_function_bodys(self) -> None:
        if len(self.experiment.hotspot_functions) == 0:
            return
        all_hotspot_functions_raw: List[Tuple[int, str]] = []
        for key in self.experiment.hotspot_functions:
            for file_id, line_num, hs_node_type, name, _ in self.experiment.hotspot_functions[key]:
                if hs_node_type == HotspotNodeType.FUNCTION:
                    all_hotspot_functions_raw.append((file_id, name))

        # convert raw information to node ids
        for file_id, name in all_hotspot_functions_raw:
            for function in get_all_function_nodes(self.graph):
                function_node = cast(FunctionRoot, data_at(self.graph, function))
                if function_node is None:
                    continue
                if function_node.original_cu_id is None:
                    continue
                if int(function_node.original_cu_id.split(":")[0]) == file_id:
                    print("FID EQUAL")
                    print("CHECK NAME: ", function_node.name, name)
                    if function_node.name == name:
                        print("NAME EQQUAL")
                        self.experiment.hotspot_function_node_ids.append(function)

        print("HOTPSOT FUNCTIONS: ")
        print(self.experiment.hotspot_function_node_ids)

        for function in get_all_function_nodes(self.graph):
            if (
                function not in self.experiment.hotspot_function_node_ids
                and len(self.experiment.hotspot_function_node_ids) > 0
            ):
                print("DELETING FUNCTION BODY: ", cast(FunctionRoot, data_at(self.graph, function)).name)
                # remove function body
                for node in get_all_nodes_in_function(self.graph, function):
                    self.graph.remove_node(node)
                # leave the function node

    def __remove_invalid_functions(self) -> None:
        for function in self.invalid_functions:
            if self.experiment.arguments.verbose:
                print("Removing body of invalid function: ", cast(FunctionRoot, data_at(self.graph, function)).name)
            # delete all nodes in function body
            for node in get_all_nodes_in_function(self.graph, function):
                self.graph.remove_node(node)
            # leave the function node for compatibility reasons

    #    def __add_function_return_node(self):
    #        function_node_ids = get_all_function_nodes(self.graph)
    #        dummy_return_nodes: Set[int] = set()
    #        function_return_nodes: Dict[int, int] = dict()
    #        for function in function_node_ids:
    #            return_dummy_id = self.get_new_node_id()
    #            self.graph.add_node(return_dummy_id, data=Workload(return_dummy_id, None, None, None, None))
    #            function_return_nodes[function] = return_dummy_id
    #            dummy_return_nodes.add(return_dummy_id)
    #
    #        for node in self.graph.nodes():
    #            if node in dummy_return_nodes:
    #                continue
    #            if len(get_successors(self.graph, node)) == 0:
    #                # node is end of path
    #                # check if node is contained in function
    #                parent_functions = [e for e in get_all_parents(self.graph, node) if e in function_node_ids]
    #                if len(parent_functions) > 0:
    #                    for parent_func in parent_functions:
    #                        # connect end of path to the dummy return node
    #                        add_successor_edge(self.graph, node, function_return_nodes[parent_func])
    #
    #    #                        if self.experiment.arguments.verbose:
    #    #                            print("ADDED DUMMY CONNECTION: ", node, function_return_nodes[parent_func])

    def __add_function_return_node(self) -> None:
        """Add a return node to each function as a location to force data updates"""
        for function in get_all_function_nodes(self.graph):
            queue = get_children(self.graph, function)
            while len(queue) > 0:
                current = queue.pop()
                successors = get_successors(self.graph, current)
                if len(successors) == 0:
                    # get last original_cu_id
                    inner_queue = [current]
                    last_original_cu_id = None
                    while len(inner_queue) > 0:
                        inner_current = inner_queue.pop()
                        inner_current_data = data_at(self.graph, inner_current)
                        if inner_current_data.original_cu_id != None:
                            last_original_cu_id = inner_current_data.original_cu_id
                            break
                        else:
                            inner_queue += [
                                p for p in get_predecessors(self.graph, inner_current) if p not in inner_queue
                            ]
                    if last_original_cu_id is None:
                        # fallback
                        last_original_cu_id = data_at(self.graph, function).original_cu_id

                    # create a functionReturn node
                    new_node_id = self.get_new_node_id()
                    new_node_data = FunctionReturn(new_node_id, self.experiment)
                    # copy original_cu_id from current for update positiong during code generation
                    new_node_data.original_cu_id = last_original_cu_id
                    self.graph.add_node(new_node_id, data=new_node_data)
                    add_successor_edge(self.graph, current, new_node_id)
                else:
                    queue += [s for s in successors if s not in queue]

    def __add_branch_return_node(self) -> None:
        """makes sure every branching section has a merge node"""
        path_return_nodes: Dict[List[int], int] = dict()

        for node in copy.deepcopy(self.graph.nodes()):
            if len(get_successors(self.graph, node)) == 0:
                path_entry = get_path_entry(self.graph, node)
                if path_entry not in path_return_nodes:
                    # create new dummy return node
                    dummy_return_node_id = self.get_new_node_id()
                    self.graph.add_node(
                        dummy_return_node_id, data=Workload(dummy_return_node_id, self.experiment, None, None, None)
                    )
                    path_return_nodes[path_entry] = dummy_return_node_id
                # connect to existing return node
                add_successor_edge(self.graph, node, path_return_nodes[path_entry])
                print("ADDED EDGE: ", node, "->", path_return_nodes[path_entry])

    def __new_parse_branched_sections(self) -> None:
        """Branched sections in the CU Graph are represented by a serialized version in the MOG.
        To make this possible, Context Snapshot, Restore and Merge points are added to allow a synchronization
        'between' the different branches"""

        all_functions = get_all_function_nodes(self.graph)
        nodes_by_functions = get_nodes_by_functions(self.graph)
        for idx, function in enumerate(all_functions):
            if (
                function not in self.experiment.hotspot_function_node_ids
                and len(self.experiment.hotspot_function_node_ids) > 0
            ):
                if cast(FunctionRoot, data_at(self.graph, function)).name == "main":
                    print("SKIPPING NON HOTSPOT FUNCTION: ", cast(FunctionRoot, data_at(self.graph, function)).name)
                continue
            # try:
            if self.experiment.arguments.verbose:
                if cast(FunctionRoot, data_at(self.graph, function)).name == "main":
                    print(
                        "FUNCTION: ",
                        cast(FunctionRoot, data_at(self.graph, function)).name,
                        idx,
                        "/",
                        len(all_functions),
                    )
            nodes_in_function = nodes_by_functions[function]

            post_dominators = self.__get_post_dominators(nodes_in_function)

            path_splits = self.__get_path_splits(nodes_in_function)
            merge_nodes = self.__get_merge_nodes(path_splits, post_dominators)

            if cast(FunctionRoot, data_at(self.graph, function)).name == "main":
                print("showing..")
                show_function(
                    self.graph,
                    cast(FunctionRoot, data_at(self.graph, function)),
                    show_dataflow=False,
                    show_mutex_edges=False,
                )

            added_node_ids = self.__fix_empty_branches(merge_nodes, post_dominators)

            if cast(FunctionRoot, data_at(self.graph, function)).name == "main":
                print("showing..")
                show_function(
                    self.graph,
                    cast(FunctionRoot, data_at(self.graph, function)),
                    show_dataflow=False,
                    show_mutex_edges=False,
                )
            nodes_in_function = list(dict.fromkeys(list(nodes_in_function) + list(added_node_ids)))

            # re-calculate post_dominators and merge nodes
            #            post_dominators = self.__get_post_dominators(nodes_in_function)
            #            path_splits = self.__get_path_splits(nodes_in_function)
            #            merge_nodes = self.__get_merge_nodes(path_splits, post_dominators)

            self.__insert_context_nodes(nodes_in_function)
            if cast(FunctionRoot, data_at(self.graph, function)).name == "main":
                print("showing..")
                show_function(
                    self.graph,
                    cast(FunctionRoot, data_at(self.graph, function)),
                    show_dataflow=False,
                    show_mutex_edges=False,
                )

                # sanity check
            #                fix_applied = True
            #                while fix_applied:
            #                    fix_applied = False
            #                    for node in get_all_nodes_in_function(self.graph, function):
            #                        if len(get_predecessors(self.graph, node)) > 1:
            #                            warnings.warn("SANITY CHECK FAILED FOR NODE " +  str(node) + " . Removing random edge to try an fix the problem.")
            #                            remove_edge(self.graph, get_predecessors(self.graph, node)[0], node)
            #                            fix_applied = True
            #                            break
            # except ValueError:
            #    if self.experiment.arguments.verbose:
            #        print("NPBS: Function",  data_at(self.graph, function).name ,"invalid due to graph construction issues. Skipping.")
            #    self.invalid_functions.add(function)

    def __fix_empty_branches(
        self, merge_nodes: Dict[int, Optional[int]], post_dominators: Dict[int, Set[int]]
    ) -> List[int]:
        """do not allow empty branches. Adds an empty dummy node if necessary"""
        empty_branches: Set[Tuple[int, int]] = set()
        for split_node in merge_nodes:
            if merge_nodes[split_node] is None:
                raise ValueError("No branching without merge allowed!")
            for branch_entry in get_successors(self.graph, split_node):
                for branch_exit in get_predecessors(self.graph, cast(int, merge_nodes[split_node])):
                    if branch_exit == split_node and branch_entry == merge_nodes[split_node]:
                        empty_branches.add((branch_exit, branch_entry))

        added_node_ids: List[int] = []
        for entry, exit in empty_branches:
            dummy_node_id = self.get_new_node_id()
            self.graph.add_node(dummy_node_id, data=Workload(dummy_node_id, self.experiment, None, None, None))
            #            if self.experiment.arguments.verbose:
            #                print("Added dummy node: ", entry, "->", dummy_node_id, "->", exit)
            redirect_edge(self.graph, entry, entry, exit, dummy_node_id)
            add_successor_edge(self.graph, dummy_node_id, exit)
            added_node_ids.append(dummy_node_id)
        return added_node_ids

    def __insert_context_nodes(self, node_list: List[int]) -> None:
        """flattens the graph via inserting context nodes"""
        modification_found = True
        from time import time

        timeout = 30
        start_time = int(time())
        while modification_found:
            modification_found = False
            post_dominators = self.__get_post_dominators(node_list)
            path_splits = self.__get_path_splits(node_list)
            merge_nodes = self.__get_merge_nodes(path_splits, post_dominators)

            for split_node in merge_nodes:
                iteration_time = int(time())
                print("Iteration: ", "time:", iteration_time - start_time)
                if iteration_time - start_time > timeout:
                    raise ValueError("Timeout expired.")

                if merge_nodes[split_node] is None:
                    # no merge exists -> no merge necessary since a return is encountered
                    continue

                # save information for later linearization step
                branch_entry_to_exit: Dict[int, int] = dict()
                branch_entry_to_updated_entry: Dict[int, int] = dict()
                branch_exit_to_updated_exit: Dict[int, int] = dict()
                empty_branches: Set[Tuple[int, int]] = set()

                for branch_entry in get_successors(self.graph, split_node):
                    for branch_exit in get_predecessors(self.graph, cast(int, merge_nodes[split_node])):
                        if branch_exit == split_node and branch_entry == merge_nodes[split_node]:
                            empty_branches.add((branch_entry, branch_exit))

                        if branch_entry not in post_dominators:
                            continue
                        if branch_exit in post_dominators[branch_entry]:
                            branch_entry_to_exit[branch_entry] = branch_exit
                if len(empty_branches) != 0:
                    raise ValueError("No empty branches allowed!")
                # initialize dicts
                for branch_entry in get_successors(self.graph, split_node):
                    branch_entry_to_updated_entry[branch_entry] = branch_entry
                for branch_exit in get_predecessors(self.graph, cast(int, merge_nodes[split_node])):
                    branch_exit_to_updated_exit[branch_exit] = branch_exit

                # create context snapshot
                context_snapshot_id = self.get_new_node_id()
                self.graph.add_node(context_snapshot_id, data=ContextSnapshot(context_snapshot_id, self.experiment))
                node_list.append(context_snapshot_id)
                add_temporary_edge(self.graph, split_node, context_snapshot_id)

                # create branch entries
                for successor in get_successors(self.graph, split_node):
                    # create and connect context restore node
                    branch_context_restore_id = self.get_new_node_id()
                    self.graph.add_node(
                        branch_context_restore_id,
                        data=ContextRestore(branch_context_restore_id, self.experiment),
                    )
                    node_list.append(branch_context_restore_id)
                    add_temporary_edge(self.graph, context_snapshot_id, branch_context_restore_id)

                    # redirect branch to restore node
                    redirect_edge(self.graph, split_node, branch_context_restore_id, successor, successor)
                    branch_entry_to_updated_entry[successor] = branch_context_restore_id
                    modification_found = True

                # create and connect create merge node and snapshot pop node
                context_merge_node_id = self.get_new_node_id()
                self.graph.add_node(context_merge_node_id, data=ContextMerge(context_merge_node_id, self.experiment))
                context_snapshot_pop_node_id = self.get_new_node_id()
                self.graph.add_node(
                    context_snapshot_pop_node_id, data=ContextSnapshotPop(context_snapshot_pop_node_id, self.experiment)
                )
                add_temporary_edge(self.graph, context_merge_node_id, context_snapshot_pop_node_id)
                add_temporary_edge(self.graph, context_snapshot_pop_node_id, cast(int, merge_nodes[split_node]))
                node_list.append(context_merge_node_id)
                node_list.append(context_snapshot_pop_node_id)

                # create branch exits
                for predecessor in get_predecessors(self.graph, cast(int, merge_nodes[split_node])):
                    # create context save node
                    context_save_node_id = self.get_new_node_id()
                    self.graph.add_node(context_save_node_id, data=ContextSave(context_save_node_id, self.experiment))
                    node_list.append(context_save_node_id)
                    # connect context save node
                    add_temporary_edge(self.graph, context_save_node_id, context_merge_node_id)
                    redirect_edge(
                        self.graph, predecessor, predecessor, cast(int, merge_nodes[split_node]), context_save_node_id
                    )
                    branch_exit_to_updated_exit[predecessor] = context_save_node_id

                # linearize the branched section by concatenating all branches
                last_node_id = context_snapshot_id
                for entry in branch_entry_to_exit:
                    if last_node_id != context_snapshot_id:
                        self.graph.remove_edge(last_node_id, context_merge_node_id)
                    exit = branch_entry_to_exit[entry]
                    updated_entry = branch_entry_to_updated_entry[entry]
                    updated_exit = branch_exit_to_updated_exit[exit]
                    # redirect entry
                    redirect_edge(self.graph, context_snapshot_id, last_node_id, updated_entry, updated_entry)
                    last_node_id = updated_exit

                #            # linearize empty branches
                #            for entry,  exit in empty_branches:
                #                updated_entry = branch_entry_to_updated_entry[entry]
                #                updated_exit = branch_exit_to_updated_exit[updated_entry]
                #                print("EMPTY: ", entry, exit)
                #                # redirect entry
                #                redirect_edge(self.graph, context_snapshot_id, last_node_id, updated_entry, updated_entry)
                #                last_node_id = updated_exit

                # connect exit of linearized section
                # add_temporary_edge(self.graph, last_node_id, context_merge_node_id)

                # DEBUG
                if modification_found:
                    break
            convert_temporary_edges(self.graph)

    def __get_merge_nodes(
        self, path_splits: Set[int], post_dominators: Dict[int, Set[int]]
    ) -> Dict[int, Optional[int]]:
        """Calculates and returns the merge nodes for paths starting a the given node"""

        def get_merge_nodes(node_list: Set[int], initial_post_dominators: Optional[Set[int]] = None) -> Set[int]:
            candidates: Set[int] = initial_post_dominators if initial_post_dominators is not None else set()
            for node in node_list:
                for succ in get_successors(self.graph, node):
                    if len(candidates) == 0:
                        candidates = post_dominators[succ]
                    candidates = candidates.intersection(post_dominators[succ])
            modification_found = True
            while modification_found:
                modification_found = False
                for c1 in candidates:
                    for c2 in candidates:
                        if c1 == c2:
                            continue
                        if c1 in post_dominators[c2]:
                            candidates.remove(c1)
                            modification_found = True
                            break
                    if modification_found:
                        break
            return candidates

        merge_nodes: Dict[int, Optional[int]] = dict()
        for node in path_splits:
            # cleanup candidates to get the earliest merge
            candidates = get_merge_nodes({node}, post_dominators[node])

            while len(candidates) > 1:
                candidates = get_merge_nodes(candidates)

            # prepare return value
            if len(candidates) == 0:
                merge_nodes[node] = None
            elif len(candidates) == 1:
                merge_nodes[node] = list(candidates)[0]
            else:
                raise ValueError(
                    "More than one merge node identified for path split: " + str(node) + " : " + str(candidates)
                )
        return merge_nodes

    def __get_path_splits(self, node_list: List[int]) -> Set[int]:
        """Returns nodes which result in path splits"""
        path_splits: Set[int] = set()
        for node in node_list:
            if len(get_successors(self.graph, node)) > 1:
                path_splits.add(node)
        return path_splits

    def __get_post_dominators(self, node_list: List[int]) -> Dict[int, Set[int]]:
        """calculates and returns the post dominators for all nodes in the function"""
        post_dominators: Dict[int, Set[int]] = dict()
        # initialize
        modified: Set[int] = set()
        for node in node_list:
            post_dominators[node] = {node}
            modified.add(node)

        # iterate
        while len(modified) > 0:
            new_modified: Set[int] = set()
            for node in modified:
                predecessors = get_predecessors(self.graph, node)
                for pred in predecessors:
                    len_pre = len(post_dominators[pred])
                    post_dominators[pred] = post_dominators[pred].union(post_dominators[node])
                    if len_pre != len(post_dominators[pred]):
                        new_modified.add(pred)
            modified = new_modified
        return post_dominators

    def __parse_branched_sections(self) -> None:
        """Branched sections in the CU Graph are represented by a serialized version in the MOG.
        To make this possible, Context Snapshot, Restore and Merge points are added to allow a synchronization
        'between' the different branches"""
        visited_nodes: Set[int] = set()
        for idx, function_node in enumerate(all_nodes(self.pet, FunctionNode)):
            print("parsing ", function_node.name, idx, "/", len(all_nodes(self.pet, FunctionNode)))
            _, _ = self.__parse_raw_node(self.cu_id_to_graph_node_id[function_node.id], visited_nodes)

        # remove visited nodes, since duplicates exist now
        for node_id in visited_nodes:
            self.graph.remove_node(node_id)

    def __parse_raw_node(self, root_node_id: int, visited_nodes: Set[int]) -> Tuple[int, int]:
        """parses the nodes starting from the root node and returns the id of the first and last node in the created linearized path"""
        visited_nodes.add(root_node_id)
        # if this node has children, parse them before proceeding
        children_entry_points: List[int] = []
        for child_id in get_children(self.graph, root_node_id):
            child_entry_point, _ = self.__parse_raw_node(child_id, visited_nodes)
            children_entry_points.append(child_entry_point)

        if len(get_successors(self.graph, root_node_id)) <= 1:
            return self.__parse_path_node(root_node_id, children_entry_points, visited_nodes)
        else:
            return self.__parse_branching_point(root_node_id, children_entry_points, visited_nodes)

    def __parse_path_node(
        self, root_node_id: int, connect_to_children: List[int], visited_nodes: Set[int]
    ) -> Tuple[int, int]:
        """parses a regular path node, i.e. one with at most one successor node.
        returns the id of the first and last node in the created linearized path"""

        # create a duplicate of the root node
        duplicate_node_id = self.get_new_node_id()
        tmp_node_data = data_at(self.graph, root_node_id)
        self.graph.add_node(duplicate_node_id, data=tmp_node_data)

        # connect duplicated entry node to children
        for children_id in connect_to_children:
            add_child_edge(self.graph, duplicate_node_id, children_id)

        if len(get_successors(self.graph, root_node_id)) == 0:
            # root is a path end
            return duplicate_node_id, duplicate_node_id
        else:
            # proceed to successor
            successor_id = get_successors(self.graph, root_node_id)[0]
            path_entry, path_end = self.__parse_raw_node(successor_id, visited_nodes)

            # connect created duplicate to the successor
            add_temporary_edge(self.graph, duplicate_node_id, path_entry)

            return duplicate_node_id, path_end

    def __parse_branching_point(
        self, root_node_id: int, connect_to_children: List[int], visited_nodes: Set[int]
    ) -> Tuple[int, int]:
        """parses a branching point, i.e. a node with more than one successor.
        returns the id of the first and last node in the created linearized path"""

        #########
        # Step 1: create duplicate of root node
        # Step 2: create and connect context snapshot
        # Step 3: parse branches
        #   Step 3.1: create and connect context restore node
        #   Step 3.2: parse branch
        #   Step 3.3: create context save node
        #   Step 3.3: connect restore and save not to branch entry and exit
        # step 4: create and connect context merge node
        # Step 5: create and connect context snapshot pop
        ########

        # Step 1: create duplicate of root node
        duplicate_node_id = self.get_new_node_id()
        tmp_node_data = data_at(self.graph, root_node_id)
        self.graph.add_node(duplicate_node_id, data=tmp_node_data)

        # Step 2: create and connect context snapshot
        context_snapshot_id = self.get_new_node_id()
        self.graph.add_node(context_snapshot_id, data=ContextSnapshot(context_snapshot_id, self.experiment))
        add_temporary_edge(self.graph, duplicate_node_id, context_snapshot_id)

        # Step 3: parse branches
        last_added_node_id = context_snapshot_id
        for successor in get_successors(self.graph, root_node_id):
            # Step 3.1: create and connect context restore node
            branch_context_restore_id = self.get_new_node_id()
            self.graph.add_node(
                branch_context_restore_id,
                data=ContextRestore(branch_context_restore_id, self.experiment),
            )
            add_temporary_edge(self.graph, last_added_node_id, branch_context_restore_id)

            # Step 3.2: parse branch
            branch_entry, branch_exit = self.__parse_raw_node(successor, visited_nodes)

            # Step 3.3: create context save node
            branch_context_save_id = self.get_new_node_id()
            self.graph.add_node(branch_context_save_id, data=ContextSave(branch_context_save_id, self.experiment))

            # Step 3.3: connect restore and save node to branch entry and exit
            add_temporary_edge(self.graph, branch_context_restore_id, branch_entry)
            add_temporary_edge(self.graph, branch_exit, branch_context_save_id)

            # update last_added_node_id
            last_added_node_id = branch_context_save_id

        # step 4: create and connect context merge node
        context_merge_node_id = self.get_new_node_id()
        self.graph.add_node(context_merge_node_id, data=ContextMerge(context_merge_node_id, self.experiment))
        add_temporary_edge(self.graph, last_added_node_id, context_merge_node_id)

        # Step 5: create and connect context snapshot pop
        context_snapshot_pop_id = self.get_new_node_id()
        self.graph.add_node(
            context_snapshot_pop_id,
            data=ContextSnapshotPop(context_snapshot_pop_id, self.experiment),
        )
        add_temporary_edge(self.graph, context_merge_node_id, context_snapshot_pop_id)

        # connect duplicated entry node to children
        for children_id in connect_to_children:
            add_child_edge(self.graph, duplicate_node_id, children_id)

        return duplicate_node_id, context_snapshot_pop_id

    def __add_cu_nodes(self) -> None:
        """adds Workload nodes which represent the CU Nodes to the graph.
        The added nodes will not be connected in any way."""
        for cu_node in all_nodes(self.pet, CUNode):
            # create new node for CU
            new_node_id = self.get_new_node_id()
            self.cu_id_to_graph_node_id[cu_node.id] = new_node_id
            # calculate accessed data
            written_memory_regions, read_memory_regions = get_data_accesses_for_cu(self.pet, cu_node.id)
            try:
                parallelizable_workload = calculate_workload(
                    self.pet, cu_node, ignore_function_calls_and_cached_values=True
                )
            except RecursionError as rerr:
                warnings.warn("Cost calculation not possible for node: " + str(cu_node.id) + "!")
                parallelizable_workload = 0
            self.graph.add_node(
                new_node_id,
                data=Workload(
                    node_id=new_node_id,
                    experiment=self.experiment,
                    cu_id=cu_node.id,
                    sequential_workload=Integer(0),
                    parallelizable_workload=Integer(parallelizable_workload),
                    written_memory_regions=written_memory_regions,
                    read_memory_regions=read_memory_regions,
                ),
            )

    def __add_loop_nodes(self) -> None:
        """adds Loop Nodes to the graph.
        connects contained nodes using Children edges"""
        for loop_node in all_nodes(self.pet, LoopNode):
            # calculate metadata
            loop_subtree = subtree_of_type(self.pet, loop_node, CUNode)

            # get iteration count for loop
            if loop_node.loop_data is not None:
                iteration_count = max(1, loop_node.loop_data.average_iteration_count)
            else:
                # loop has not been executed, thus, no information was gathered during the profiling
                # set iteration_count to prevent divisions by zero
                iteration_count = 1

            # create new node for Loop
            new_node_id = self.get_new_node_id()
            self.cu_id_to_graph_node_id[loop_node.id] = new_node_id
            try:
                discopop_workload = calculate_workload(
                    self.pet, loop_node, ignore_function_calls_and_cached_values=True
                )
            except RecursionError as rerr:
                warnings.warn("Cost calculation not possible for node: " + str(loop_node.id) + "!")
                discopop_workload = 0
            self.graph.add_node(
                new_node_id,
                data=Loop(
                    node_id=new_node_id,
                    cu_id=loop_node.id,
                    discopop_workload=discopop_workload,
                    iterations=iteration_count,
                    position=loop_node.start_position(),
                    experiment=self.experiment,
                ),
            )
            # connect loop node and entry node via a child edge
            tmp_entry_node = loop_node.get_entry_node(self.pet)
            if tmp_entry_node is None:
                raise ValueError("Loop: " + str(loop_node) + " has no entry node!")
            entry_node_cu_id = tmp_entry_node.id
            add_child_edge(self.graph, new_node_id, self.cu_id_to_graph_node_id[entry_node_cu_id])

            # redirect edges from outside the loop to the entry node to the Loop node
            for s, t, d in in_edges(self.pet, entry_node_cu_id, EdgeType.SUCCESSOR):
                if self.pet.node_at(s) not in loop_subtree:
                    try:
                        redirect_edge(
                            self.graph,
                            old_source_id=self.cu_id_to_graph_node_id[s],
                            new_source_id=self.cu_id_to_graph_node_id[s],
                            old_target_id=self.cu_id_to_graph_node_id[entry_node_cu_id],
                            new_target_id=new_node_id,
                        )
                    except KeyError as ke:
                        if self.experiment.arguments.verbose:
                            print("ignoring redirect of edge due to KeyError: ", ke)

            # redirect edges to the outside of the loop
            for s, t, d in out_edges(self.pet, entry_node_cu_id, EdgeType.SUCCESSOR):
                if self.pet.node_at(t) not in loop_subtree:
                    redirect_edge(
                        self.graph,
                        old_source_id=self.cu_id_to_graph_node_id[entry_node_cu_id],
                        new_source_id=new_node_id,
                        old_target_id=self.cu_id_to_graph_node_id[t],
                        new_target_id=self.cu_id_to_graph_node_id[t],
                    )

            # copy entry node
            entry_node_id = self.cu_id_to_graph_node_id[entry_node_cu_id]
            entry_node_data = data_at(self.graph, entry_node_id)
            copied_entry_node_id = self.get_new_node_id()
            self.graph.add_node(copied_entry_node_id, data=entry_node_data)

            # redirect edges from inside the loop to the copy of the entry node
            for s, t, d in in_edges(self.pet, entry_node_cu_id, EdgeType.SUCCESSOR):
                if self.pet.node_at(s) in loop_subtree:
                    redirect_edge(
                        self.graph,
                        old_source_id=self.cu_id_to_graph_node_id[s],
                        new_source_id=self.cu_id_to_graph_node_id[s],
                        old_target_id=self.cu_id_to_graph_node_id[entry_node_cu_id],
                        new_target_id=copied_entry_node_id,
                    )

            # redirect accesses to the cu_id of the entry node to the newly created loop node
            self.cu_id_to_graph_node_id[entry_node_cu_id] = new_node_id

    def __add_functions(self) -> None:
        """parse function nodes in the PET graph.
        Results in the creation of a forest of function graphs."""
        for function_node in all_nodes(self.pet, FunctionNode):
            # create function root node and register it in the graph
            new_node_id = self.get_new_node_id()
            self.graph.add_node(
                new_node_id,
                data=FunctionRoot(
                    node_id=new_node_id,
                    experiment=self.experiment,
                    cu_id=function_node.id,
                    name=function_node.name,
                ),
            )
            # connect function node to its entry node
            add_child_edge(
                self.graph,
                new_node_id,
                self.cu_id_to_graph_node_id[function_node.get_entry_cu_id(self.pet)],
            )
            # save ID
            self.cu_id_to_graph_node_id[function_node.id] = new_node_id

    def __add_pet_successor_edges(self) -> None:
        for cu_node in all_nodes(self.pet, CUNode):
            for successor_cu_id in [t for s, t, d in out_edges(self.pet, cu_node.id, EdgeType.SUCCESSOR)]:
                add_successor_edge(
                    self.graph,
                    self.cu_id_to_graph_node_id[cu_node.id],
                    self.cu_id_to_graph_node_id[successor_cu_id],
                )

    def __mark_branch_affiliation(self) -> None:
        """Mark each nodes' branch affiliation to allow a simple check for 'on same branch' relation
        without considering the successor relation."""

        def mark_branched_section(node: int, branch_stack: List[int]) -> None:
            node_data = data_at(self.graph, node)
            if isinstance(node_data, ContextSnapshot):
                branch_stack.append(node)
            elif isinstance(node_data, ContextSnapshotPop):
                branch_stack.pop()
            # mark current node
            node_data.branch_affiliation = copy.deepcopy(branch_stack)

            # mark children
            for child in get_children(self.graph, node):
                mark_branched_section(child, copy.deepcopy(branch_stack))

            # mark successors (at most one successor can exist,
            # since parallelization suggestions have not been imported yet)
            for successor in get_successors(self.graph, node):
                mark_branched_section(successor, copy.deepcopy(branch_stack))

        for function_node in get_all_function_nodes(self.graph):
            current_node = get_children(self.graph, function_node)[0]
            mark_branched_section(current_node, [])

    #    def __new_calculate_data_flow(self):
    #        """calculate dataflow in such a way, that no data is left on any device but the host and every relevant change is synchronized."""
    #        self.in_data_flow = dict()
    #        self.out_data_flow = dict()
    #
    #        data_transactions= dict()  # stores created and removed data for unrolling when leaving a "frame"
    #        # Dict[device_id, List[("enter/exit", memreg)]]
    #
    #        data_frame_stack: List[int] = [] # stores node ids which opened a data frame
    #
    #        for function in get_all_function_nodes(self.graph):
    #            logger.info("calculate data flow for function: " + data_at(self.graph, function).name)

    def __calculate_data_flow(self) -> None:
        self.in_data_flow = dict()
        self.out_data_flow = dict()

        def inlined_data_flow_calculation(
            current_node: Optional[int], current_last_writes: Dict[MemoryRegion, int]
        ) -> Dict[MemoryRegion, int]:
            # TODO add entering and exiting data frames to support resetting at end of a child section
            while current_node is not None:
                # check if current_node uses written data
                reads, writes = get_read_and_written_data_from_subgraph(
                    self.graph, current_node, ignore_successors=True
                )

                for mem_reg in current_last_writes:
                    # check if incoming data flow exists
                    if mem_reg in reads or mem_reg in writes:
                        # uses written data
                        # create incoming data flow
                        if current_node not in self.in_data_flow:
                            self.in_data_flow[current_node] = set()
                        self.in_data_flow[current_node].add(current_last_writes[mem_reg])
                        # create outgoing data flow
                        if current_last_writes[mem_reg] not in self.out_data_flow:
                            self.out_data_flow[current_last_writes[mem_reg]] = set()
                        self.out_data_flow[current_last_writes[mem_reg]].add(current_node)
                # save write to calculate outgoing data flow
                for mem_reg in writes:
                    current_last_writes[mem_reg] = current_node

                ## start data_flow calculation for children
                for child in get_children(self.graph, current_node):
                    _current_last_writes = inlined_data_flow_calculation(child, current_last_writes)

                # continue to successor
                successors = get_successors(self.graph, current_node)
                if len(successors) > 1:
                    raise ValueError("only a single successor should exist at this stage in the process!")

                elif len(successors) == 1:
                    current_node = successors[0]
                else:
                    current_node = None

            return current_last_writes

        # Note: at this point in time, the graph MUST NOT have branched sections
        all_function_nodes = get_all_function_nodes(self.graph)
        for idx, function_node in enumerate(all_function_nodes):
            if self.experiment.arguments.verbose:
                print(
                    "Calculating dataflow for function: ",
                    cast(FunctionRoot, data_at(self.graph, function_node)).name,
                    idx,
                    "/",
                    len(all_function_nodes),
                )
            if (
                function_node not in self.experiment.hotspot_function_node_ids
                and len(self.experiment.hotspot_function_node_ids) > 0
            ):
                print("SKIPPING NON-HOTSPOT FUNCTION: ", cast(FunctionRoot, data_at(self.graph, function_node)).name)
                continue
            if function_node in self.invalid_functions:
                print("SKIPPING INVALID FUNCTION: ", cast(FunctionRoot, data_at(self.graph, function_node)).name)
                continue

            try:
                last_writes: Dict[MemoryRegion, int] = dict()
                inlined_data_flow_calculation(get_children(self.graph, function_node)[0], last_writes)
            except ValueError:
                if self.experiment.arguments.verbose:
                    print(
                        "CDF: Function:",
                        cast(FunctionRoot, data_at(self.graph, function_node)).name,
                        "invalid due to graph construction errors. Skipping.",
                    )
                    # show_function(self.graph, data_at(self.graph, function_node), show_dataflow=False, show_mutex_edges=False)
                self.invalid_functions.add(function_node)
            except IndexError:
                # function has no child. ignore, but issue a warning
                warnings.warn(
                    "Skipping function: "
                    + cast(FunctionRoot, data_at(self.graph, function_node)).name
                    + " as it has no children nodes!"
                )
                pass

        for key in self.out_data_flow:
            for entry in self.out_data_flow[key]:
                if not self.graph.has_edge(key, entry):
                    add_dataflow_edge(self.graph, key, entry)

    def __propagate_reads_and_writes(self) -> None:
        # initialize queue
        queue = [n for n in self.graph.nodes]

        while queue:
            current = queue.pop()
            current_data = data_at(self.graph, current)
            parents = get_all_parents(self.graph, current)
            queue += [p for p in parents if p not in queue]
            for p in parents:
                data_at(self.graph, p).written_memory_regions.update(current_data.written_memory_regions)
                data_at(self.graph, p).read_memory_regions.update(current_data.read_memory_regions)

    def __inline_reads_and_writes_from_call(self) -> None:
        for node in self.graph.nodes:
            called = get_out_call_edges(self.graph, node)
            if len(called) == 0:
                continue
            logger.info("Node: " + str(node) + " called: " + str(called))
            # identify reads and writes in called function
            node_data = data_at(self.graph, node)
            for function_id in called:
                called_function_data = data_at(self.graph, function_id)
                logger.info("--> called function: " + cast(FunctionRoot, called_function_data).name)
                function_read_memory_regions: Dict[MemoryRegion, ReadDataAccess] = dict()
                function_written_memory_regions: Dict[MemoryRegion, WriteDataAccess] = dict()
                for rda in called_function_data.read_memory_regions:
                    if rda.memory_region not in function_read_memory_regions:
                        function_read_memory_regions[rda.memory_region] = rda
                for wda in called_function_data.written_memory_regions:
                    if wda.memory_region not in function_written_memory_regions:
                        function_written_memory_regions[wda.memory_region] = wda
                # append the gathered reads and writes to the calling node
                for read_mem_reg in function_read_memory_regions:
                    call_rda = copy.deepcopy(function_read_memory_regions[read_mem_reg])
                    call_rda.from_call = True
                    node_data.read_memory_regions.add(call_rda)
                for written_mem_reg in function_written_memory_regions:
                    call_wda = copy.deepcopy(function_written_memory_regions[written_mem_reg])
                    call_wda.from_call = True
                    node_data.written_memory_regions.add(call_wda)
