# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
from typing import List, Dict, Tuple

import networkx as nx  # type: ignore
from spb import plot3d, MB, plot  # type: ignore
from sympy import Symbol  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.CostModels.utilities import get_random_path
from discopop_library.discopop_optimizer.DataTransfers.DataTransfers import calculate_data_transfers
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot


def find_quasi_optimal_using_random_samples(
    experiment: Experiment,
    graph: nx.DiGraph,
    function_root: FunctionRoot,
    random_path_count: int,
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution],
    verbose: bool = False,
) -> Tuple[
    Tuple[CostModel, ContextObject],
    Tuple[CostModel, ContextObject],
    Tuple[CostModel, ContextObject],
    Tuple[CostModel, ContextObject],
    Tuple[CostModel, ContextObject],
]:
    """Returns the identified minimum, maximum, median, 25% quartile and 75% quartile of the random_path_count samples.
    NOTE: The decisions should be treated as suggestions, not mathematically accurate decisions
    due to the used comparison method!"""
    random_paths: List[Tuple[CostModel, ContextObject]] = []
    if verbose:
        print("Generating ", random_path_count, "random paths")
    i = 0
    # create a temporary copy of the substitutions list to roll back unwanted modifications
    substitutions_buffer = copy.deepcopy(experiment.substitutions)
    while i < random_path_count:
        # reset substitutions
        experiment.substitutions = copy.deepcopy(substitutions_buffer)

        tmp_dict = dict()
        tmp_dict[function_root] = [get_random_path(experiment, graph, function_root.node_id, must_contain=None)]
        try:
            random_paths.append(calculate_data_transfers(graph, tmp_dict, experiment)[function_root][0])
            i += 1
        except ValueError as ve:
            if verbose:
                print(ve)
            # might occur as a result of invalid paths due to restrictions
            pass
    # reset substitutions
    experiment.substitutions = copy.deepcopy(substitutions_buffer)

    # apply substitutions and set free symbol ranges and distributions
    if verbose:
        print("\tApplying substitutions...")

    random_paths_with_substitutions: List[Tuple[CostModel, ContextObject, CostModel]] = []
    for model, context in random_paths:
        substituted_model = copy.deepcopy(model)

        # apply substitutions iteratively
        modification_found = True
        while modification_found:
            modification_found = False
            # apply substitutions to parallelizable costs
            tmp_model = substituted_model.parallelizable_costs.subs(experiment.substitutions)
            if tmp_model != substituted_model.parallelizable_costs:
                modification_found = True
            substituted_model.parallelizable_costs = tmp_model

            # apply substitutions to sequential costs
            tmp_model = substituted_model.sequential_costs.subs(experiment.substitutions)
            if tmp_model != substituted_model.sequential_costs:
                modification_found = True
            substituted_model.sequential_costs = tmp_model
        substituted_model.free_symbol_ranges = free_symbol_ranges
        substituted_model.free_symbol_distributions = free_symbol_distributions

        random_paths_with_substitutions.append((model, context, substituted_model))

    if verbose:
        print("\tSorting...")
    sorted_list = sorted(random_paths_with_substitutions, key=lambda x: x[2])  # BOTTLENECK!
    if verbose:
        print("\tDone.")
    minimum = (sorted_list[0][0], sorted_list[0][1])
    maximum = (sorted_list[-1][0], sorted_list[-1][1])
    median = (sorted_list[int(len(sorted_list) / 2)][0], sorted_list[int(len(sorted_list) / 2)][1])
    upper_quartile = (
        sorted_list[int(len(sorted_list) / 4 * 3)][0],
        sorted_list[int(len(sorted_list) / 4 * 3)][1],
    )
    lower_quartile = (
        sorted_list[int(len(sorted_list) / 4 * 1)][0],
        sorted_list[int(len(sorted_list) / 4 * 1)][1],
    )

    return minimum, maximum, median, lower_quartile, upper_quartile
