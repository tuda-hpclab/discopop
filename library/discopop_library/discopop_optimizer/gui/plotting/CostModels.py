# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
from typing import List, Dict, Tuple, Optional, cast

import matplotlib  # type: ignore
import numpy as np
import sympy  # type: ignore
from matplotlib import pyplot as plt  # type: ignore
from spb import plot3d, MB, plot  # type: ignore
from sympy import Integer
from sympy import Symbol, Expr

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment


def plot_CostModels(
    experiment: Experiment,
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
    super_title: Optional[str] = None,
) -> None:
    local_sorted_free_symbols = copy.deepcopy(sorted_free_symbols)
    local_free_symbol_ranges = copy.deepcopy(free_symbol_ranges)
    for symbol in experiment.substitutions:
        if symbol in experiment.free_symbols:
            experiment.free_symbols.remove(symbol)
        if symbol in local_free_symbol_ranges:
            del local_free_symbol_ranges[symbol]
        if symbol in local_sorted_free_symbols:
            local_sorted_free_symbols.remove(symbol)

    # apply selected substitutions
    # collect substitutions
    local_substitutions = copy.deepcopy(experiment.substitutions)
    for function in experiment.selected_paths_per_function:
        # register substitution
        local_substitutions[cast(Symbol, function.sequential_costs)] = experiment.selected_paths_per_function[function][
            0
        ].sequential_costs
        local_substitutions[cast(Symbol, function.parallelizable_costs)] = experiment.selected_paths_per_function[
            function
        ][0].parallelizable_costs

    local_models = copy.deepcopy(models)

    # perform iterative substitutions
    modification_found = True
    while modification_found:
        modification_found = False
        for model in local_models:
            # apply substitution to parallelizable costs
            tmp_model = model.parallelizable_costs.subs(local_substitutions)
            if tmp_model != model.parallelizable_costs:
                modification_found = True
            model.parallelizable_costs = tmp_model

            # apply substitutions to sequential costs
            tmp_model = model.sequential_costs.subs(local_substitutions)
            if tmp_model != model.sequential_costs:
                modification_found = True
            model.sequential_costs = model.sequential_costs.subs(local_substitutions)

    # replace Expr(0) with 0
    for model in local_models:
        model.sequential_costs = model.sequential_costs.subs({Expr(Integer(0)): Integer(0)})
        model.parallelizable_costs = model.parallelizable_costs.subs({Expr(Integer(0)): Integer(0)})

    if len(local_sorted_free_symbols) == 2:
        __3d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=str(title) + str(super_title) if super_title is not None else title,
        )
    elif len(local_sorted_free_symbols) == 1:
        __2d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=str(title) + str(super_title) if super_title is not None else title,
        )
    elif len(local_sorted_free_symbols) == 0:
        __1d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=title,
            super_title=super_title,
        )
    else:
        print("Plotiting not supported for", len(sorted_free_symbols), "free symbols!")


