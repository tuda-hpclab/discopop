# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import json
import os
import pickle
import tkinter as tk
from tkinter import Button
from typing import Dict, List, Optional, Tuple, cast

import jsonpickle  # type: ignore
import jsons  # type: ignore
from sympy import Float, Symbol  # type: ignore
from discopop_explorer.json_serializer import PatternBaseSerializer  # type: ignore
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.CostModels.DataTransfer.DataTransferCosts import add_data_transfer_costs
from discopop_library.discopop_optimizer.CostModels.utilities import get_performance_models_for_functions
from discopop_library.discopop_optimizer.DataTransfers.DataTransfers import calculate_data_transfers  # type: ignore
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.PETParser.PETParser import PETParser  # type: ignore

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.system.System import System
from discopop_library.discopop_optimizer.gui.presentation.OptionTable import (
    show_options,
    add_random_models,
)
from discopop_library.discopop_optimizer.gui.queries.ValueTableQuery import query_user_for_symbol_values
from discopop_library.discopop_optimizer.gui.widgets.ScrollableFrame import ScrollableFrameWidget
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.result_classes.DetectionResult import DetectionResult


def show_function_models(
    experiment: Experiment,
    parent_frame: tk.Frame,
    destroy_window_after_execution: bool,
    show_functions: Optional[List[FunctionRoot]] = None,
) -> None:
    considered_functions = show_functions if show_functions is not None else experiment.function_models
    # show function selection dialogue
    parent_frame.rowconfigure(0, weight=1)
    parent_frame.rowconfigure(1, weight=1)
    parent_frame.columnconfigure(1, weight=1)
    parent_frame.columnconfigure(0, weight=1)

    scrollable_frame_widget = ScrollableFrameWidget(parent_frame)
    scrollable_frame = scrollable_frame_widget.get_scrollable_frame()

    spawned_windows: List[tk.Toplevel] = []

    # populate scrollable frame
    for idx, function in enumerate(considered_functions):
        function_button = Button(
            scrollable_frame,
            text=function.name,
            command=lambda func=function: show_options(  # type: ignore
                # random options might be added by show_options
                experiment.detection_result.pet,
                experiment.optimization_graph,
                experiment,
                experiment.function_models[func],
                experiment.sorted_free_symbols,
                experiment.free_symbol_ranges,
                experiment.free_symbol_distributions,
                func,
                parent_frame,
                spawned_windows,
                window_title="Function: " + func.name,
            ),
        )
        function_button.grid(row=idx, column=0)

    # finalize scrollable frame
    scrollable_frame_widget.finalize(row_count=len(considered_functions), row=0, col=0)

    def __on_press() -> None:
        for w in spawned_windows:
            try:
                w.destroy()
            except tk.TclError:
                pass
        if destroy_window_after_execution:
            for c in parent_frame.winfo_children():
                c.destroy()
            parent_frame.winfo_toplevel().destroy()
        else:
            parent_frame.quit()

    # add exit button
    exit_button = Button(parent_frame, text="Exit", command=lambda: __on_press())  # type: ignore
    exit_button.grid(row=1, column=0)

    parent_frame.mainloop()


def perform_headless_execution(
    experiment: Experiment,
) -> None:
    print("Headless execution...")
    for function in experiment.function_models:
        print("\t", function.name)
        # generate random models
        updated_options = add_random_models(
            None,
            experiment.detection_result.pet,
            experiment.optimization_graph,
            experiment,
            experiment.function_models[function],
            experiment.sorted_free_symbols,
            experiment.free_symbol_ranges,
            experiment.free_symbol_distributions,
            function,
            None,
            [],
            show_results=False,
        )

        # save models
        experiment.function_models[function] = updated_options


def export_to_json(experiment: Experiment, export_path: str) -> None:
    # convert functionRoot in function_models to node ids
    to_be_added = []
    to_be_deleted = []
    for old_key in experiment.function_models:
        new_key = old_key.node_id
        to_be_added.append((new_key, experiment.function_models[old_key]))
        to_be_deleted.append(old_key)

    for k1 in to_be_deleted:
        del experiment.function_models[k1]
    for k2, v in to_be_added:
        experiment.function_models[k2] = v  # type: ignore

    experiment_dump_path: str = os.path.join(export_path, "last_experiment.pickle")
    if not os.path.exists(export_path):
        os.makedirs(export_path)
    pickle.dump(experiment, open(experiment_dump_path, "wb"))


def export_patterns_to_json(experiment: Experiment, export_path: str) -> None:
    detection_result_copy = copy.deepcopy(experiment.detection_result)
    # pet is not serializable and needs to be deleted
    del detection_result_copy.pet
    with open(export_path, "w+") as f:
        json.dump(detection_result_copy, f, indent=2, cls=PatternBaseSerializer)


def export_detection_result_to_json(experiment: Experiment, export_path: str) -> None:
    with open(export_path, "w+") as f:
        f.write(experiment.detection_result.dump_to_pickled_json())
        f.flush()
        f.close()


def restore_session(json_file: str) -> Experiment:
    experiment: Experiment = pickle.load(open(json_file, "rb"))

    # convert keys of function_models to FunctionRoot objects
    to_be_added = []
    to_be_deleted = []
    for old_key in experiment.function_models:
        new_key = cast(FunctionRoot, data_at(experiment.optimization_graph, cast(int, old_key)))
        to_be_added.append((new_key, experiment.function_models[old_key]))
        to_be_deleted.append(old_key)

    for k, v in to_be_added:
        experiment.function_models[k] = v
    for k in to_be_deleted:
        del experiment.function_models[k]

    return experiment


def create_optimization_graph(experiment: Experiment, arguments: OptimizerArguments) -> None:
    if arguments.verbose:
        print("Creating optimization graph...", end="")
    pet_parser = PETParser(experiment)
    experiment.optimization_graph, experiment.next_free_node_id = pet_parser.parse()
    if arguments.verbose:
        print("Done.")


def get_sequential_cost_model(experiment: Experiment) -> Dict[FunctionRoot, List[Tuple[CostModel, ContextObject]]]:
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
    return sequential_complete_performance_models


def initialize_free_symbol_ranges_and_distributions(
    experiment: Experiment, arguments: OptimizerArguments, system: System
) -> None:
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]] = dict()
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution] = dict()
    sorted_free_symbols = sorted(list(experiment.free_symbols), key=lambda x: x.name)
    symbol_values: List[
        Tuple[
            Symbol,
            Optional[float],
            Optional[float],
            Optional[float],
            Optional[FreeSymbolDistribution],
        ]
    ] = []

    if arguments.interactive:
        symbol_values = query_user_for_symbol_values(sorted_free_symbols, experiment.suggested_values)
    else:
        # use the suggested values
        for symbol in sorted_free_symbols:
            # check if symbol is already defined by the system
            found_symbol = False
            for entry in system.get_symbol_values_and_distributions():
                if entry[0] == symbol:
                    symbol_values.append(entry)
                    found_symbol = True
                    break
            if not found_symbol:
                # else, use a default value for non-system symbols
                symbol_values.append((symbol, experiment.suggested_values[symbol].evalf(), None, None, None))

    for symbol, value, start_value, end_value, symbol_distribution in symbol_values:
        if value is not None:
            experiment.substitutions[symbol] = Float(value)
        else:
            experiment.free_symbol_ranges[symbol] = (cast(float, start_value), cast(float, end_value))
            experiment.free_symbol_distributions[symbol] = cast(FreeSymbolDistribution, symbol_distribution)
