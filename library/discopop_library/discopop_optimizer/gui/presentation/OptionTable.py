# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import tkinter
from tkinter import *
from typing import List, Tuple, Dict, Optional, cast

import networkx as nx  # type: ignore
from sympy import Symbol  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.gui.plotting.CostModels import (
    plot_CostModels,
    plot_CostModels_using_function_path_selections,
    print_current_function_path_selections,
    print_current_substitutions,
    print_simplified_function,
)
from discopop_library.discopop_optimizer.gui.presentation.ChoiceDetails import (
    display_choices_for_model,
)
from discopop_library.discopop_optimizer.utilities.optimization.GlobalOptimization.RandomSamples import (
    find_quasi_optimal_using_random_samples,
)


def show_options(
    pet: PEGraphX,
    graph: nx.DiGraph,
    experiment: Experiment,
    options: List[Tuple[CostModel, ContextObject, str]],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution],
    function_root: FunctionRoot,
    parent_frame: tkinter.Frame,
    spawned_windows: List[tkinter.Toplevel],
    window_title: Optional[str] = None,
) -> List[Tuple[CostModel, ContextObject, str]]:
    """Shows a tkinter table to browse and plot models"""
    # root = tkinter.Toplevel()
    # if window_title is not None:
    #    root.configure()
    #    root.title(window_title)
    root = tkinter.Toplevel(parent_frame.winfo_toplevel())
    spawned_windows.append(root)
    root.configure()
    root.title(window_title)

    rows = []
    column_headers = ["Label", "Decisions", "Options"]
    # set column headers
    header_cols = []
    for col_idx, header in enumerate(column_headers):
        e = Entry(root, relief=RIDGE)
        e.grid(row=0, column=col_idx, sticky=NSEW)
        e.insert(END, header)
        e.configure(state=DISABLED, disabledforeground="black")
        header_cols.append(e)
    rows.append(header_cols)

    label1 = Entry(root, relief=RIDGE)
    label1.grid(row=1, column=0, sticky=NSEW)
    label1.insert(END, "Current selection:")
    label1.configure(state=DISABLED, disabledforeground="black")

    label2 = Entry(root, relief=RIDGE)
    label2.grid(row=1, column=1, sticky=NSEW)
    label2.insert(END, str(experiment.selected_paths_per_function[function_root][0].path_decisions))
    label2.configure(state=DISABLED, disabledforeground="black")

    plot_button = Button(
        root,
        text="Plot using selections",
        command=lambda: plot_CostModels_using_function_path_selections(  # type: ignore
            experiment,
            [experiment.selected_paths_per_function[function_root][0]],  # type: ignore
            sorted_free_symbols,
            free_symbol_ranges,
            [function_root.name],
            title=function_root.name,
            super_title=function_root.name,
        ),
    )
    plot_button.grid(row=1, column=2, sticky=NSEW)

    print_selections_button = Button(
        root,
        text="Print selections",
        command=lambda: print_current_function_path_selections(  # type: ignore
            experiment,
        ),
    )
    print_selections_button.grid(row=1, column=3, sticky=NSEW)

    print_substitutions_button = Button(
        root,
        text="Print substitutions",
        command=lambda: print_current_substitutions(  # type: ignore
            experiment,
        ),
    )
    print_substitutions_button.grid(row=1, column=4, sticky=NSEW)

    print_simplified_function_button = Button(
        root,
        text="Print simplified",
        command=lambda: print_simplified_function(  # type: ignore
            experiment,
            [experiment.selected_paths_per_function[function_root][0]],  # type: ignore
            sorted_free_symbols,
            free_symbol_ranges,
            [function_root.name],
            title=function_root.name,
            super_title=function_root.name,
        ),
    )
    print_simplified_function_button.grid(row=1, column=5, sticky=NSEW)

    Button(
        root,
        text="Plot All",
        command=lambda: plot_CostModels(
            experiment,
            [t[0] for t in options],
            sorted_free_symbols,
            free_symbol_ranges,
            [t[2] for t in options],
            title="Full Plot",
            super_title=function_root.name,
        ),
    ).grid()  # type: ignore
    Button(
        root,
        text="Add Random (10)",
        command=lambda: add_random_models(
            root,
            pet,
            graph,
            experiment,
            [opt for opt in options if not opt[2].startswith("Rand ")],
            sorted_free_symbols,
            free_symbol_ranges,
            free_symbol_distributions,
            function_root,
            parent_frame,
            spawned_windows,
            window_title,
        ),
    ).grid()
    Button(root, text="Save Models", command=lambda: __save_models(experiment, function_root, options)).grid()
    Button(root, text="Close", command=lambda: root.destroy()).grid()

    # create option entries
    for row_idx, option_tuple in enumerate(options):
        option, context, option_name = option_tuple
        row_idx = row_idx + 1 + 5  # to account for column headers
        label = Entry(root, relief=RIDGE)
        label.grid(row=row_idx, column=0, sticky=NSEW)
        label.insert(END, option_name)
        label.configure(state=DISABLED, disabledforeground="black")

        decisions = Entry(root, relief=RIDGE)
        decisions.grid(row=row_idx, column=1, sticky=NSEW)
        decisions.insert(END, str(option.path_decisions))
        decisions.configure(state=DISABLED, disabledforeground="black")

        options_field = Entry(root, relief=RIDGE)
        options_field.grid(row=row_idx, column=2, sticky=NSEW)
        options_field.configure(state=DISABLED, disabledforeground="black")

        plot_button = Button(
            options_field,
            text="Plot",
            command=lambda opt=option, opt_name=option_name: plot_CostModels(  # type: ignore
                experiment,
                [opt],  # type: ignore
                sorted_free_symbols,
                free_symbol_ranges,
                [opt_name],
                title=opt_name,
                super_title=function_root.name,
            ),
        )
        plot_button.grid(row=0, column=0)
        details_button = Button(
            options_field,
            text="Details",
            command=lambda opt=option, opt_name=option_name: display_choices_for_model(  # type: ignore
                graph, opt, window_title=opt_name  # type: ignore
            ),
        )
        details_button.grid(row=0, column=1)

        export_code_button = Button(
            options_field,
            text="Export Code",
            command=lambda opt=option, opt_name=option_name, ctx=context: export_code(  # type: ignore
                pet, graph, experiment, opt, ctx, opt_name, function_root
            ),
        )
        export_code_button.grid(row=0, column=2)

        def __update_selection(cm: CostModel, ctx: ContextObject) -> None:
            experiment.selected_paths_per_function[function_root] = (cm, ctx)
            experiment.substitutions[cast(Symbol, function_root.sequential_costs)] = (
                experiment.selected_paths_per_function[function_root][0].sequential_costs
            )
            experiment.substitutions[cast(Symbol, function_root.parallelizable_costs)] = (
                experiment.selected_paths_per_function[function_root][0].parallelizable_costs
            )
            # update displayed value
            label2.configure(state=NORMAL)
            label2.delete(0, END)
            label2.insert(0, str(cm.path_decisions))
            label2.configure(state=DISABLED)

        update_selection_button = Button(
            options_field,
            text="Update selection",
            command=lambda opt=option, opt_name=option_name, ctx=context: __update_selection(opt, ctx),  # type: ignore
        )
        update_selection_button.grid(row=0, column=3)

    root.mainloop()

    return options


