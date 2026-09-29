# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import itertools
import json
import logging
from logging import Logger
import os
import time
from typing import List, Set, Tuple, cast

import jsonpickle  # type: ignore
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Statistics.StatisticsGraph import NodeColor, NodeShape, StatisticsGraph
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.EmpiricalAutotuning.optimization.check_single_combination import check_single_combination
from discopop_library.EmpiricalAutotuning.optimization.coordinate_descent_combination import (
    execute_coordinate_descent_combination,
)
from discopop_library.EmpiricalAutotuning.optimization.evolutionary_combination import execute_evolutionary_combination
from discopop_library.EmpiricalAutotuning.optimization.greedy_combination import execute_greedy_combination
from discopop_library.EmpiricalAutotuning.optimization.hotspot_guided_combination import (
    execute_hotspot_guided_combination,
)
from discopop_library.EmpiricalAutotuning.optimization.linear_hotspot_combination import (
    execute_linear_hotspot_combination,
)

from discopop_library.EmpiricalAutotuning.optimization.measure_only import execute_measure_only

from discopop_library.EmpiricalAutotuning.optimization.parallel_region_combination_with_refinement import (
    execute_parallel_region_combination_with_refinement,
)
from discopop_library.EmpiricalAutotuning.output.intermediate import show_info_stats
from discopop_library.EmpiricalAutotuning.output.progress import (
    DebugStatEntry,
    ProgressList,
    ProgressReporter,
    count_outcomes,
    set_active_reporter,
)
from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.EmpiricalAutotuning.priorities import get_prioritized_configurations
from discopop_library.EmpiricalAutotuning.utils import get_applicable_suggestion_ids, restrict_patterns_to_ids
from discopop_library.FolderStructure.setup import setup_auto_tuner
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.result_classes.DetectionResult import DetectionResult

logger = logging.getLogger("Autotuner")

configuration_counter = 1


def get_unique_configuration_id() -> int:
    global configuration_counter
    buffer = configuration_counter
    configuration_counter += 1
    return buffer


def report_compile_only_results(
    auto_tuner_dir: str,
    debug_stats: List[DebugStatEntry],
    optimization_time_s: float,
    progress_reporter: ProgressReporter,
    logger: Logger,
) -> None:
    """Summarize a --compile-only run and write compile_results.json.

    The reference configuration is reported alongside the candidates: when it is the
    one that does not build, no candidate's failure says anything about its patches,
    and a consumer (discopop_patch_repair above all) has to stop rather than ask an
    agent to repair patches for a project that never compiled.
    """
    built: List[List[SUGGESTION_ID]] = []
    failed: List[List[SUGGESTION_ID]] = []
    not_applied: List[List[SUGGESTION_ID]] = []
    reference_built = True
    for entry in debug_stats:
        suggestions, _, return_code, _, _, _, failed_suggestions = entry
        if failed_suggestions:
            not_applied.append(suggestions)
        elif return_code == 0:
            built.append(suggestions)
        else:
            failed.append(suggestions)
            if not suggestions:
                reference_built = False

    print("##############################")
    print("Compile-only run. No configuration was executed.")
    if not reference_built:
        print("The reference configuration itself does not build -- fix the project first.")
    print("Built: " + str(len(built)))
    print("Failed to build: " + str(len(failed)))
    if not_applied:
        print("Patches not applicable: " + str(len(not_applied)))
    for suggestions in failed:
        print("  does not build: " + (str(suggestions) if suggestions else "<reference configuration>"))
    print("Time: " + str(round(optimization_time_s, 1)) + "s")
    print("##############################")

    if not reference_built:
        logger.error("The reference configuration does not build; candidate build failures are inconclusive.")

    with open(os.path.join(auto_tuner_dir, "compile_results.json"), "w+") as f:
        json.dump(
            {
                "reference_built": reference_built,
                "built": [[int(s) for s in entry] for entry in built],
                "failed": [[int(s) for s in entry] for entry in failed],
                "not_applied": [[int(s) for s in entry] for entry in not_applied],
            },
            f,
            sort_keys=True,
            indent=4,
        )

    progress_reporter.compile_summary(built, failed, not_applied, optimization_time_s)


