# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
from typing import List, Optional, Set, cast
from discopop_library.discopop_optimizer.DataTransfers.NewDataTransfers import new_calculate_data_transfers
from discopop_library.discopop_optimizer.DataTransfers.calculate_configuration_data_movement import (
    calculate_data_movement,
)
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.UpdateOptimization.main import optimize_updates
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.Variables.ExperimentUtils import (
    export_patterns_to_json,
    export_to_json,
    restore_session,
)
from discopop_library.discopop_optimizer.utilities.MOGUtilities import show
from discopop_library.result_classes.MergedPattern import MergedPattern
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern

logger = logging.getLogger("Optimizer").getChild("Interactive")


def run_interactive_optimizer(arguments: OptimizerArguments) -> None:
    logger.setLevel(arguments.log_level)
    logger.info("Starting..")
    # check prerequisites
    if not os.path.exists(os.path.join("optimizer", "last_experiment.pickle")):
        raise FileNotFoundError(
            ""
            + os.path.join("optimizer", "last_experiment.pickle")
            + ": please execute the non-interactice optimizer in advance."
        )

    experiment = restore_session(os.path.join("optimizer", "last_experiment.pickle"))
    logger.info("Restored experiment.")

    applied_suggestions: Set[int] = set()

    if arguments.interactive_export != "None":
        logger.info(
            "Not entering interactive mode due to specified --interactive-export: " + str(arguments.interactive_export)
        )
        parse_interactive_export(experiment, applied_suggestions, arguments)
    else:
        # enter interactive mode
        # mainloop
        got_continue = True
        while got_continue:
            print()
            print("Options: list, add [<int>]+, rm [<int>]+, exit, export, showdiff, clear")
            input1 = input()
            logger.debug("Got input: " + input1)
            got_continue = parse_input(input1, experiment, applied_suggestions, arguments)
        logger.info("Closing interactive optimizer..")


def parse_interactive_export(
    experiment: Experiment, applied_suggestions: Set[int], arguments: OptimizerArguments
) -> None:
    parse_input(
        input="add " + arguments.interactive_export.replace(",", " "),
        experiment=experiment,
        applied_suggestions=applied_suggestions,
        arguments=arguments,
    )
    parse_input(input="export", experiment=experiment, applied_suggestions=applied_suggestions, arguments=arguments)


def parse_input(
    input: str, experiment: Experiment, applied_suggestions: Set[int], arguments: OptimizerArguments
) -> bool:
    """Return True if the interactive session should be kept alive.
    Return False if the main loop should be exited."""
    if input.startswith("list"):
        print("Selected suggestions:")
        print(applied_suggestions)
    elif input.startswith("add "):
        split_input = input.split(" ")
        pattern_ids1: List[int] = []
        for s in split_input:
            try:
                id = int(s)
                pattern_ids1.append(id)
            except:
                pass
        logger.debug("Adding ids: " + str(pattern_ids1))
        applied_suggestions.update(pattern_ids1)
    elif input.startswith("rm "):
        split_input = input.split(" ")
        pattern_ids2: List[int] = []
        for s in split_input:
            try:
                id = int(s)
                pattern_ids2.append(id)
            except:
                pass
        logger.debug("Removing ids: " + str(pattern_ids2))
        for i in pattern_ids2:
            if i in applied_suggestions:
                applied_suggestions.remove(i)
    elif input.startswith("clear"):
        applied_suggestions.clear()
    elif input.startswith("exit"):
        return False
    elif input.startswith("export"):
        export_configuration(experiment, applied_suggestions, arguments)
    elif input.startswith("showdiff"):
        show_configuration_diff(experiment, applied_suggestions)
    else:
        logger.info("Unknown command ignored: " + input)
    return True


def show_configuration_diff(experiment: Experiment, applied_suggestions: Set[int]) -> None:
    logger.info("Creating and showing the diff for the current configuration..")
    logger.info("Not yet implemented")


def export_configuration(experiment: Experiment, applied_suggestions: Set[int], arguments: OptimizerArguments) -> None:
    logger.info("Exporting the current configuration..")
    configured_pattern = __create_optimizer_output_pattern(experiment, applied_suggestions)
    if configured_pattern is None:
        logger.info("Nothing to export.")
        return
    logger.info("Calculating necessary data movement")
    logger.debug("Decisions: " + str(configured_pattern.decisions))
    data_transfer = new_calculate_data_transfers(
        experiment.optimization_graph, configured_pattern.decisions, experiment, arguments=arguments
    )
    for update in data_transfer:
        configured_pattern.add_data_movement(update)
    logger.info("Optimizing data movement")
    configured_pattern = cast(MergedPattern, optimize_updates(experiment, configured_pattern, arguments))
    # append the configuration to the list of patterns
    experiment.detection_result.patterns.merged_pattern.append(configured_pattern)
    # save updated patterns.json to disk
    export_patterns_to_json(experiment, os.path.join("optimizer", "patterns.json"))
    logger.info("Saved patterns.")
    # save updated experiment
    export_to_json(experiment, "optimizer")
    logger.info("Saved experiment.")


def __create_optimizer_output_pattern(experiment: Experiment, applied_suggestions: Set[int]) -> Optional[MergedPattern]:
    if len(applied_suggestions) == 0:
        return None
    output_pattern: Optional[MergedPattern] = None

    for suggestion_id in applied_suggestions:
        if output_pattern is None:
            # Initialize output_pattern
            first_suggestion = experiment.detection_result.patterns.get_pattern_from_id(suggestion_id)
            output_pattern = MergedPattern(
                first_suggestion._node,
                experiment.pattern_id_to_decisions_dict[first_suggestion.pattern_id],
                experiment.get_system().get_host_device_id(),
                experiment,
            )
            logger.info("Initialized OptimizerOutputPattern based on " + str(suggestion_id))

        pattern_obj = experiment.detection_result.patterns.get_pattern_from_id(suggestion_id)
        if "device_id" in pattern_obj.__dict__:
            device_id = pattern_obj.__dict__["device_id"]
        else:
            device_id = experiment.get_system().get_host_device_id()

        # unpack OptimizerOutputPattern if necessary
        if isinstance(pattern_obj, OptimizerOutputPattern):
            logger.info("OptimizerOutputPattern found!")
            for contained_pattern in pattern_obj.applied_patterns:
                logger.info("--> " + str(contained_pattern))
                output_pattern.add_pattern(
                    contained_pattern["pattern_id"], contained_pattern["device_id"], contained_pattern["device_type"]
                )
                logger.info("Added sub-pattern : " + str(contained_pattern["pattern_id"]))
            logger.info("Inherited decisions from pattern_obj: " + str(pattern_obj.decisions))
            output_pattern.decisions += pattern_obj.decisions

        else:
            # regular pattern type
            output_pattern.add_pattern(
                pattern_obj.pattern_id, device_id, experiment.get_system().get_device(device_id).get_device_type()
            )
            logger.info("Added pattern : " + str(suggestion_id))

    if output_pattern is None:
        return None
    # collect decisions
    output_pattern.decisions = output_pattern.get_contained_decisions(experiment)
    logger.info("Created new pattern: " + str(output_pattern.pattern_id))
    return output_pattern
