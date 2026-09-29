# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Set, cast

from sympy import Integer  # type: ignore
from discopop_library.discopop_optimizer.utilities.MOGUtilities import get_predecessors
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
import networkx as nx  # type: ignore
from discopop_library.discopop_optimizer.classes.nodes.ContextRestore import ContextRestore
from discopop_library.discopop_optimizer.classes.nodes.ContextSave import ContextSave
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshot import ContextSnapshot
from discopop_library.discopop_optimizer.classes.nodes.ContextSnapshotPop import ContextSnapshotPop
from discopop_library.discopop_optimizer.classes.nodes.SynchronizationTrigger import SynchronizationTrigger
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.classes.types.DataAccessType import ReadDataAccess, WriteDataAccess
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    add_successor_edge,
    get_parent_function,
    redirect_edge,
)


from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at  # type: ignore


def prepare_force_branch_end_data_movement(experiment: Experiment) -> nx.DiGraph:
    """Insert dummy reads at the end of a branch to all memory regions written within the branch.
    This forces a data synchronization whenever the branch is left"""

    all_context_save_nodes: List[int] = []
    for node in experiment.optimization_graph.nodes:
        if type(data_at(experiment.optimization_graph, node)) == ContextSave:
            all_context_save_nodes.append(node)

    for node in all_context_save_nodes:
        seen_writes: Set[WriteDataAccess] = set()
        queue = [node]
        branching_depth = 0
        while len(queue) > 0:
            current = queue.pop()
            current_data = data_at(experiment.optimization_graph, current)
            seen_writes.update(current_data.written_memory_regions)

            if branching_depth == 0 and type(current_data) == ContextRestore:
                # found entry to the exited branch
                break
            if type(current_data) == ContextSnapshotPop:
                branching_depth += 1
            if type(current_data) == ContextSnapshot:
                branching_depth -= 1
            queue += [p for p in get_predecessors(experiment.optimization_graph, current) if p not in queue]

        # get the n last cu_ids prior to node
        # multiples to allow "skipping" the branch merge node, inherited from the PE Graph, to fix the update positioning inside the branch
        queue = [node]
        last_original_cu_ids = None
        n = 2
        while len(queue) > 0:
            current = queue.pop()
            current_data = data_at(experiment.optimization_graph, current)
            if current_data.original_cu_id is not None:
                if last_original_cu_ids is None:
                    last_original_cu_ids = []
                last_original_cu_ids.append(current_data.original_cu_id)
                if len(last_original_cu_ids) == n:
                    break
            queue += [p for p in get_predecessors(experiment.optimization_graph, current) if p not in queue]
        if last_original_cu_ids is None:
            # fallback
            last_original_cu_ids = [
                data_at(
                    experiment.optimization_graph, get_parent_function(experiment.optimization_graph, current)
                ).original_cu_id
            ]

        # add a dummy node reading all written memory regions
        new_node_id = experiment.get_next_free_node_id()
        new_node_data = SynchronizationTrigger(
            new_node_id,
            experiment,
            last_original_cu_ids[-1],
            Integer(0),
            Integer(0),
            None,
            cast(Set[ReadDataAccess], seen_writes),
        )
        new_node_data.device_id = experiment.get_system().get_host_device_id()
        experiment.optimization_graph.add_node(new_node_id, data=new_node_data)

        # redirect edges predecessor->node to predecessor->dummy
        for pred in get_predecessors(experiment.optimization_graph, node):
            redirect_edge(experiment.optimization_graph, pred, pred, node, new_node_id)

        # create edge dummy->node
        add_successor_edge(experiment.optimization_graph, new_node_id, node)

    return experiment.optimization_graph
