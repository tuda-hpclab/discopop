# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import json
import logging
from multiprocessing import Pool
import os
from typing import Dict, List, Optional, Set, Tuple, cast

from sympy import Expr  # type: ignore
import tqdm  # type: ignore
from discopop_explorer.aliases.NodeID import NodeID

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.optimization.evaluate import evaluate_configuration
from itertools import product
from discopop_library.discopop_optimizer.optimization.validation import check_configuration_validity

from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern

logger = logging.getLogger("Optimizer")

global_experiment = None
global_arguments = None


def greedy_search(
    experiment: Experiment,
    available_decisions: Dict[FunctionRoot, List[List[int]]],
    arguments: OptimizerArguments,
    optimizer_dir: str,
) -> Optional[OptimizerOutputPattern]:
    """find a good combination of suggestions via greedy search"""
    global global_experiment
    global global_arguments
    global_experiment = experiment
    global_arguments = arguments

    # identify sequential suggestions
    # copy available decisions and convert function nodes to node ids
    sequential_suggestions: Dict[int, List[List[int]]] = dict()
    for key_1 in available_decisions:
        sequential_suggestions[key_1.node_id] = []
        for entry in available_decisions[key_1]:
            sequential_suggestions[key_1.node_id].append(copy.deepcopy(entry))

    for function in sequential_suggestions:
        for decision_set in sequential_suggestions[function]:
            to_be_removed = []
            for decision in decision_set:
                if not data_at(experiment.optimization_graph, decision).represents_sequential_version():
                    to_be_removed.append(decision)
            for entry_tbr in to_be_removed:
                decision_set.remove(entry_tbr)

            # remove all but the original version
            while len(decision_set) > 1:
                tbr = sorted(decision_set, reverse=True)[0]
                decision_set.remove(tbr)

    # copy sequential decisions
    made_decisions: Dict[int, List[List[int]]] = dict()
    made_decisions_context = None
    for key_2 in sequential_suggestions:
        made_decisions[key_2] = []
        for entry in sequential_suggestions[key_2]:
            made_decisions[key_2].append(copy.deepcopy(entry))

    for idx, function_node in enumerate(available_decisions):
        print("Greedy searching function: ", function_node.name, idx, "/", len(available_decisions))
        for dcsi, decision_set in enumerate(available_decisions[function_node]):
            print("\tDecision:", dcsi, "/", len(available_decisions[function_node]))
            local_results: List[Tuple[Dict[int, List[List[int]]], int, ContextObject]] = []

            # prepare arguments for parallel cost calculation
            param_list: List[Dict[int, List[List[int]]]] = []
            for decision in decision_set:
                # copy made decisions
                local_decision_set: Dict[int, List[List[int]]] = dict()
                for key_3 in made_decisions:
                    local_decision_set[key_3] = []
                    for entry in made_decisions[key_3]:
                        local_decision_set[key_3].append(copy.deepcopy(entry))

                local_decision_set[function_node.node_id][dcsi] = [decision]
                param_list.append(local_decision_set)

            tmp_result: List[Tuple[Dict[int, List[List[int]]], int, ContextObject]] = []
            if True:
                # calculate costs in parallel
                with Pool(initializer=__initialize_cost_caluclation_worker, initargs=(experiment, arguments)) as pool:
                    tmp_result = list(
                        tqdm.tqdm(pool.imap_unordered(__get_score, param_list), total=len(param_list), disable=True)
                    )
            else:
                # calculate costs sequentially
                tmp_result = []
                for param in param_list:
                    tmp_result.append(__get_score(param))

            for local_result in tmp_result:
                # remove invalid elements
                if local_result[1] < 0:
                    continue
                local_results.append(local_result)

            # identify best option and update made_decisions
            # sort deterministically so that ties are always resolved the same way, regardless of the
            # non-deterministic arrival order of imap_unordered() results across process runs
            local_results.sort(key=lambda item: (item[1], __get_dicision_list(item[0])))
            best_option: Optional[Tuple[Dict[int, List[List[int]]], int, ContextObject]] = None
            for k, e, c in local_results:
                dbg_decisions_string = ""
                for key in k:
                    dbg_decisions_string += str(key) + "("
                    for l in k[key]:
                        dbg_decisions_string += "[ "
                        for entry2 in l:
                            dbg_decisions_string += str(entry2)
                            entry_data = data_at(global_experiment.optimization_graph, entry2)

                            if entry_data.device_id != global_experiment.get_system().get_host_device_id():
                                dbg_decisions_string += "@" + str(entry_data.device_id)
                            if entry_data.represents_sequential_version():
                                dbg_decisions_string += "(seq)"
                            dbg_decisions_string += ", "
                        dbg_decisions_string += "] "
                    dbg_decisions_string += ") "

                logger.info("LocalResult: " + dbg_decisions_string + " -> " + str(e))
                if best_option is None:
                    best_option = (k, e, c)
                    continue
                if e < best_option[1]:
                    best_option = (k, e, c)

            assert best_option  # != None
            made_decisions = best_option[0]
            made_decisions_context = best_option[2]

            #            made_decisions = sorted(local_results, key=lambda x: x[1])[0][0]
            print("Selection: ", __get_dicision_list(made_decisions), "costs:", best_option[1])

    if made_decisions_context is None:
        return None

    # return the selected configuration
    return __get_optimizer_output_pattern(
        __get_dicision_list(made_decisions), made_decisions_context, optimizer_dir, experiment
    )


