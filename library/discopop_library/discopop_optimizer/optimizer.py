# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import cProfile
import json
import logging
import os.path
import pstats
import shutil
from typing import Dict, List, Tuple, cast
import warnings

import jsonpickle  # type: ignore
from sympy import Float, Symbol  # type: ignore

from discopop_library.CodeGenerator.CodeGenerator import from_json_strings
from discopop_library.FolderStructure.setup import setup_optimizer
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.JSONHandler.JSONHandler import read_patterns_from_json_to_json
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.diffs import get_diffs_from_modified_code
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.discopop_optimizer.CostModels.DataTransfer.DataTransferCosts import add_data_transfer_costs
from discopop_library.discopop_optimizer.CostModels.utilities import get_performance_models_for_functions
from discopop_library.discopop_optimizer.DataTransfers.NewDataTransfers import new_calculate_data_transfers
from discopop_library.discopop_optimizer.DataTransfers.calculate_configuration_data_movement import (
    calculate_data_movement,
)
from discopop_library.discopop_optimizer.DataTransfers.prepare_force_branch_end_data_movement import (
    prepare_force_branch_end_data_movement,
)
from discopop_library.discopop_optimizer.DataTransfers.prepare_forced_data_movement import prepare_forced_data_movement
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.PETParser.PETParser import PETParser
from discopop_library.discopop_optimizer.UpdateOptimization.main import optimize_updates
from discopop_library.discopop_optimizer.Variables.ExperimentUtils import (
    create_optimization_graph,
    export_detection_result_to_json,
    export_patterns_to_json,
    export_to_json,
    get_sequential_cost_model,
    initialize_free_symbol_ranges_and_distributions,
)
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.system.system_utils import generate_default_system_configuration
from discopop_library.discopop_optimizer.gui.queries.ValueTableQuery import query_user_for_symbol_values
from discopop_library.discopop_optimizer.interactive.interactive_optimizer import run_interactive_optimizer
from discopop_library.discopop_optimizer.optimization.evaluate import evaluate_configuration
from discopop_library.discopop_optimizer.optimization.evaluate_all_decision_combinations import (
    evaluate_all_decision_combinations,
)
from discopop_library.discopop_optimizer.optimization.evolutionary_algorithm import perform_evolutionary_search
from discopop_library.discopop_optimizer.optimization.greedy import greedy_search
from discopop_library.discopop_optimizer.suggestions.optimizers.main import optimize_suggestions
from discopop_library.discopop_optimizer.utilities.insert_device_switch_nodes import insert_device_switch_nodes
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.discopop_optimizer.utilities.visualization.update_graph import show_update_graph
from discopop_library.global_data.version.utils import get_version
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.discopop_optimizer.classes.system.System import System
from discopop_library.discopop_optimizer.Microbench.ExtrapInterpolatedMicrobench import (
    ExtrapInterpolatedMicrobench,
)
from discopop_library.discopop_optimizer.Microbench.Microbench import MicrobenchType
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.utilities.MOGUtilities import (
    get_available_decisions_for_functions,
    show,
)
from discopop_library.discopop_optimizer.suggestions.importers.main import import_suggestions

from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots


def run(arguments: OptimizerArguments) -> None:
    if arguments.interactive:
        run_interactive_optimizer(arguments)
    else:
        run_passive_optimizer(arguments)


