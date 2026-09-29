# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Set, Tuple, cast
import networkx as nx  # type: ignore
from sympy import Integer  # type: ignore
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.DeviceSwitch import DeviceSwitch
from discopop_library.discopop_optimizer.classes.nodes.SynchronizationTrigger import SynchronizationTrigger
from discopop_library.discopop_optimizer.classes.types.DataAccessType import ReadDataAccess, WriteDataAccess
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    add_successor_edge,
    get_predecessors,
    get_successors,
    redirect_edge,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


def insert_device_switch_nodes(experiment: Experiment) -> nx.DiGraph:
    print("Inserting device switch nodes")
    insert_device_switches: List[Tuple[int, int]] = []
    for node in experiment.optimization_graph.nodes:
        node_data = data_at(experiment.optimization_graph, node)
        if type(node_data) == SynchronizationTrigger:
            # ignore Synchronization triggers
            continue
        successors = get_successors(experiment.optimization_graph, node)
        for successor in successors:
            successor_data = data_at(experiment.optimization_graph, successor)
            if type(successor_data) == SynchronizationTrigger:
                # ignore Synchronization triggers
                continue
            if node_data.device_id != successor_data.device_id:
                insert_device_switches.append((node, successor))

    device_switch_nodes: List[int] = []
    already_covered: List[Tuple[int, int]] = []
    for source, target in insert_device_switches:
        if (source, target) in already_covered:
            continue

        # insert device switch after source, if it has multiple successors
        insert_after_source = len(get_successors(experiment.optimization_graph, source)) > 1
        # insert device switch before target if it has multiple predecessors
        insert_before_target = len(get_predecessors(experiment.optimization_graph, target)) > 1
        # insert inbetween, if only one successor / predecessor exists
        insert_inbetween = (
            len(get_successors(experiment.optimization_graph, source)) == 1
            and len(get_predecessors(experiment.optimization_graph, target)) == 1
        )

        if insert_after_source and insert_before_target:
            raise ValueError("Mal-formatted graph at nodes: " + str(source) + " -> " + str(target))

        if not (insert_after_source or insert_before_target or insert_inbetween):
            raise ValueError(
                "Could not determine positioning of DeviceSwitch at nodes:" + str(source) + " -> " + str(target)
            )

        # create DeviceSwitch node
        new_node_id = experiment.get_next_free_node_id()
        new_node_data = DeviceSwitch(new_node_id, experiment, None, Integer(0), Integer(0))
        experiment.optimization_graph.add_node(new_node_id, data=new_node_data)
        device_switch_nodes.append(new_node_id)

        # the following positioning is required to ensure the overall structure of the graph is kept.
        # i.e., only parallelism suggestions create branches in the successor-graph

        # position DeviceSwitch node
        if insert_inbetween:
            # insert DeviceSwitch inbetween source and target
            redirect_edge(experiment.optimization_graph, source, source, target, new_node_id)
            add_successor_edge(experiment.optimization_graph, new_node_id, target)
            new_node_data.original_cu_id = data_at(experiment.optimization_graph, target).original_cu_id
            already_covered.append((source, target))

        elif insert_after_source:
            # insert DeviceSwitch after source
            for succ in get_successors(experiment.optimization_graph, source):
                redirect_edge(experiment.optimization_graph, source, new_node_id, succ, succ)
                # note: all successors should have the same original_cu_id
                new_node_data.original_cu_id = data_at(experiment.optimization_graph, target).original_cu_id
                already_covered.append((source, succ))
            add_successor_edge(experiment.optimization_graph, source, new_node_id)

        elif insert_before_target:
            # insert DeviceSwitch before target
            for pred in get_predecessors(experiment.optimization_graph, target):
                redirect_edge(experiment.optimization_graph, pred, pred, target, new_node_id)
                already_covered.append((pred, target))
            add_successor_edge(experiment.optimization_graph, new_node_id, target)
            new_node_data.original_cu_id = data_at(experiment.optimization_graph, target).original_cu_id

    __set_read_and_write_information(experiment, device_switch_nodes)

    return experiment.optimization_graph


def __set_read_and_write_information(experiment: Experiment, device_switch_nodes: List[int]) -> None:
    """Collect and set read and write information for the device switch nodes"""
    for node in device_switch_nodes:
        # look ahead to next device switch along each path and collect the encountered reads and writes
        reads: Set[ReadDataAccess] = set()
        writes: Set[WriteDataAccess] = set()

        queue = get_successors(experiment.optimization_graph, node)
        while len(queue) > 0:
            current = queue.pop()
            current_data = data_at(experiment.optimization_graph, current)
            if type(current_data) == DeviceSwitch or type(current_data) == SynchronizationTrigger:
                # stop search along this path
                continue
            reads.update(current_data.read_memory_regions)
            writes.update(current_data.written_memory_regions)
            queue += [s for s in get_successors(experiment.optimization_graph, current) if s not in queue]

        # set collected read and write information for proper update calculation
        # important: device switch node must be a read-only node, hence the cast of "writes"
        if len(reads) + len(writes) > 0:
            node_data = data_at(experiment.optimization_graph, node)
            node_data.read_memory_regions = reads.union(cast(Set[ReadDataAccess], writes))