def plot_CostModels_using_function_path_selections(
    experiment: Experiment,
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
    super_title: Optional[str] = None,
) -> None:
    # apply selected substitutions
    # collect substitutions
    local_substitutions = copy.deepcopy(experiment.substitutions)
    for function in experiment.selected_paths_per_function:
        # register substitution
        local_substitutions[cast(Symbol, function.sequential_costs)] = experiment.selected_paths_per_function[function][
            0
        ].sequential_costs
        local_substitutions[cast(Symbol, function.parallelizable_costs)] = experiment.selected_paths_per_function[
            function
        ][0].parallelizable_costs

    local_models = copy.deepcopy(models)

    # perform iterative substitutions
    modification_found = True
    while modification_found:
        modification_found = False
        for model in local_models:
            # apply substitution to parallelizable costs
            tmp_model = model.parallelizable_costs.subs(local_substitutions)
            if tmp_model != model.parallelizable_costs:
                modification_found = True
            model.parallelizable_costs = tmp_model

            # apply substitutions to sequential costs
            tmp_model = model.sequential_costs.subs(local_substitutions)
            if tmp_model != model.sequential_costs:
                modification_found = True
            model.sequential_costs = model.sequential_costs.subs(local_substitutions)

    # replace Expr(0) with 0
    for model in local_models:
        model.sequential_costs = model.sequential_costs.subs({Expr(Integer(0)): Integer(0)})
        model.parallelizable_costs = model.parallelizable_costs.subs({Expr(Integer(0)): Integer(0)})

    local_sorted_free_symbols = copy.deepcopy(sorted_free_symbols)
    local_free_symbol_ranges = copy.deepcopy(free_symbol_ranges)
    for symbol in experiment.substitutions:
        if symbol in experiment.free_symbols:
            experiment.free_symbols.remove(symbol)
        if symbol in local_free_symbol_ranges:
            del local_free_symbol_ranges[symbol]
        if symbol in local_sorted_free_symbols:
            local_sorted_free_symbols.remove(symbol)

    if len(local_sorted_free_symbols) == 2:
        __3d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=str(title) + str(super_title) if super_title is not None else title,
        )
    elif len(local_sorted_free_symbols) == 1:
        __2d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=str(title) + str(super_title) if super_title is not None else title,
        )
    elif len(local_sorted_free_symbols) == 0:
        __1d_plot(
            local_models,
            local_sorted_free_symbols,
            local_free_symbol_ranges,
            labels=labels,
            title=title,
            super_title=super_title,
        )
    else:
        print("Plotiting not supported for", len(local_sorted_free_symbols), "free symbols!")


def print_current_function_path_selections(experiment: Experiment) -> None:
    """Prints an overview of the currently selected paths for each function to the console"""
    print("###")
    print("SELECTIONS:")
    for function in experiment.selected_paths_per_function:
        print("\t", function.name)
        print("\t\t", experiment.selected_paths_per_function[function][0].path_decisions)
    print("###")


def print_current_substitutions(experiment: Experiment) -> None:
    """Prints an overview of the currently selected paths for each function to the console"""
    print("###")
    print("SUBSTITUTIONS:")
    for var in experiment.substitutions:
        print("->", var)
        print("\t", experiment.substitutions[var])
    print("###")


def print_simplified_function(
    experiment: Experiment,
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
    super_title: Optional[str] = None,
) -> None:
    """Prints an simplified mathematical function based on the current set of selections"""

    # todo: NOTE: copied from plot_CostModels_using_function_path_selections

    # apply selected substitutions
    # collect substitutions
    local_substitutions = copy.deepcopy(experiment.substitutions)
    for function in experiment.selected_paths_per_function:
        # register substitution
        local_substitutions[cast(Symbol, function.sequential_costs)] = experiment.selected_paths_per_function[function][
            0
        ].sequential_costs
        local_substitutions[cast(Symbol, function.parallelizable_costs)] = experiment.selected_paths_per_function[
            function
        ][0].parallelizable_costs

    local_models = copy.deepcopy(models)

    # perform iterative substitutions
    modification_found = True
    while modification_found:
        modification_found = False
        for model in local_models:
            # apply substitution to parallelizable costs
            tmp_model = model.parallelizable_costs.subs(local_substitutions)
            if tmp_model != model.parallelizable_costs:
                modification_found = True
            model.parallelizable_costs = tmp_model

            # apply substitutions to sequential costs
            tmp_model = model.sequential_costs.subs(local_substitutions)
            if tmp_model != model.sequential_costs:
                modification_found = True
            model.sequential_costs = model.sequential_costs.subs(local_substitutions)

    # replace Expr(0) with 0
    for model in local_models:
        model.sequential_costs = model.sequential_costs.subs({Expr(Integer(0)): Integer(0)})
        model.parallelizable_costs = model.parallelizable_costs.subs({Expr(Integer(0)): Integer(0)})

    local_sorted_free_symbols = copy.deepcopy(sorted_free_symbols)
    local_free_symbol_ranges = copy.deepcopy(free_symbol_ranges)
    for symbol in experiment.substitutions:
        if symbol in experiment.free_symbols:
            experiment.free_symbols.remove(symbol)
        if symbol in local_free_symbol_ranges:
            del local_free_symbol_ranges[symbol]
        if symbol in local_sorted_free_symbols:
            local_sorted_free_symbols.remove(symbol)

    print("###")
    print("FUNCTION:")
    for model in local_models:
        model_costs = sympy.simplify(
            sympy.re(model.parallelizable_costs + model.sequential_costs)
            + sympy.im(model.parallelizable_costs + model.sequential_costs)
        )
        print("-> ", model_costs)
    print("###")


