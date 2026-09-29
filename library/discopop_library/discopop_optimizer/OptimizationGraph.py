# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import tkinter as tk
from typing import Dict, cast, List, Tuple, Optional, Any

import jsonpickle  # type: ignore
import networkx as nx  # type: ignore
import sympy  # type: ignore
from spb import plot3d, MB  # type: ignore
from sympy import Integer, Expr, Symbol, lambdify, plot, Float, init_printing, simplify, diff  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.CostModels.DataTransfer.DataTransferCosts import (
    add_data_transfer_costs,
)
from discopop_library.discopop_optimizer.CostModels.utilities import (
    get_performance_models_for_functions,
)
from discopop_library.discopop_optimizer.DataTransfers.DataTransfers import calculate_data_transfers
from discopop_library.discopop_optimizer.PETParser.PETParser import PETParser
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.Variables.ExperimentUtils import (
    show_function_models,
    export_to_json,
    perform_headless_execution,
)
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.gui.queries.ValueTableQuery import (
    query_user_for_symbol_values,
)
from discopop_library.discopop_optimizer.suggestions.importers.main import import_suggestions
from discopop_library.discopop_optimizer.utilities.optimization.LocalOptimization.TopDown import (
    get_locally_optimized_models,
)


class OptimizationGraph(object):
    next_free_node_id: int

    def __init__(
        self,
        experiment: Experiment,
        arguments: Dict[str, Any],
        parent_frame: Optional[tk.Frame],
        destroy_window_after_execution: bool,
    ):
        # construct optimization graph from PET Graph
        # save graph in experiment
        experiment.optimization_graph, self.next_free_node_id = PETParser(experiment).parse()

        # get performance models for sequential execution
        sequential_function_performance_models = get_performance_models_for_functions(
            experiment, experiment.optimization_graph
        )
        sequential_function_performance_models_with_transfers = calculate_data_transfers(
            experiment.optimization_graph, sequential_function_performance_models, experiment
        )
        sequential_complete_performance_models = add_data_transfer_costs(
            experiment.optimization_graph,
            sequential_function_performance_models_with_transfers,
            experiment,
        )

        # import parallelization suggestions
        experiment.optimization_graph = import_suggestions(experiment)

        # perform an exhaustive search if requested
        if arguments["--exhaustive-search"]:
            # calculate performance models without data transfers
            function_performance_models = get_performance_models_for_functions(
                experiment, experiment.optimization_graph
            )

            # calculate and append necessary data transfers to the models
            function_performance_models_with_transfers = calculate_data_transfers(
                experiment.optimization_graph, function_performance_models, experiment
            )

            # calculate and append costs of data transfers to the performance models
            exhaustive_performance_models = add_data_transfer_costs(
                experiment.optimization_graph,
                function_performance_models_with_transfers,
                experiment,
            )
        else:
            exhaustive_performance_models = dict()

        # collect free symbols
        #        free_symbols: Set[Symbol] = set()
        free_symbol_ranges: Dict[Symbol, Tuple[float, float]] = dict()
        free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution] = dict()

        #        for function in complete_performance_models:
        #            for pair in complete_performance_models[function]:
        #                model, context = pair
        #                free_symbols.update(cast(List[Symbol], model.parallelizable_costs.free_symbols))
        #                free_symbols.update(cast(List[Symbol], model.sequential_costs.free_symbols))
        #                suggested_values = suggested_values | model.symbol_value_suggestions
        sorted_free_symbols = sorted(list(experiment.free_symbols), key=lambda x: x.name)

        # query user for values for free symbols
        query_results = query_user_for_symbol_values(sorted_free_symbols, experiment.suggested_values)
        for symbol, value, start_value, end_value, symbol_distribution in query_results:
            if value is not None:
                experiment.substitutions[symbol] = Float(value)
            else:
                free_symbol_ranges[symbol] = (cast(float, start_value), cast(float, end_value))
                free_symbol_distributions[symbol] = cast(FreeSymbolDistribution, symbol_distribution)

        # by default, select the sequential version of each function for substitution
        for function in sequential_complete_performance_models:
            experiment.selected_paths_per_function[function] = sequential_complete_performance_models[function][0]

        # add function symbols to list of substitutions
        # collect substitutions
        for function in experiment.selected_paths_per_function:
            # register substitution
            experiment.substitutions[cast(Symbol, function.sequential_costs)] = experiment.selected_paths_per_function[
                function
            ][0].sequential_costs
            experiment.substitutions[cast(Symbol, function.parallelizable_costs)] = (
                experiment.selected_paths_per_function[function][0].parallelizable_costs
            )

        # TODO END OF DUMMY

        # set free symbol ranges and distributions for comparisons
        #        for idx, function in enumerate(complete_performance_models):
        #            for pair in complete_performance_models[function]:
        #                model, context = pair
        #                model.free_symbol_ranges = free_symbol_ranges
        #                model.free_symbol_distributions = free_symbol_distributions

        # save substitutions, sorted_free_symbols, free_symbol_ranges and free_symbol_distributions in experiment
        experiment.sorted_free_symbols = sorted_free_symbols
        experiment.free_symbol_ranges = free_symbol_ranges
        experiment.free_symbol_distributions = free_symbol_distributions

        # create locally optimized model
        locally_optimized_models = get_locally_optimized_models(
            experiment,
            experiment.optimization_graph,
            experiment.substitutions,
            experiment,
            free_symbol_ranges,
            free_symbol_distributions,
        )

        # set free symbol ranges and distributions for comparisons
        for idx, function in enumerate(locally_optimized_models):
            for pair in locally_optimized_models[function]:
                model, context = pair
                model.free_symbol_ranges = free_symbol_ranges
                model.free_symbol_distributions = free_symbol_distributions

        # set free symbol ranges and distributions for comparisons
        for idx, function in enumerate(exhaustive_performance_models):
            for pair in exhaustive_performance_models[function]:
                model, context = pair
                model.free_symbol_ranges = free_symbol_ranges
                model.free_symbol_distributions = free_symbol_distributions

        # find the minimum of the exhaustive list of models
        exhaustive_minima: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]] = dict()
        if len(exhaustive_performance_models) > 0:
            print("Sorting exhaustive models...")
            for function in exhaustive_performance_models:
                sorted_exhaustive_performance_models = sorted(
                    exhaustive_performance_models[function], key=lambda x: x[0]
                )
                exhaustive_minima[function] = [sorted_exhaustive_performance_models[0]]
            print("\tDone.")

        for function in sequential_complete_performance_models:
            # show table of options
            options: List[Tuple[CostModel, ContextObject, str]] = []
            # add exhaustive minima
            if function in exhaustive_minima:
                for model_tmp in exhaustive_minima[function]:
                    options.append((model_tmp[0], model_tmp[1], "Exhaustive Min"))

            options.append(
                (
                    sequential_complete_performance_models[function][0][0],
                    sequential_complete_performance_models[function][0][1],
                    "Sequential",
                )
            )
            if function in locally_optimized_models:
                options.append(
                    (
                        locally_optimized_models[function][0][0],
                        locally_optimized_models[function][0][1],
                        "Locally Optimized",
                    )
                )
            # save options to experiment
            experiment.function_models[function] = options

        # show function models
        if not arguments["--headless-mode"]:
            if parent_frame is None:
                raise ValueError("No frame provided!")
            show_function_models(experiment, parent_frame, destroy_window_after_execution)
        else:
            # perform actions for headless mode
            perform_headless_execution(experiment)

    def get_next_free_node_id(self) -> int:
        buffer = self.next_free_node_id
        self.next_free_node_id += 1
        return buffer
