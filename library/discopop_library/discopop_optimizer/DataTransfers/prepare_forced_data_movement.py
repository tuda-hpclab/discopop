# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.discopop_optimizer.DataTransfers.prepare_force_branch_end_data_movement import (
    prepare_force_branch_end_data_movement,
)
from discopop_library.discopop_optimizer.DataTransfers.prepare_forced_data_movement_prior_to_call import (
    prepare_forced_data_movement_prior_to_call,
)
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
import networkx as nx  # type: ignore


def prepare_forced_data_movement(experiment: Experiment) -> nx.DiGraph:
    experiment.optimization_graph = prepare_force_branch_end_data_movement(experiment)

    # experiment.optimization_graph = prepare_forced_data_movement_prior_to_call(experiment)

    return experiment.optimization_graph
