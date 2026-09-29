# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os
from typing import Dict, List, Optional, Tuple, Union, cast

import jsonpickle  # type: ignore
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_library.FolderStructure.setup import setup_sanity_checker
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.SanityChecker.ArgumentClasses import SanityCheckerArguments
from discopop_library.SanityChecker.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.SanityChecker.Classes.ExecutionResult import ExecutionResult
from discopop_library.SanityChecker.Types import PATTERN_TAG, RETURN_CODE, SUGGESTION_ID, TSAN_CODE, VALIDATION_CODE
from discopop_library.SanityChecker.utils import get_applicable_suggestion_ids
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.result_classes.DetectionResult import DetectionResult

logger = logging.getLogger("SanityChecker")

configuration_counter = 1


def get_unique_configuration_id() -> int:
    global configuration_counter
    buffer = configuration_counter
    configuration_counter += 1
    return buffer


def run(arguments: SanityCheckerArguments) -> None:
    logger.info("Starting.")
    results: List[Dict[str, Union[List[SUGGESTION_ID], List[PATTERN_TAG], TSAN_CODE, Optional[bool], RETURN_CODE]]] = []

    debug_stats: List[Tuple[List[SUGGESTION_ID], RETURN_CODE, TSAN_CODE, VALIDATION_CODE, str]] = []

    setup_sanity_checker(arguments.dot_dp_path)

    # get untuned reference result
    reference_configuration = CodeConfiguration(arguments.project_path, arguments.dot_dp_path)
    reference_configuration.execute(arguments, timeout=None, is_initial=True)
    results.append(
        {
            "applied_suggestions": cast(List[SUGGESTION_ID], []),
            "applied_pattern_tags": cast(List[PATTERN_TAG], []),
            "TSAN_CODE": cast(ExecutionResult, reference_configuration.execution_result).thread_sanitizer,
            "VALIDATION": cast(ExecutionResult, reference_configuration.execution_result).validation_result,
            "RETURN_CODE": cast(ExecutionResult, reference_configuration.execution_result).return_code,
        }
    )
    debug_stats.append(
        (
            [],
            cast(ExecutionResult, reference_configuration.execution_result).return_code,
            cast(ExecutionResult, reference_configuration.execution_result).thread_sanitizer,
            cast(ExecutionResult, reference_configuration.execution_result).validation_result,
            reference_configuration.root_path,
        )
    )

    # load suggestions
    with open(os.path.join(arguments.dot_dp_path, "explorer", "detection_result_dump.json"), "r") as f:
        tmp_str = f.read()
    detection_result: DetectionResult = jsonpickle.decode(tmp_str, keys=True)
    logger.debug("loaded suggestions")

    # load hotspot information and classify suggestions
    hsl_arguments = HotspotLoaderArguments(
        "WARNING", arguments.write_log, False, arguments.dot_dp_path, True, False, True, True, True
    )
    hotspot_information = load_hotspots(hsl_arguments)
    logger.debug("loaded hotspots")
    patterns_by_hotspot_type = get_patterns_by_hotspot_type(detection_result, hotspot_information)
    logger.debug("Patterns by hotspot type")
    logger.debug(str(patterns_by_hotspot_type))

    # filter suggestions by requested hotspot categorization

    filtered_suggestion_ids: List[int] = []
    for hotspot_class in arguments.suggestion_classes:
        filtered_suggestion_ids += patterns_by_hotspot_type[hotspot_class]

    # check every filtered suggestion for sanity
    logger.debug("suggestions: " + str(filtered_suggestion_ids))
    for pattern_id in filtered_suggestion_ids:
        configuration = reference_configuration.create_copy(get_unique_configuration_id)
        application = configuration.apply_suggestions(arguments, [pattern_id])
        if application is not None and application.failure:
            # Nothing was patched, so this copy holds the original code. Checking it
            # would certify the unmodified program as a sane parallelization.
            logger.error("Suggestion " + str(pattern_id) + " not checked: " + application.summary())
            results.append(
                {
                    "applied_suggestions": cast(List[SUGGESTION_ID], [pattern_id]),
                    "applied_pattern_tags": cast(
                        List[PATTERN_TAG], [detection_result.patterns.get_pattern_from_id(pattern_id).pattern_tag]
                    ),
                    "TSAN_CODE": None,
                    "VALIDATION": None,
                    "RETURN_CODE": None,
                    "APPLICATION_FAILED": True,
                }
            )
            configuration.deleteFolder()
            continue
        configuration.execute(arguments, timeout=None)

        results.append(
            {
                "applied_suggestions": cast(List[SUGGESTION_ID], [pattern_id]),
                "applied_pattern_tags": cast(
                    List[PATTERN_TAG], [detection_result.patterns.get_pattern_from_id(pattern_id).pattern_tag]
                ),
                "TSAN_CODE": cast(ExecutionResult, configuration.execution_result).thread_sanitizer,
                "VALIDATION": cast(ExecutionResult, configuration.execution_result).validation_result,
                "RETURN_CODE": cast(ExecutionResult, configuration.execution_result).return_code,
            }
        )

        debug_stats.append(
            (
                [pattern_id],
                cast(ExecutionResult, configuration.execution_result).return_code,
                cast(ExecutionResult, configuration.execution_result).thread_sanitizer,
                cast(ExecutionResult, configuration.execution_result).validation_result,
                configuration.root_path,
            )
        )
        configuration.deleteFolder()

    # show debug stats
    stats_str = "Configuration results:\n"
    stats_str += "[applied suggestions]\t[return code]\t[thread sanitizer]\t[validation]\t[path]\n"
    for stats in sorted(debug_stats, key=lambda x: (x[1]), reverse=True):
        stats_str += (
            str(stats[0])
            + "\t"
            + str(stats[1])
            + "\t"
            + str(stats[2])
            + "\t"
            + str(stats[3])
            + "\t"
            + str(stats[4])
            + "\n"
        )
    logger.info(stats_str)

    # output results
    with open(os.path.join(arguments.dot_dp_path, "sanity_checker", "results.json"), "w+") as f:
        json.dump(results, f)
