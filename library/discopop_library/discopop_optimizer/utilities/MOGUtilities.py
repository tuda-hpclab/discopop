# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import itertools
from multiprocessing import Pool
from typing import Any, ClassVar, Dict, List, Optional, cast, Set, Tuple
import warnings

import matplotlib  # type: ignore
import matplotlib.pyplot as plt  # type: ignore
import networkx as nx  # type: ignore
import tqdm  # type: ignore

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.classes.edges.CallEdge import CallEdge
from discopop_library.discopop_optimizer.classes.edges.DataFlowEdge import DataFlowEdge
from discopop_library.discopop_optimizer.classes.edges.MutuallyExclusiveEdge import MutuallyExclusiveEdge
from discopop_library.discopop_optimizer.classes.edges.ChildEdge import ChildEdge
from discopop_library.discopop_optimizer.classes.edges.GenericEdge import GenericEdge
from discopop_library.discopop_optimizer.classes.edges.OptionEdge import OptionEdge
from discopop_library.discopop_optimizer.classes.edges.RequirementEdge import RequirementEdge
from discopop_library.discopop_optimizer.classes.edges.SuccessorEdge import SuccessorEdge
from discopop_library.discopop_optimizer.classes.edges.TemporaryEdge import TemporaryEdge
from discopop_library.discopop_optimizer.classes.nodes.ContextNode import ContextNode
from discopop_library.discopop_optimizer.classes.nodes.FunctionReturn import FunctionReturn
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.nodes.GenericNode import GenericNode
from discopop_library.discopop_optimizer.classes.nodes.Loop import Loop
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at

from networkx.drawing.nx_pydot import graphviz_layout  # type: ignore


def get_nodes_from_cu_id(graph: nx.DiGraph, cu_node_id: NodeID) -> List[int]:
    result_list: List[int] = []
    for node_id in graph.nodes:
        if cast(GenericNode, graph.nodes[node_id]["data"]).original_cu_id == cu_node_id:
            result_list.append(node_id)
    return result_list


def get_edge_data(graph: nx.DiGraph, source: int, target: int) -> GenericEdge:
    return cast(GenericEdge, graph.edges[(source, target)]["data"])