def __get_dicision_list(decisions_dict: Dict[int, List[List[int]]]) -> List[int]:
    """Converts a dictionary based description of a configuration into a list of integers"""
    res_list = []
    for function in decisions_dict:
        for decision_set in decisions_dict[function]:
            res_list.append(decision_set[0])
    return res_list


def __initialize_cost_caluclation_worker(
    experiment: Experiment,
    arguments: OptimizerArguments,
) -> None:
    global global_experiment
    global global_arguments
    global_experiment = experiment
    global_arguments = arguments


def __get_score(param_tuple: Dict[int, List[List[int]]]) -> Tuple[Dict[int, List[List[int]]], int, ContextObject]:
    global global_experiment
    global global_arguments
    configuration = param_tuple
    try:
        if check_configuration_validity(
            cast(Experiment, global_experiment),
            cast(OptimizerArguments, global_arguments),
            __get_dicision_list(configuration),
        ):
            _, score_expr, context = evaluate_configuration(
                cast(Experiment, global_experiment),
                __get_dicision_list(configuration),
                cast(OptimizerArguments, global_arguments),
            )
            result = int(float(str(score_expr.evalf())))
        else:
            # configuration is invalid
            result = -1
            context = ContextObject(-1, None)
    except ValueError:
        result = -1
        context = ContextObject(-1, None)

    return configuration, result, context


def __get_optimizer_output_pattern(
    selection: List[int], context: ContextObject, optimizer_dir: str, experiment: Experiment
) -> Optional[OptimizerOutputPattern]:
    best_configuration = None
    for node_id in selection:
        # find pattern id
        for pattern_id in experiment.suggestion_to_node_ids_dict:
            if node_id in experiment.suggestion_to_node_ids_dict[pattern_id]:
                device_id = data_at(experiment.optimization_graph, node_id).device_id
                if best_configuration is None:
                    best_configuration = OptimizerOutputPattern(
                        experiment.detection_result.pet.node_at(
                            cast(NodeID, data_at(experiment.optimization_graph, node_id).original_cu_id),
                        ),
                        [],
                        experiment.get_system().get_host_device_id(),
                        experiment,
                    )
                best_configuration.add_pattern(
                    pattern_id, device_id, experiment.get_system().get_device(device_id).get_device_type()
                )
                best_configuration.decisions.append(node_id)
    if best_configuration is None:
        # best configuration is sequential
        return OptimizerOutputPattern(
            experiment.detection_result.pet.node_at(
                cast(NodeID, data_at(experiment.optimization_graph, selection[0]).original_cu_id)
            ),
            [],
            experiment.get_system().get_host_device_id(),
            experiment,
        )
    # collect data movement information
    for update in context.necessary_updates:
        best_configuration.add_data_movement(update)
    # export results to file
    best_option_id_path: str = os.path.join(optimizer_dir, "evolutionary_pattern_id.txt")
    with open(best_option_id_path, "w+") as f:
        f.write(str(best_configuration.pattern_id))

    return best_configuration