def write_measurements(auto_tuner_dir: str, debug_stats: List[DebugStatEntry]) -> None:
    """Persist the full measurement trace so the GUI can redraw a run without repeating it."""
    with open(os.path.join(auto_tuner_dir, "measurements.json"), "w+") as f:
        json.dump(
            [
                {
                    "suggestions": [int(s) for s in entry[0]],
                    "runtime": entry[1],
                    "return_code": entry[2],
                    "result_valid": entry[3],
                    "thread_sanitizer": entry[4],
                }
                for entry in debug_stats
            ],
            f,
            indent=4,
        )


def run(arguments: AutotunerArguments) -> None:
    logger.info("Starting discopop autotuner.")
    # ``ProgressList`` emits a structured "measurement" progress event on every
    # append, so all step-based algorithms report progress without any change.
    debug_stats: List[DebugStatEntry] = ProgressList()
    statistics_graph = StatisticsGraph()
    statistics_step_num = 0

    setup_auto_tuner(os.getcwd())
    auto_tuner_dir = os.path.join(os.getcwd(), "auto_tuner")
    # a result left over from an earlier apply must not be attributed to this run's
    # reference measurement, which applies no suggestions at all
    clear_application_result(os.path.join(arguments.dot_dp_path, "patch_applicator"))

    # structured progress channel (stdout @@AT_PROGRESS lines + progress.jsonl)
    progress_reporter = ProgressReporter(arguments.configuration, os.path.join(auto_tuner_dir, "progress.jsonl"))
    set_active_reporter(progress_reporter)

    # get untuned reference result
    reference_configuration = CodeConfiguration(arguments.project_path, arguments.dot_dp_path, "par_settings.json")
    reference_configuration.execute(arguments, timeout=None, thread_count=arguments.thread_count, is_initial=True)
    reference_result = cast(ExecutionResult, reference_configuration.execution_result)
    progress_reporter.baseline(
        reference_result.runtime,
        reference_result.return_code == 0 and reference_result.result_valid and reference_result.thread_sanitizer,
        arguments.thread_count,
    )
    statistics_graph.set_root(
        reference_configuration.get_statistics_graph_label(),
        color=reference_configuration.get_statistics_graph_color(),
        shape=NodeShape.BOX,
    )
    # Derived from the wall clock duration, never from the runtime the candidates
    # are ranked by: those differ as soon as a configuration reads its execution
    # time from the program's own output, and a timeout scaled to the *reported*
    # time would kill every candidate before the part the program does not time
    # (setup, teardown, file I/O) is even done.
    timeout_after = max(3.0, cast(ExecutionResult, reference_configuration.execution_result).wall_clock_runtime * 2)
    debug_stats.append(
        (
            [],
            cast(ExecutionResult, reference_configuration.execution_result).runtime,
            cast(ExecutionResult, reference_configuration.execution_result).return_code,
            cast(ExecutionResult, reference_configuration.execution_result).result_valid,
            cast(ExecutionResult, reference_configuration.execution_result).thread_sanitizer,
            reference_configuration.root_path,
            cast(ExecutionResult, reference_configuration.execution_result).failed_suggestions,
        )
    )

    # load hotspots
    hsl_arguments = HotspotLoaderArguments(
        "WARNING", arguments.write_log, False, arguments.dot_dp_path, True, False, True, True, True
    )
    hotspot_information = load_hotspots(hsl_arguments)
    logger.debug("loaded hotspots")
    # load suggestions
    with open(os.path.join(arguments.dot_dp_path, "explorer", "detection_result_dump.json"), "r") as f:
        tmp_str = f.read()
    detection_result: DetectionResult = jsonpickle.decode(tmp_str, keys=True)
    logger.debug("loaded suggestions")

    # get metadata: highest average runtime in hotspot information. Used to filter relevant loops (1% runtime contribution)
    max_avg_runtime = 0.0
    for hotspot_type in [HotspotType.YES, HotspotType.MAYBE, HotspotType.NO]:
        if hotspot_information:
            if hotspot_type not in hotspot_information:
                continue
            for info in hotspot_information[hotspot_type]:
                if info[4] > max_avg_runtime:
                    max_avg_runtime = info[4]

    # identify the best suggestion
    visited_configurations: List[List[SUGGESTION_ID]] = []
    best_suggestion_configuration: Tuple[List[SUGGESTION_ID], CodeConfiguration] = ([], reference_configuration)

    time_limit_s = 3600  # seconds

    optimization_start_time = time.time()
    if arguments.suggestions is None:
        if arguments.search_space is not None:
            allowed_ids = {int(s) for s in arguments.search_space.split(",") if s.strip()}
            kept = restrict_patterns_to_ids(detection_result, allowed_ids)
            logger.info("Restricted optimization search space to suggestion ids: " + str(kept))
        if arguments.algorithm == 1:
            execute_linear_hotspot_combination(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
        #        elif parallel_region_combination_with_refinement:
        #            execute_parallel_region_combination_with_refinement(
        #                detection_result,
        #                hotspot_information,
        #                logger,
        #                time_limit_s,
        #                reference_configuration,
        #                arguments,
        #                timeout_after,
        #                debug_stats,
        #                get_unique_configuration_id,
        #            )
        elif arguments.algorithm == 3:
            execute_evolutionary_combination(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
        elif arguments.algorithm == 4:
            execute_greedy_combination(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
        elif arguments.algorithm == 5:
            execute_coordinate_descent_combination(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
        elif arguments.algorithm == 6:
            execute_hotspot_guided_combination(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
        else:
            execute_measure_only(
                detection_result,
                hotspot_information,
                logger,
                time_limit_s,
                reference_configuration,
                arguments,
                timeout_after,
                debug_stats,
                get_unique_configuration_id,
            )
    else:
        check_single_combination(
            detection_result,
            hotspot_information,
            logger,
            time_limit_s,
            reference_configuration,
            arguments,
            timeout_after,
            debug_stats,
            get_unique_configuration_id,
            [int(s) for s in arguments.suggestions.split(",")],
        )

    optimization_time_s = time.time() - optimization_start_time

    if arguments.compile_only:
        # Nothing was measured, so there is no best configuration to pick, no speedup to
        # report and nothing to write to results.json -- which is what "apply the
        # tuner's result" reads, and which must never name a configuration that was
        # only ever compiled. The build outcomes are the entire result of this mode.
        report_compile_only_results(auto_tuner_dir, debug_stats, optimization_time_s, progress_reporter, logger)
        write_measurements(auto_tuner_dir, debug_stats)
        progress_reporter.close()
        set_active_reporter(None)
        return

    # select best option and create code folder
    if arguments.algorithm == 1:
        for stat_entry in sorted(debug_stats, key=lambda x: len(x[0]), reverse=True):
            if len(stat_entry[0]) != 0 and stat_entry[2] == 0 and stat_entry[3] == True and stat_entry[4] == True:
                sibling_config = reference_configuration.create_copy(
                    arguments, "par_settings.json", get_unique_configuration_id
                )
                application = sibling_config.apply_suggestions(arguments, stat_entry[0])
                if application is not None and application.failure:
                    # re-applying the winning combination failed, so this folder holds
                    # the unmodified code; reporting it as the result would claim a
                    # parallelization that is not in the code
                    logger.error(
                        "Could not re-apply the best combination " + str(stat_entry[0]) + ": " + application.summary()
                    )
                    if not arguments.skip_cleanup:
                        sibling_config.deleteFolder()
                    continue
                sibling_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
                best_suggestion_configuration = (stat_entry[0], sibling_config)
                if not arguments.skip_cleanup:
                    sibling_config.deleteFolder()
                break
    else:
        for stat_entry in sorted(debug_stats, key=lambda x: (x[1])):
            if len(stat_entry[0]) != 0 and stat_entry[2] == 0 and stat_entry[3] == True and stat_entry[4] == True:
                sibling_config = reference_configuration.create_copy(
                    arguments, "par_settings.json", get_unique_configuration_id
                )
                application = sibling_config.apply_suggestions(arguments, stat_entry[0])
                if application is not None and application.failure:
                    # re-applying the winning combination failed, so this folder holds
                    # the unmodified code; reporting it as the result would claim a
                    # parallelization that is not in the code
                    logger.error(
                        "Could not re-apply the best combination " + str(stat_entry[0]) + ": " + application.summary()
                    )
                    if not arguments.skip_cleanup:
                        sibling_config.deleteFolder()
                    continue
                sibling_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
                best_suggestion_configuration = (stat_entry[0], sibling_config)
                if not arguments.skip_cleanup:
                    sibling_config.deleteFolder()
                break

    show_info_stats(debug_stats, logger)

    # export measurements for pdf creation
    if False:  # export all measurements
        with open("measurements.csv", "w+") as f:
            f.write("ID; time; return_code; thread_sanitizer\n")
            for stats in sorted(debug_stats, key=lambda x: x[1], reverse=True):
                f.write(str(stats[0]) + "; " + str(round(stats[1], 3)) + "; " + str(stats[2]) + ";" + "\n")
    else:  # export only sequential and best measurement
        with open("measurements.csv", "w+") as f:
            f.write("ID; time; return_code; thread_sanitizer\n")
            # write sequential measurement
            for stats in sorted(debug_stats, key=lambda x: x[1], reverse=True):
                if str(stats[0]) == "[]":
                    f.write(str(stats[0]) + "; " + str(round(stats[1], 3)) + "; " + str(stats[2]) + ";" + "\n")
            # write best measurement
            for stats in sorted(debug_stats, key=lambda x: x[1], reverse=False):
                if str(stats[2]) != "0":
                    continue
                if stats[3] == False:  # skip invalid results
                    continue
                f.write(str(stats[0]) + "; " + str(round(stats[1], 3)) + "; " + str(stats[2]) + ";" + "\n")
                break

    # calculate result statistics
    best_runtime = cast(ExecutionResult, best_suggestion_configuration[1].execution_result).runtime
    if best_runtime > 0:
        speedup = cast(ExecutionResult, reference_configuration.execution_result).runtime / best_runtime
    else:
        # no measurement exists (e.g. every candidate's patches failed to apply)
        speedup = 1.0
    parallel_efficiency = speedup * (1 / arguments.thread_count)

    # show result and statistics
    if best_suggestion_configuration[1] is None:
        print("No valid configuration found!")
    else:
        print("##############################")
        print("Best configuration located at: " + best_suggestion_configuration[1].root_path)
        print("Applied suggestions: " + str(best_suggestion_configuration[0]))
        print("Speedup: ", round(speedup, 3))
        print("Parallel efficiency: ", round(parallel_efficiency, 3))
        print("Optimization time: ", str(round(optimization_time_s, 1)) + "s")
        print("##############################")

        # export results to result.json
        results_json_path = os.path.join(auto_tuner_dir, "results.json")
        if os.path.exists(results_json_path):
            with open(results_json_path, "r") as f:
                results_dict = json.load(f)
        else:
            results_dict = dict()

        if arguments.configuration not in results_dict:
            results_dict[arguments.configuration] = dict()
        results_dict[arguments.configuration]["applied_suggestions"] = [
            str(s) for s in best_suggestion_configuration[0]
        ]
        results_dict[arguments.configuration]["speedup"] = round(speedup, 3)
        results_dict[arguments.configuration]["efficiency"] = round(parallel_efficiency, 3)
        results_dict[arguments.configuration]["time"] = cast(
            ExecutionResult, best_suggestion_configuration[1].execution_result
        ).runtime
        results_dict[arguments.configuration]["not_applied_count"] = count_outcomes(debug_stats)[3]

        with open(results_json_path, "w+") as f:
            json.dump(results_dict, f, sort_keys=True, indent=4)

    # output statistics graph
    statistics_graph.output()

    # emit the final result and persist the full measurement trace so the GUI can
    # (re-)draw the search without re-running the autotuner.
    valid_count, invalid_count, failed_count, not_applied_count = count_outcomes(debug_stats)
    if not_applied_count:
        logger.error(
            str(not_applied_count)
            + " of "
            + str(len(debug_stats))
            + " configurations could not be patched and were therefore not measured."
        )
    progress_reporter.result(
        best_suggestion_configuration[0],
        speedup,
        parallel_efficiency,
        cast(ExecutionResult, best_suggestion_configuration[1].execution_result).runtime,
        valid_count,
        invalid_count,
        failed_count,
        optimization_time_s,
        not_applied_count=not_applied_count,
    )
    write_measurements(auto_tuner_dir, debug_stats)
    progress_reporter.close()
    set_active_reporter(None)