def get_successors(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the successors of the given node"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], SuccessorEdge)]


def get_temporary_successors(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the temporary successors of the given node"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], TemporaryEdge)]


def get_predecessors(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the predecessors of the given node"""
    return [edge[0] for edge in graph.in_edges(node_id, data="data") if isinstance(edge[2], SuccessorEdge)]


def get_children(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the children of the given node"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], ChildEdge)]


def get_in_child_edges_sources(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the children of the given node"""
    return [edge[0] for edge in graph.in_edges(node_id, data="data") if isinstance(edge[2], ChildEdge)]


def get_out_options(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the parallelization options of the given node"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], OptionEdge)]


def get_in_options(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the parallelization options of the given node"""
    return [edge[0] for edge in graph.in_edges(node_id, data="data") if isinstance(edge[2], OptionEdge)]


def get_in_mutex_edges(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids which are mutually exclusive to the current node_id"""
    return [edge[0] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], MutuallyExclusiveEdge)]


def get_out_mutex_edges(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids which are mutually exclusive to the current node_id"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], MutuallyExclusiveEdge)]


def get_out_call_edges(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids which are called by current node_id"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], CallEdge)]


def get_requirements(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns a list of node ids for the requirements of the parallelization option in the given node"""
    return [edge[1] for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], RequirementEdge)]


def has_temporary_successor(graph: nx.DiGraph, node_id: int) -> bool:
    """Checks whether the given node has outgoing temporary successor edges"""
    return len([edge for edge in graph.out_edges(node_id, data="data") if isinstance(edge[2], TemporaryEdge)]) > 0


def get_function_return_node(graph: nx.DiGraph, function: int) -> int:
    """Identify and return the FunctionReturn node belonging to function."""
    queue = get_children(graph, function)
    while len(queue) > 0:
        current = queue.pop()
        successors = get_successors(graph, current)
        if len(successors) == 0 and type(data_at(graph, current)) == FunctionReturn:
            return current
        queue += [s for s in successors if s not in queue]
    raise ValueError(
        "No FunctionReturn found for function: "
        + str(function)
        + " "
        + cast(FunctionRoot, data_at(graph, function)).name
    )


def show_decision_graph(
    graph: nx.DiGraph, decisions: List[int], show_dataflow: bool = True, show_mutex_edges: bool = False
) -> None:
    print("Decisions: ", decisions)
    contained_nodes: Set[int] = set()
    for function in get_all_function_nodes(graph):
        # get nodes in subtree of function, if they are reachable by the set of decisions
        queue: List[int] = [data_at(graph, function).node_id]
        while len(queue) > 0:
            current = queue.pop()
            contained_nodes.add(current)
            queue += [c for c in get_children(graph, current) if c not in queue and c not in contained_nodes]
            successors = get_successors(graph, current)

            if len(successors) <= 1:
                # no decision required
                queue += [s for s in successors if s not in queue and s not in contained_nodes]
            else:
                # filter for successors in decisions
                print("SUCCESSORS: ", successors)
                valid_successors = [s for s in successors if s in decisions]
                # check for requirements, if no valid successor was found
                if len(valid_successors) == 0:
                    requirements = []
                    for dec in decisions:
                        requirements += get_requirements(graph, dec)
                    valid_successors = [s for s in successors if s in requirements]
                    print("REQUIREMENT SUCCESSORS: ", valid_successors)
                print("VALID SUCCESSORS: ", valid_successors)
                # if no decision could be made, keep all sequential successors
                if len(valid_successors) > 0:
                    queue += [s for s in valid_successors if s not in queue and s not in contained_nodes]
                else:
                    # fallback
                    queue += [s for s in successors if data_at(graph, s).represents_sequential_version()]

    # show the subgraph
    show(graph.subgraph(contained_nodes), show_dataflow=show_dataflow, show_mutex_edges=show_mutex_edges)


def show_function(
    graph: nx.DiGraph, function: FunctionRoot, show_dataflow: bool = True, show_mutex_edges: bool = True
) -> None:
    # get nodes in subtree of function
    contained_nodes: Set[int] = set()
    queue: List[int] = [function.node_id]
    while len(queue) > 0:
        current = queue.pop()
        contained_nodes.add(current)
        queue += [c for c in get_children(graph, current) if c not in queue and c not in contained_nodes]
        queue += [s for s in get_successors(graph, current) if s not in queue and s not in contained_nodes]

    # show the subgraph
    show(graph.subgraph(contained_nodes), show_dataflow=show_dataflow, show_mutex_edges=show_mutex_edges)


def show(graph: nx.DiGraph, show_dataflow: bool = True, show_mutex_edges: bool = True) -> None:
    """Plots the graph

    :return:
    """
    matplotlib.use("TkAgg")
    fig, ax = plt.subplots()
    try:
        # pos = nx.planar_layout(graph)  # good
        pos = graphviz_layout(graph, prog="dot")
    except nx.exception.NetworkXException:
        try:
            # fallback layouts
            pos = nx.shell_layout(graph)  # maybe
        except nx.exception.NetworkXException:
            pos = nx.random_layout(graph)

    drawn_nodes = set()
    nodes_lists: Dict[Any, Any] = dict()
    node_ids: Dict[Any, Any] = dict()
    node_insertion_sequence: List[Any] = []
    # draw nodes
    node_insertion_sequence.append(FunctionRoot)
    nodes_lists[FunctionRoot] = nx.draw_networkx_nodes(
        graph,
        pos=pos,
        ax=ax,
        node_size=200,
        node_color="#ff5151",
        node_shape="d",
        nodelist=[n for n in graph.nodes if isinstance(data_at(graph, n), FunctionRoot)],
    )
    node_ids[FunctionRoot] = [n for n in graph.nodes if isinstance(data_at(graph, n), FunctionRoot)]
    drawn_nodes.update([n for n in graph.nodes if isinstance(data_at(graph, n), FunctionRoot)])

    node_insertion_sequence.append(Loop)
    nodes_lists[Loop] = nx.draw_networkx_nodes(
        graph,
        pos=pos,
        ax=ax,
        node_size=200,
        node_color="#ff5151",
        node_shape="s",
        nodelist=[n for n in graph.nodes if isinstance(data_at(graph, n), Loop)],
    )
    node_ids[Loop] = [n for n in graph.nodes if isinstance(data_at(graph, n), Loop)]
    drawn_nodes.update([n for n in graph.nodes if isinstance(data_at(graph, n), Loop)])

    node_insertion_sequence.append(ContextNode)
    nodes_lists[ContextNode] = nx.draw_networkx_nodes(
        graph,
        pos=pos,
        ax=ax,
        node_size=200,
        node_color="yellow",
        node_shape="s",
        nodelist=[n for n in graph.nodes if isinstance(data_at(graph, n), ContextNode)],
    )
    node_ids[ContextNode] = [n for n in graph.nodes if isinstance(data_at(graph, n), ContextNode)]
    drawn_nodes.update([n for n in graph.nodes if isinstance(data_at(graph, n), ContextNode)])

    node_insertion_sequence.append(Workload)
    nodes_lists[Workload] = nx.draw_networkx_nodes(
        graph,
        pos=pos,
        ax=ax,
        node_size=200,
        node_color="#2B85FD",
        node_shape="o",
        nodelist=[n for n in graph.nodes if isinstance(data_at(graph, n), Workload) and n not in drawn_nodes],
    )
    node_ids[Workload] = [n for n in graph.nodes if isinstance(data_at(graph, n), Workload) and n not in drawn_nodes]
    drawn_nodes.update([n for n in graph.nodes if isinstance(data_at(graph, n), Workload) and n not in drawn_nodes])

    # id as label
    labels = {}
    for n in graph.nodes:
        labels[n] = graph.nodes[n]["data"].get_plot_label()
    nx.draw_networkx_labels(graph, pos, labels, font_size=7, ax=ax)

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="black",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], SuccessorEdge)],
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="red",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], ChildEdge)],
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="blue",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], TemporaryEdge)],
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="pink",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], OptionEdge)],
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="yellow",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], RequirementEdge)],
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        ax=ax,
        edge_color="blue",
        edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], CallEdge)],
    )

    if show_mutex_edges:
        nx.draw_networkx_edges(
            graph,
            pos,
            ax=ax,
            edge_color="orange",
            edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], MutuallyExclusiveEdge)],
        )

    if show_dataflow:
        nx.draw_networkx_edges(
            graph,
            pos,
            ax=ax,
            edge_color="green",
            edgelist=[e for e in graph.edges(data="data") if isinstance(e[2], DataFlowEdge)],
        )

    # define tool tip style when hovering
    # based on https://stackoverflow.com/questions/61604636/adding-tooltip-for-nodes-in-python-networkx-graph
    annot = ax.annotate(  # type: ignore
        "",
        xy=(0, 0),
        xytext=(20, 20),
        textcoords="offset points",
        bbox=dict(boxstyle="round", fc="w"),
        arrowprops=dict(arrowstyle="->"),
    )
    annot.set_visible(False)

    idx_to_node_dict = {}
    for idx, node in enumerate(graph.nodes):
        idx_to_node_dict[idx] = node

    def update_annot(ind: Any, node_ids_list: Any) -> None:
        node_idx = ind["ind"][0]
        node_id = node_ids_list[node_idx]
        xy = pos[node_id]
        annot.xy = xy
        node_attr = {"node": node_id}
        node_attr.update(graph.nodes[node_id])
        text = data_at(graph, node_id).get_hover_text()
        annot.set_text(text)

    def hover(event: Any) -> None:
        vis = annot.get_visible()
        if event.inaxes == ax:
            for node_type in node_insertion_sequence:
                nodes = nodes_lists[node_type]
                try:
                    cont, ind = nodes.contains(event)
                    if cont:
                        update_annot(ind, node_ids[node_type])
                        annot.set_visible(True)
                        fig.canvas.draw_idle()  # type: ignore
                    else:
                        if vis:
                            annot.set_visible(False)
                            fig.canvas.draw_idle()  # type: ignore
                except TypeError:
                    pass

    fig.canvas.mpl_connect("motion_notify_event", hover)  # type: ignore

    plt.show()


def add_successor_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    edge_data = SuccessorEdge()
    graph.add_edge(source_id, target_id, data=edge_data)


def add_child_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    edge_data = ChildEdge()
    graph.add_edge(source_id, target_id, data=edge_data)


def add_call_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    edge_data = CallEdge()
    graph.add_edge(source_id, target_id, data=edge_data)


def add_temporary_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    edge_data = TemporaryEdge()
    graph.add_edge(source_id, target_id, data=edge_data)


def add_dataflow_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    edge_data = DataFlowEdge()
    graph.add_edge(source_id, target_id, data=edge_data)


def delete_outgoing_temporary_edges(graph: nx.DiGraph, source_id: int) -> None:
    to_be_deleted = set()
    for edge in graph.out_edges(source_id):
        edge_data = graph.edges[edge]["data"]
        if isinstance(edge_data, TemporaryEdge):
            to_be_deleted.add(edge)
    for edge in to_be_deleted:
        remove_edge(graph, edge[0], edge[1])


def redirect_edge(
    graph: nx.DiGraph,
    old_source_id: int,
    new_source_id: int,
    old_target_id: int,
    new_target_id: int,
) -> None:
    edge_data = graph.edges[(old_source_id, old_target_id)]["data"]
    remove_edge(graph, old_source_id, old_target_id)
    graph.add_edge(new_source_id, new_target_id, data=edge_data)


def remove_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    graph.remove_edge(source_id, target_id)


def convert_temporary_edges(graph: nx.DiGraph) -> None:
    """Convert temporary edges to Successor edges"""
    for edge in graph.edges:
        edge_data = graph.edges[edge]["data"]
        if isinstance(edge_data, TemporaryEdge):
            graph.edges[edge]["data"] = edge_data.convert_to_successor_edge()


def convert_temporary_edge(graph: nx.DiGraph, source_id: int, target_id: int) -> None:
    """Converts a single temporary edge to a successor edge"""
    edge_data = graph.edges[(source_id, target_id)]["data"]
    if isinstance(edge_data, TemporaryEdge):
        graph.edges[(source_id, target_id)]["data"] = edge_data.convert_to_successor_edge()


def get_all_function_nodes(graph: nx.DiGraph) -> List[int]:
    result_set: Set[int] = set()
    for node_id in graph.nodes:
        if type(graph.nodes[node_id]["data"]) == FunctionRoot:
            result_set.add(node_id)
    return list(result_set)


def get_all_nodes_in_function(graph: nx.DiGraph, function_id: int) -> List[int]:
    result_list: List[int] = []
    queue: List[int] = [function_id]
    while len(queue) > 0:
        current = queue.pop()
        if current != function_id:
            result_list.append(current)
        queue += [c for c in get_children(graph, current) if c not in result_list and c not in queue]
        queue += [s for s in get_successors(graph, current) if s not in result_list and s not in queue]

    #    for node_id in graph.nodes:
    #        if function_id in get_all_parents(graph, node_id):
    #            result_list.append(node_id)
    return result_list


def get_nodes_by_functions(graph: nx.DiGraph) -> Dict[int, List[int]]:
    result_dict: Dict[int, List[int]] = dict()
    function_nodes = set(get_all_function_nodes(graph))
    for node in graph.nodes:
        parents = get_all_parents(graph, node)
        parent_functions = set(parents).intersection(function_nodes)
        for pf in parent_functions:
            if pf not in result_dict:
                result_dict[pf] = []
            result_dict[pf].append(node)
    return result_dict


def get_all_loop_nodes(graph: nx.DiGraph) -> List[int]:
    result_set: Set[int] = set()
    for node_id in graph.nodes:
        if type(graph.nodes[node_id]["data"]) == Loop:
            result_set.add(node_id)
    return list(result_set)


def get_read_and_written_data_from_subgraph(
    graph: nx.DiGraph, node_id: int, ignore_successors: bool = False
) -> Tuple[Set[MemoryRegion], Set[MemoryRegion]]:
    """Collect written and read memory regions for the node itself, it's successor and it's children. Used in the data flow calculation step."""
    read_memory_regions: Set[MemoryRegion] = set()
    written_memory_regions: Set[MemoryRegion] = set()
    # collect reads and writes from successors and children
    try:
        subgraph = get_children(graph, node_id)
        if not ignore_successors:
            subgraph += get_successors(graph, node_id)
        for successor in subgraph:
            reads, writes = get_read_and_written_data_from_subgraph(graph, successor)
            read_memory_regions.update(reads)
            written_memory_regions.update(writes)
    except RecursionError:
        warnings.warn("Recursion limit exceeeded. Read and write in subtrees might be inaccurate.")
    # add reads and writes of the node itself
    node_data = data_at(graph, node_id)
    read_memory_regions.update([read_access.memory_region for read_access in node_data.read_memory_regions])
    written_memory_regions.update([write_access.memory_region for write_access in node_data.written_memory_regions])

    return read_memory_regions, written_memory_regions


def get_path_entry(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns the first node in the successor path node_id belongs to."""
    current_node = node_id
    preds = get_predecessors(graph, current_node)
    while len(preds) != 0:
        current_node = preds[0]
        preds = get_predecessors(graph, current_node)
    return [current_node]


def get_parents(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns the first parent of node_id.
    Returns an empty list if none exists."""
    current_node = node_id
    preds = get_predecessors(graph, current_node)
    while len(preds) != 0:
        current_node = preds[0]
        preds = get_predecessors(graph, current_node)

    parents = [
        cast(int, edge[0]) for edge in graph.in_edges(current_node, data="data") if isinstance(edge[2], ChildEdge)
    ]

    return parents


def get_all_parents(graph: nx.DiGraph, node_id: int) -> List[int]:
    """Returns all parents of node_id.
    Returns an empty list if none exist."""

    queue: Set[int] = set(get_parents(graph, node_id))
    all_parents: Set[int] = set()
    while queue:
        current = queue.pop()
        all_parents.add(current)
        new_parents = [
            parent for parent in get_parents(graph, current) if parent not in queue and parent not in all_parents
        ]
        queue.update(new_parents)
    return list(all_parents)


def get_parent_function(graph: nx.DiGraph, node_id: int) -> int:
    """Returns the parent function of node_id"""
    all_parents = get_all_parents(graph, node_id)
    for p in all_parents:
        if type(data_at(graph, p)) == FunctionRoot:
            return p
    raise ValueError("No parent exists for node " + str(node_id) + ", type: " + str(type(data_at(graph, node_id))))


global_graph = None
global_arguments = None


def get_available_decisions_for_functions(
    graph: nx.DiGraph, arguments: OptimizerArguments
) -> Dict[FunctionRoot, List[List[int]]]:
    """Returns a list of Lists describing all available decisions through the subgraph of the individual Functions."""
    global global_graph
    global global_arguments
    global_graph = graph
    global_arguments = arguments

    if arguments.verbose:
        print("Calculating available decisions per function...")
    available_decisions: Dict[FunctionRoot, List[List[int]]] = dict()
    param_list = [(function_node) for function_node in get_all_function_nodes(graph)]
    #    with Pool(
    #        initializer=__initialize_availability_worker,
    #        initargs=(graph, arguments),
    #    ) as pool:
    #        tmp_result = list(
    #            tqdm.tqdm(pool.imap_unordered(__parallel_get_decisions_from_node, param_list), total=len(param_list))
    #        )

    tmp_result: List[Any] = []
    for p in param_list:
        tmp_result.append(__parallel_get_decisions_from_node(p))

    for local_result in tmp_result:
        available_decisions[cast(FunctionRoot, data_at(graph, local_result[0]))] = local_result[1]

    if arguments.verbose:
        print("\tDone.")
        print("# Identified paths per function:")
        for function in available_decisions:
            print("#", function.name)
            for elem in available_decisions[function]:
                print("#..", elem)
        print()

    # show(graph, show_dataflow=False)
    # import sys
    # sys.exit(0)

    return available_decisions


def __initialize_availability_worker(graph: nx.DiGraph, arguments: OptimizerArguments) -> None:
    global global_graph
    global global_arguments
    global_graph = graph
    global_arguments = arguments


def __parallel_get_decisions_from_node_recursive(function_node: int) -> Tuple[int, List[List[int]]]:
    global global_graph
    global global_arguments

    def get_decisions_from_node_recursive(node_id: int, prev_decisions: List[int]) -> List[List[int]]:
        children_paths: List[List[int]] = []
        # get decisions from children
        for child in get_children(global_graph, node_id):
            children_paths += get_decisions_from_node_recursive(child, copy.deepcopy(prev_decisions))
        # get decisions from current node
        successors = get_successors(global_graph, node_id)
        successor_paths: List[List[int]] = []
        if len(successors) == 1:
            if len(children_paths) > 0:
                for cp in children_paths:
                    successor_paths += get_decisions_from_node_recursive(successors[0], copy.deepcopy(cp))
            else:
                successor_paths += get_decisions_from_node_recursive(successors[0], copy.deepcopy(prev_decisions))
            return successor_paths
        elif len(successors) == 0:
            if len(children_paths) > 0:
                return children_paths
            else:
                return [prev_decisions]
        else:
            tmp_result = []
            if len(children_paths) > 0:
                for cp in children_paths:
                    successor_paths = []
                    for succ in successors:
                        successor_paths += get_decisions_from_node_recursive(succ, copy.deepcopy(cp + [succ]))
                    tmp_result += successor_paths
            else:
                successor_paths = []
                for succ in successors:
                    successor_paths += get_decisions_from_node_recursive(succ, copy.deepcopy(prev_decisions + [succ]))
                tmp_result += successor_paths
            return tmp_result

    return function_node, get_decisions_from_node_recursive(function_node, [])


def __parallel_get_decisions_from_node(function_node: int) -> Tuple[int, List[List[int]]]:
    global global_graph
    global global_arguments

    # connected decisions in sets
    decision_sets: List[Set[int]] = []

    queue: List[int] = [function_node]
    visited: Set[int] = set()

    while len(queue) > 0:
        current = queue.pop(0)
        visited.add(current)
        queue += [c for c in get_children(global_graph, current) if c not in queue and c not in visited]
        queue += [s for s in get_successors(global_graph, current) if s not in queue and s not in visited]

        alternatives = set(get_out_mutex_edges(global_graph, current)).union(
            set(get_in_mutex_edges(global_graph, current))
        )
        if len(alternatives) == 0:
            continue
        # check if an existing decision set needs to be extended
        found_existing = False
        for idx, dcs in enumerate(decision_sets):
            if len(dcs.intersection(alternatives)) > 0:
                found_existing = True
                decision_sets[idx] = decision_sets[idx].union(alternatives)
        if not found_existing:
            decision_sets.append(alternatives)

    # convert sets to lists
    decision_lists: List[List[int]] = []
    for ds in decision_sets:
        decision_lists.append(list(ds))

    return function_node, decision_lists


#    def get_decisions_from_node(node_id, prev_decisions: List[int]) -> List[List[int]]:
#        children_paths: List[List[int]] = []
#        # get decisions from children
#        for child in get_children(global_graph, node_id):
#            children_paths += get_decisions_from_node(child, copy.deepcopy(prev_decisions))
#        # get decisions from current node
#        successors = get_successors(global_graph, node_id)
#        successor_paths: List[List[int]] = []
#        if len(successors) == 1:
#            if len(children_paths) > 0:
#                for cp in children_paths:
#                    successor_paths += get_decisions_from_node(successors[0], copy.deepcopy(cp))
#            else:
#                successor_paths += get_decisions_from_node(successors[0], copy.deepcopy(prev_decisions))
#            return successor_paths
#        elif len(successors) == 0:
#            if len(children_paths) > 0:
#                return children_paths
#            else:
#                return [prev_decisions]
#        else:
#            tmp_result = []
#            if len(children_paths) > 0:
#                for cp in children_paths:
#                    successor_paths = []
#                    for succ in successors:
#                        successor_paths += get_decisions_from_node(succ, copy.deepcopy(cp + [succ]))
#                    tmp_result += successor_paths
#            else:
#                successor_paths = []
#                for succ in successors:
#                    successor_paths += get_decisions_from_node(succ, copy.deepcopy(prev_decisions + [succ]))
#                tmp_result += successor_paths
#            return tmp_result

# return function_node, get_decisions_from_node(function_node, [])
