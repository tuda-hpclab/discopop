# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from logging import Logger
from typing import Callable, Dict, List, Set, Tuple, cast

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


def _evaluate(
    config: Set[int],
    reference_configuration: CodeConfiguration,
    arguments: AutotunerArguments,
    timeout_after: float,
    get_unique_configuration_id: Callable[[], int],
    debug_stats: List[DebugStatEntry],
) -> Tuple[float, bool]:
    """Compile and run a configuration. Returns (runtime, is_valid).
    Falls back to the reference runtime when the config is empty."""
    if not config:
        ref_res = cast(ExecutionResult, reference_configuration.execution_result)
        return ref_res.runtime, ref_res.return_code == 0 and ref_res.result_valid and ref_res.thread_sanitizer

    tmp_config = reference_configuration.create_copy(arguments, "par_settings.json", get_unique_configuration_id)
    tmp_config.apply_suggestions(arguments, list(config))
    tmp_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
    if not arguments.skip_cleanup:
        tmp_config.deleteFolder()

    exec_res = cast(ExecutionResult, tmp_config.execution_result)
    debug_stats.append(
        (
            sorted(config),
            exec_res.runtime,
            exec_res.return_code,
            exec_res.result_valid,
            exec_res.thread_sanitizer,
            tmp_config.root_path,
            cast(ExecutionResult, tmp_config.execution_result).failed_suggestions,
        )
    )

    is_valid = exec_res.return_code == 0 and exec_res.result_valid and exec_res.thread_sanitizer
    return exec_res.runtime, is_valid


def execute_coordinate_descent_combination(
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
    logger.info("Executing coordinate descent combination.")

    patterns_by_hotspot_type = get_patterns_by_hotspot_type(detection_result, hotspot_information)
    logger.debug("Patterns by hotspot type: " + str(patterns_by_hotspot_type))

    if "maybe" not in arguments.hotspot_types:
        patterns_by_hotspot_type[HotspotType.MAYBE] = []
    if "no" not in arguments.hotspot_types:
        patterns_by_hotspot_type[HotspotType.NO] = []

    # All candidate suggestions, ordered by evidence strength for the initial scan order.
    all_suggestions: List[int] = (
        patterns_by_hotspot_type[HotspotType.YES]
        + patterns_by_hotspot_type[HotspotType.MAYBE]
        + patterns_by_hotspot_type[HotspotType.NO]
    )

    if not all_suggestions:
        logger.info("No suggestions available. Stopping.")
        return

    # Initialize from all YES suggestions — the strongest-evidence starting point.
    # If no YES suggestions exist, start from empty.
    current_config: Set[int] = set(patterns_by_hotspot_type[HotspotType.YES])

    logger.info("Measuring initial configuration (all YES suggestions): " + str(sorted(current_config)))
    current_runtime, current_valid = _evaluate(
        current_config, reference_configuration, arguments, timeout_after, get_unique_configuration_id, debug_stats
    )

    # Fall back to empty if the initial YES configuration is invalid.
    if not current_valid:
        logger.info("Initial YES configuration is invalid; falling back to empty configuration.")
        current_config = set()
        current_runtime = cast(ExecutionResult, reference_configuration.execution_result).runtime

    logger.info(
        "Starting coordinate descent over "
        + str(len(all_suggestions))
        + " suggestions. Initial runtime: "
        + str(round(current_runtime, 3))
        + "s"
    )
    logger.info("Press CTRL+C to manually stop the search.")

    pass_count = 0
    try:
        while True:
            pass_count += 1
            improved_in_pass = False
            logger.info("Pass " + str(pass_count))

            for suggestion in search_bar(all_suggestions, desc="Pass " + str(pass_count)):
                # Toggle: remove if present, add if absent.
                if suggestion in current_config:
                    candidate = current_config - {suggestion}
                else:
                    candidate = current_config | {suggestion}

                runtime, is_valid = _evaluate(
                    candidate,
                    reference_configuration,
                    arguments,
                    timeout_after,
                    get_unique_configuration_id,
                    debug_stats,
                )

                if is_valid and runtime < current_runtime:
                    action = "removed" if suggestion in current_config else "added"
                    logger.info(
                        "Pass "
                        + str(pass_count)
                        + ": "
                        + action
                        + " suggestion "
                        + str(suggestion)
                        + ": "
                        + str(round(current_runtime, 3))
                        + "s -> "
                        + str(round(runtime, 3))
                        + "s"
                    )
                    current_config = candidate
                    current_runtime = runtime
                    improved_in_pass = True

            if not improved_in_pass:
                logger.info("Pass " + str(pass_count) + " yielded no improvement. Converged.")
                break

    except KeyboardInterrupt:
        logger.info("Manually stopped coordinate descent search.")

    logger.info(
        "Coordinate descent complete after "
        + str(pass_count)
        + " pass(es). Final configuration: "
        + str(sorted(current_config))
    )
    logger.info("Final runtime: " + str(round(current_runtime, 3)) + "s")
    show_info_stats(debug_stats, logger)