def run_passive_optimizer(arguments: OptimizerArguments) -> None:
    logger = logging.getLogger("Optimizer")

    # check prerequisites and setup folder structure
    if arguments.verbose:
        print("Started DiscoPoP Optimizer...")
        print("Creating optimizer directory...")

    setup_optimizer(os.getcwd())

    optimizer_dir = os.path.join(os.getcwd(), "optimizer")
    explorer_dir = os.path.join(os.getcwd(), "explorer")
    profiler_dir = os.path.join(os.getcwd(), "profiler")
    pattern_file_path = os.path.join(explorer_dir, "patterns.json")
    if not os.path.exists(pattern_file_path):
        raise FileNotFoundError(
            "No pattern file found. Please execute the discopop_explorer in advance."
            + "\nExpected pattern file: "
            + pattern_file_path
        )
    file_mapping_path = os.path.join(os.getcwd(), "FileMapping.txt")
    if not os.path.exists(file_mapping_path):
        raise FileNotFoundError(
            "No file mapping found. Please execute the discopop_explorer in advance."
            + "\nExpected file: "
            + file_mapping_path
        )
    if not os.path.exists(arguments.system_configuration_path):
        generate_default_system_configuration(arguments.system_configuration_path)

    # create a new session, load data from previous steps)
    if arguments.verbose:
        print("Loading file mapping...", end="")
    file_mapping = load_file_mapping(file_mapping_path)
    if arguments.verbose:
        print("Done.")

    if arguments.verbose:
        print("Loading Hotspots...")
    hotspot_functions = load_hotspots(
        HotspotLoaderArguments(
            verbose=arguments.verbose,
            dot_discopop_path=os.getcwd(),
            get_loops=False,
            get_functions=True,
            get_YES=True,
            get_MAYBE=False,
            get_NO=False,
            log_level=arguments.log_level,
            write_log=arguments.write_log,
        )
    )

    if arguments.verbose:
        print("Done.")

    if arguments.verbose:
        print("Loading patterns...", end="")
    patterns_by_type = read_patterns_from_json_to_json(pattern_file_path, [])
    if arguments.verbose:
        print("Done.")

    if arguments.verbose:
        print("Loading detection result and PET...", end="")
    detection_result_dump_str = ""
    with open(os.path.join(explorer_dir, "detection_result_dump.json")) as f:
        detection_result_dump_str = f.read()
    detection_result: DetectionResult = jsonpickle.decode(detection_result_dump_str, keys=True)

    if "version" in detection_result.__dict__:  # for backwards compatibility
        if detection_result.version != get_version():
            warnings.warn(
                "Restored DetectionResult was created using different DiscoPoP version: "
                + detection_result.version
                + "; current: "
                + get_version()
            )
    else:
        warnings.warn("Restored DetectionResult does not contain version information and might be outdated!")

    if arguments.verbose:
        print("Done")

    # define System
    # todo make system user-configurable, or detect it using a set of benchmarks
    system = System(arguments)

    # todo connections between devices might happen as update to host + update to second device.
    #  As of right now, connections between two devices are implemented in this manner.
    # todo check if OpenMP allows direct data transfers between devices

    # load overhead measurements into system if existent
    if arguments.doall_microbench_file != "None":
        # construct and set overhead model for doall suggestions
        system.set_device_doall_overhead_model(
            system.get_device(system.get_host_device_id()),
            ExtrapInterpolatedMicrobench(arguments.doall_microbench_file).getFunctionSympy(
                benchType=MicrobenchType.DOALL
            ),
            arguments,
        )
        # construct and set overhead model for doall suggestions with shaed clause
        system.set_device_doall_shared_overhead_model(
            system.get_device(system.get_host_device_id()),
            ExtrapInterpolatedMicrobench(arguments.doall_microbench_file).getFunctionSympy(
                benchType=MicrobenchType.SHARED
            ),
            arguments,
        )

    if arguments.reduction_microbench_file != "None":
        # construct and set overhead model for reduction suggestions
        system.set_reduction_overhead_model(
            system.get_device(system.get_host_device_id()),
            ExtrapInterpolatedMicrobench(arguments.reduction_microbench_file).getFunctionSympy(
                benchType=MicrobenchType.FOR
            ),
            arguments,
        )

    # define Experiment
    experiment = Experiment(file_mapping, system, detection_result, profiler_dir, arguments, hotspot_functions)

    if arguments.profiling:
        experiment.profile = cProfile.Profile()  # type: ignore
        experiment.profile.enable()  # type: ignore

    # build optimization graph
    if arguments.verbose:
        print("Creating optimization graph...")
    create_optimization_graph(experiment, arguments)

    # prepare forcing of data movement at branch end
    experiment.optimization_graph = prepare_forced_data_movement(experiment)

    if arguments.verbose:
        print("Done.")
    # import parallelization suggestions
    experiment.optimization_graph = import_suggestions(experiment)
    # optimize parallelization suggestions
    experiment.optimization_graph = optimize_suggestions(experiment)

    # insert device switch nodes
    # experiment.optimization_graph = insert_device_switch_nodes(experiment)

    if arguments.plot:
        show(experiment.optimization_graph, show_dataflow=True, show_mutex_edges=False)

    if arguments.verbose:
        print("# SUGGESTION ID -> NODE ID MAPPING")
        for suggestion_id in experiment.suggestion_to_node_ids_dict:
            print("#", suggestion_id, "->", experiment.suggestion_to_node_ids_dict[suggestion_id])
        print()

    # safety precaution: make sure the correct node ids are used everywhere
    for node_id in experiment.optimization_graph.nodes:
        node_data = data_at(experiment.optimization_graph, node_id)
        if node_id != node_data.node_id:
            node_data.node_id = node_id

    # get values for free symbols
    initialize_free_symbol_ranges_and_distributions(experiment, arguments, system)

    if arguments.verbose:
        print("# SUBSTITUTIONS:")
        for key in experiment.substitutions:
            print("#", key, " ->", experiment.substitutions[key])
        print()

    # calculate necessary updates for all created (i.e. mapped or collapsed) suggestions
    # this can get quite expensive for large software, so it should only be calculated upon request
    if arguments.single_suggestions:
        calculate_data_movement(experiment)

    # apply optimization steps if requested
    best_configuration = None
    if arguments.optimization_level != 0:
        # calculate options for easy access
        available_decisions = get_available_decisions_for_functions(experiment.optimization_graph, arguments)

        if arguments.optimization_level == 1:
            best_configuration = greedy_search(experiment, available_decisions, arguments, optimizer_dir)
        elif arguments.optimization_level == 2:
            # perform evolutionary search
            best_configuration = perform_evolutionary_search(
                experiment,
                available_decisions,
                arguments,
                optimizer_dir,
            )
        # calculate costs for all combinations of decisions
        elif arguments.optimization_level == 3:
            best_configuration = evaluate_all_decision_combinations(
                experiment, available_decisions, arguments, optimizer_dir
            )
        else:
            raise ValueError("No valid optimization method specified: " + str(arguments.optimization_level))

        print("BEST CONFIGURATION: ", best_configuration)

    if best_configuration is not None:
        # calculate updates for best_configuration
        updates = new_calculate_data_transfers(experiment.optimization_graph, best_configuration.decisions, experiment)
        # register updates
        best_configuration.data_movement = []
        for u in updates:
            best_configuration.add_data_movement(u)

        best_configuration = optimize_updates(experiment, best_configuration, arguments)
        # append the configuration to the list of patterns
        experiment.detection_result.patterns.optimizer_output.append(best_configuration)

    if arguments.profiling:
        experiment.profile.disable()  # type: ignore
        if os.path.exists("optimizer_profile.txt"):
            os.remove("optimizer_profile.txt")
        with open("optimizer_profile.txt", "w+") as f:
            stats = pstats.Stats(experiment.profile, stream=f).sort_stats("time").reverse_order()  # type: ignore
            stats.print_stats()
        del experiment.profile  # type: ignore

    # save full experiment to disk
    export_to_json(experiment, optimizer_dir)
    # save updated patterns.json to disk
    export_patterns_to_json(experiment, os.path.join(optimizer_dir, "patterns.json"))
    # save updated detection_result to disk
    export_detection_result_to_json(experiment, os.path.join(optimizer_dir, "detection_result_dump.json"))