__unique_plot_id = 0


def __1d_plot(
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
    super_title: Optional[str] = None,
) -> None:
    global __unique_plot_id
    matplotlib.use("TkAgg")
    # Make a dataset from models:
    height: List[float] = []
    bars: List[str] = []

    for idx, model in enumerate(models):
        model_label = str(model.path_decisions) if labels is None else labels[idx]
        bars.append(model_label)

        # get numeric value from model
        num_value = float(
            sympy.re(model.sequential_costs.evalf() + model.parallelizable_costs.evalf())
            + sympy.im(model.sequential_costs.evalf() + model.parallelizable_costs.evalf())
        )
        height.append(num_value)

    bars_tuple = tuple(bars)
    y_pos = np.arange(len(bars_tuple))

    # Create bars
    plt.figure(__unique_plot_id)
    __unique_plot_id += 1
    if title is not None:
        plt.title(title)  # type: ignore
    if super_title is not None:
        plt.suptitle(super_title)  # type: ignore
    plt.bar(y_pos, height)  # type: ignore
    # Create names on the x-axis
    plt.xticks(y_pos, bars_tuple)
    # Show graphic
    plt.show()


def __2d_plot(
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> None:
    matplotlib.use("TkAgg")
    combined_plot = None
    for idx, model in enumerate(models):
        model_label = str(model.path_decisions) if labels is None else labels[idx]
        model_costs = sympy.re(model.parallelizable_costs + model.sequential_costs) + sympy.im(
            model.parallelizable_costs + model.sequential_costs
        )
        if combined_plot is None:
            combined_plot = plot(
                model_costs,
                (
                    sorted_free_symbols[0],
                    free_symbol_ranges[sorted_free_symbols[0]][0],
                    free_symbol_ranges[sorted_free_symbols[0]][1],
                ),
                show=False,
                backend=MB,
                label=model_label,
                ylabel="Execution time [us]",
                title=title,
            )
        else:
            combined_plot.extend(
                plot(
                    model_costs,
                    (
                        sorted_free_symbols[0],
                        free_symbol_ranges[sorted_free_symbols[0]][0],
                        free_symbol_ranges[sorted_free_symbols[0]][1],
                    ),
                    show=False,
                    backend=MB,
                    label=model_label,
                    ylabel="Execution time [us]",
                )
            )
    combined_plot.show()  # type: ignore


def __3d_plot(
    models: List[CostModel],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    labels: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> None:
    matplotlib.use("TkAgg")
    combined_plot = None
    for idx, model in enumerate(models):
        model_label = str(model.path_decisions) if labels is None else labels[idx]
        model_costs = sympy.re(model.parallelizable_costs + model.sequential_costs) + sympy.im(
            model.parallelizable_costs + model.sequential_costs
        )
        if combined_plot is None:
            combined_plot = plot3d(
                model_costs,
                (
                    sorted_free_symbols[0],
                    free_symbol_ranges[sorted_free_symbols[0]][0],
                    free_symbol_ranges[sorted_free_symbols[0]][1],
                ),
                (
                    sorted_free_symbols[1],
                    free_symbol_ranges[sorted_free_symbols[1]][0],
                    free_symbol_ranges[sorted_free_symbols[1]][1],
                ),
                show=False,
                backend=MB,
                label=model_label,
                zlabel="Execution time [us]",
                title=title,
            )
        else:
            combined_plot.extend(
                plot3d(
                    model_costs,
                    (
                        sorted_free_symbols[0],
                        free_symbol_ranges[sorted_free_symbols[0]][0],
                        free_symbol_ranges[sorted_free_symbols[0]][1],
                    ),
                    (
                        sorted_free_symbols[1],
                        free_symbol_ranges[sorted_free_symbols[1]][0],
                        free_symbol_ranges[sorted_free_symbols[1]][1],
                    ),
                    show=False,
                    backend=MB,
                    label=model_label,
                    zlabel="Execution time [us]",
                )
            )
    combined_plot.show()  # type: ignore
