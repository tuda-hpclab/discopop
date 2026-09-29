# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from logging import Logger
from typing import Callable, Dict, List, Set, Tuple, cast
from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.output.progress import DebugStatEntry
from discopop_library.EmpiricalAutotuning.output.intermediate import show_info_stats
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.EmpiricalAutotuning.output.intermediate import show_debug_stats
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import AVERAGE_RUNTIME, FILEID, NAME, STARTLINE
from discopop_library.result_classes.DetectionResult import DetectionResult

import time


def execute_linear_hotspot_combination(
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
    # time limited reverse greedy search in hotspot parallelizations
    patterns_by_hotspot_type = get_patterns_by_hotspot_type(detection_result, hotspot_information)
    logger.debug("Patterns by hotspot type")
    logger.debug(str(patterns_by_hotspot_type))

    start_time = time.time()
    visited = []

    # initialize with all hotspot suggestions
    configuration: List[int] = []
    if "yes" in arguments.hotspot_types:
        configuration += patterns_by_hotspot_type[HotspotType.YES]
    if "maybe" in arguments.hotspot_types:
        configuration += patterns_by_hotspot_type[HotspotType.MAYBE]
    if "no" in arguments.hotspot_types:
        configuration += patterns_by_hotspot_type[HotspotType.NO]

    # step 1: identify valid suggestions
    valid: Set[int] = set()
    queue: List[List[int]] = [[suggestion] for suggestion in configuration]
    logger.info("Identifying valid combination of parallelizable, known hotspots:")
    logger.info("Press CTRL+C to manually stop the search.")
    try:
        dbg_initial_queue_len = len(queue)
        while queue:
            logger.info("--- " + str(len(queue)) + " / " + str(dbg_initial_queue_len))
            current = queue.pop()
            # execute current and check validity
            tmp_config = reference_configuration.create_copy(
                arguments, "par_settings.json", get_unique_configuration_id
            )
            tmp_config.apply_suggestions(arguments, list(valid) + current)
            tmp_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
            if not arguments.skip_cleanup:
                tmp_config.deleteFolder()
            debug_stats.append(
                (
                    list(valid) + current,
                    cast(ExecutionResult, tmp_config.execution_result).runtime,
                    cast(ExecutionResult, tmp_config.execution_result).return_code,
                    cast(ExecutionResult, tmp_config.execution_result).result_valid,
                    cast(ExecutionResult, tmp_config.execution_result).thread_sanitizer,
                    tmp_config.root_path,
                    cast(ExecutionResult, tmp_config.execution_result).failed_suggestions,
                )
            )
            visited.append(list(valid) + current)

            # if invalid, split current into two parts and put into queue
            exec_res = cast(ExecutionResult, tmp_config.execution_result)
            if exec_res.return_code == 0 and (
                (exec_res.thread_sanitizer and exec_res.result_valid)
                or (not exec_res.thread_sanitizer and exec_res.result_valid)
            ):
                # result valid
                valid = valid.union(current)
                show_debug_stats(debug_stats, logger)
            else:
                # result invalid
                continue
    except KeyboardInterrupt:
        logger.info("Manually stopped search for valid suggestions.")
        show_info_stats(debug_stats, logger)
        pass

    show_debug_stats(debug_stats, logger)