def __save_models(
    experiment: Experiment,
    function_root: FunctionRoot,
    options: List[Tuple[CostModel, ContextObject, str]],
) -> None:
    print("SAVE: ", function_root)
    print("\ttype; ", type(function_root))
    experiment.function_models[function_root] = options
    print("Saved models for: ", function_root.name)


def add_random_models(
    root: Optional[tkinter.Toplevel],
    pet: PEGraphX,
    graph: nx.DiGraph,
    experiment: Experiment,
    conserve_options: List[Tuple[CostModel, ContextObject, str]],
    sorted_free_symbols: List[Symbol],
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]],
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution],
    function_root: FunctionRoot,
    parent_frame: Optional[tkinter.Frame],
    spawned_windows: List[tkinter.Toplevel],
    window_title: Optional[str] = None,
    show_results: bool = True,
) -> List[Tuple[CostModel, ContextObject, str]]:
    if root is not None:
        # close window
        root.destroy()

    # generate random models
    # sort random models
    # add models to the list of options
    random_paths = 10  # amount of random models to be generated

    (
        minimum,
        maximum,
        median,
        lower_quartile,
        upper_quartile,
    ) = find_quasi_optimal_using_random_samples(
        experiment,
        graph,
        function_root,
        random_paths,
        sorted_free_symbols,
        free_symbol_ranges,
        free_symbol_distributions,
        verbose=True,
    )
    conserve_options.append((minimum[0], minimum[1], "Rand Minimum"))
    conserve_options.append((maximum[0], maximum[1], "Rand Maximum"))
    conserve_options.append((median[0], median[1], "Rand Median"))
    conserve_options.append((lower_quartile[0], lower_quartile[1], "Rand 25% Quartile"))
    conserve_options.append((upper_quartile[0], upper_quartile[1], "Rand 75% Quartile"))

    # plot
    if show_results:
        show_options(
            pet,
            graph,
            experiment,
            conserve_options,
            sorted_free_symbols,
            free_symbol_ranges,
            free_symbol_distributions,
            function_root,
            cast(tkinter.Frame, parent_frame),  # valid due to show_results flag
            spawned_windows,
            window_title,
        )

    return conserve_options
