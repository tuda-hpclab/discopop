# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from logging import Logger
from typing import Callable, Dict, List, Tuple, cast

from discopop_library.EmpiricalAutotuning.output.bars import search_bar

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.EmpiricalAutotuning.output.progress import DebugStatEntry
from discopop_library.EmpiricalAutotuning.output.intermediate import show_info_stats
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import AVERAGE_RUNTIME, FILEID, NAME, STARTLINE
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.result_classes.DetectionResult import DetectionResult


def execute_greedy_combination(
    detection_result: DetectionResult,
    hotspot_information: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]],
    logger: Logger,
    time_limit_s: int,
    reference_configuration: CodeConfiguration,
    arguments: AutotunerArguments,
    timeout_after: float,
    debug_stats: List[DebugStatEntry],
    get_unique_configuration_id: Callable[[], int],
) -> None:
    logger.info("Executing greedy combination.")

    patterns_by_hotspot_type = get_patterns_by_hotspot_type(detection_result, hotspot_information)
    logger.debug("Patterns by hotspot type: " + str(patterns_by_hotspot_type))

    if "maybe" not in arguments.hotspot_types:
        patterns_by_hotspot_type[HotspotType.MAYBE] = []
    if "no" not in arguments.hotspot_types:
        patterns_by_hotspot_type[HotspotType.NO] = []

    # Build ordered suggestion list: YES (strongest evidence) first, then MAYBE, then NO.
    # Order matters: greedy accepts each suggestion once and never revisits it.
    ordered_suggestions: List[int] = (
        patterns_by_hotspot_type[HotspotType.YES]
        + patterns_by_hotspot_type[HotspotType.MAYBE]
        + patterns_by_hotspot_type[HotspotType.NO]
    )

    current_config: List[int] = []
    current_runtime = cast(ExecutionResult, reference_configuration.execution_result).runtime

    logger.info(
        "Starting greedy forward search over "
        + str(len(ordered_suggestions))
        + " suggestions. Current baseline runtime: "
        + str(round(current_runtime, 3))
        + "s"
    )
    logger.info("Press CTRL+C to manually stop the search.")

    try:
        for suggestion in search_bar(ordered_suggestions, desc="Greedy search"):
            candidate = current_config + [suggestion]

            tmp_config = reference_configuration.create_copy(
                arguments, "par_settings.json", get_unique_configuration_id
            )
            tmp_config.apply_suggestions(arguments, candidate)
            tmp_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
            if not arguments.skip_cleanup:
                tmp_config.deleteFolder()

            exec_res = cast(ExecutionResult, tmp_config.execution_result)
            debug_stats.append(
                (
                    list(candidate),
                    exec_res.runtime,
                    exec_res.return_code,
                    exec_res.result_valid,
                    exec_res.thread_sanitizer,
                    tmp_config.root_path,
                    cast(ExecutionResult, tmp_config.execution_result).failed_suggestions,
                )
            )

            is_valid = exec_res.return_code == 0 and exec_res.result_valid and exec_res.thread_sanitizer
            if is_valid and exec_res.runtime < current_runtime:
                logger.info(
                    "Accepted suggestion "
                    + str(suggestion)
                    + ": "
                    + str(round(current_runtime, 3))
                    + "s -> "
                    + str(round(exec_res.runtime, 3))
                    + "s"
                )
                current_config = candidate
                current_runtime = exec_res.runtime
            else:
                logger.info(
                    "Rejected suggestion "
                    + str(suggestion)
                    + " (valid="
                    + str(is_valid)
                    + ", runtime="
                    + str(round(exec_res.runtime, 3))
                    + "s)"
                )

    except KeyboardInterrupt:
        logger.info("Manually stopped greedy search.")

    logger.info("Greedy search complete. Final configuration: " + str(current_config))
    logger.info("Final runtime: " + str(round(current_runtime, 3)) + "s")
    show_info_stats(debug_stats, logger)
