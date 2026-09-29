# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.suggestions.optimizers.loop_collapse import collapse_loops

import networkx as nx  # type: ignore


def optimize_suggestions(experiment: Experiment) -> nx.DiGraph:
    experiment.optimization_graph = collapse_loops(experiment)
    return experiment.optimization_graph
