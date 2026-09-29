# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.suggestions.importers.do_all import (
    import_suggestion as import_doall,
)
from discopop_library.discopop_optimizer.suggestions.importers.reduction import (
    import_suggestion as import_reduction,
)


def import_suggestions(experiment: Experiment) -> nx.DiGraph:
    """Imports the suggestions specified in res into the graph stored in the given experiment and returns the modified graph"""

    # import do-all
    buffer = copy.deepcopy(experiment.detection_result.patterns.do_all)
    for do_all_suggestion in buffer:
        experiment.optimization_graph = import_doall(
            experiment.optimization_graph, do_all_suggestion, experiment.get_next_free_node_id, experiment
        )

    # import reduction
    for reduction_suggestion in experiment.detection_result.patterns.reduction:
        experiment.optimization_graph = import_reduction(
            experiment.optimization_graph, reduction_suggestion, experiment.get_next_free_node_id, experiment
        )
    return experiment.optimization_graph
