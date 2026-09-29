# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
import sys
from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.EmpiricalAutotuning.Autotuner import run
from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    DEFAULT_EXECUTION_TIME_TAG,
    EXECUTION_TIME_DISABLED,
    validate_execution_time_regex,
)
from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_TUNING_REPETITIONS,
    validate_repetitions,
)


def parse_args() -> AutotunerArguments:
    """Parse the arguments passed to the discopop autotuner"""
    parser = ArgumentParser(description="DiscoPoP Autotuner")

    cpu_count = os.cpu_count()
    if cpu_count is None:
        non_null_default_core_count = 2
    else:
        non_null_default_core_count = int(cpu_count / 2)

    # fmt: off
    parser.add_argument("--dot-dp-path", type=str, default=os.getcwd(), help="Path to the .discopop folder. Default: $(cwd)")
    parser.add_argument("-c", "--config", default="tiny", help="Configurations to be used for the autotuning. Default: tiny")
    parser.add_argument("-s", "--suggestions", help="If specified, the comma separated list of suggestions will be applied and compared to the baseline.")
    parser.add_argument("--search-space", dest="search_space", default=None, help="If specified, restrict the optimization algorithm's search space to this comma separated list of suggestion ids (and ranges are NOT expanded here; pass explicit ids). With -A 0, a listed id the hotspot loader could not classify is measured as well. Ignored when -s/--suggestions is given.")
    parser.add_argument("-t", "--threads", type=int, default=non_null_default_core_count, help="Value of OMP_NUM_THREADS used during execution. Default: os.cpu_count()/2 = " + str(non_null_default_core_count))
    parser.add_argument("-ht", "--hotspot-types", type=str, default="yes,no,maybe", help="Hotspot types to be considered. If no hotspot information exists, all suggestions will be classified as 'yes'. Options: yes,no,maybe. Default: yes,no,maybe")
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    parser.add_argument("-p", "--plot", action="store_true", help="Allow the creation of interactive plots.")
    parser.add_argument("-A", "--algorithm", type=int, default=0, help="Optimization algorithm. Values: 0: no combination of suggestions. 1: linear combination. 3: evolutionary combination. 4: greedy forward search (O(N) evaluations). 5: coordinate descent / bit-flip local search. 6: hotspot-guided region descent (deterministic, requires hotspot detection results). Default: 0.")
    parser.add_argument("--noise-threshold", dest="noise_threshold", type=float, default=0.02, help="[-A 6] Relative runtime improvement a suggestion must achieve to be accepted, e.g. 0.02 for 2 percent. Larger values make the search more robust against measurement noise. Default: 0.02")
    parser.add_argument("--hs-min-share", dest="hs_min_share", type=float, default=0.01, help="[-A 6] Ignore hot loops whose longest measured run is below this fraction of the hottest loop's. Default: 0.01")
    parser.add_argument("--max-measurements", dest="max_measurements", type=int, default=0, help="[-A 6] Stop the search after this many compile-and-execute cycles. 0 disables the limit. Note that a search stopped by this limit is no longer reproducible. Default: 0")
    parser.add_argument("--skip-removal-pass", dest="skip_removal_pass", action="store_true", help="[-A 6] Skip the final pass that checks whether an accepted suggestion can be removed again.")
#    parser.add_argument("--project-path", type=str, default=os.getcwd(), help="Root path of the project to be tuned. \
#                        Important: Project root will be copied multiple times! It has to contain the executable scripts DP_COMPILER.sh and DP_EXECUTE.sh! \
#                        DP_COMPILER.sh must allow the inclusion of OpenMP pragmas into the code. \
#                        DP_EXECUTE.sh may return not 0, if either the execution or validation of the result failed. \
#                        A third script DP_VALIDATE.sh might be added to add a validation step, where return code 0 is interpreted as a success, i.e. a valid result.")
    parser.add_argument("--compile-only", dest="compile_only", action="store_true", help="Build every candidate but execute none of them. Nothing is measured, so no candidate is ranked and no speedup is reported; the run only answers whether each configuration compiles. Intended for checking the applicability of suggestions, e.g. by discopop_patch_repair.")
    parser.add_argument("--skip-cleanup", action="store_true", help="Disable the deletion of created code variants. May require a lot of disk space." )
    parser.add_argument("--sanitize", action="store_true", help="Enable the invocation of ThreadSanitizer if DP_COMPILE_SANITIZE.sh and DP_EXECUTE_SANITIZE.sh are provided." )
    parser.add_argument("-xr", "--execution-repetitions", type=int, default=DEFAULT_TUNING_REPETITIONS,
                        help="Run each candidate this many times and rank it by the median of the measured times, so that a single noisy run cannot decide the search. Note that this multiplies the tuning time: the search performs one program execution per candidate. Repeating the final measurements instead (discopop_project_manager --execution-repetitions) keeps the search cheap while still reporting a stable runtime. Default: " + str(DEFAULT_TUNING_REPETITIONS) + " (measure each candidate once); the measured runs are repeated by default instead.")

    parser.add_argument("-etr", "--execution-time-regex", nargs="?", const=DEFAULT_EXECUTION_TIME_REGEX, default=None,
                        help="Rank candidates by the execution time reported in the console output of execute.sh instead of its wall clock time. Expects a regular expression whose first capture group holds the value, e.g. 'Total time:\\s*([0-9.]+)'. Given without a value, the tag '<" + DEFAULT_EXECUTION_TIME_TAG + ">value</" + DEFAULT_EXECUTION_TIME_TAG + ">' is searched for. Overrides the per configuration setting stored in execution_time.json; pass an empty string to disable the search even where a configuration enables it. If omitted, the configuration's own setting applies.")

    # fmt:  is provided.

    arguments = parser.parse_args()

    # Reject an unusable pattern here rather than letting the whole search run on
    # wall clock times it was told not to use.
    if arguments.execution_time_regex not in (None, EXECUTION_TIME_DISABLED):
        regex_error = validate_execution_time_regex(arguments.execution_time_regex)
        if regex_error is not None:
            print("ERROR: --execution-time-regex: " + regex_error)
            sys.exit(1)

    # A count of zero would leave every candidate unmeasured and therefore unrankable.
    repetitions_error = validate_repetitions(arguments.execution_repetitions)
    if repetitions_error is not None:
        print("ERROR: --execution-repetitions: " + repetitions_error)
        sys.exit(1)

    return AutotunerArguments(
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        dot_dp_path=arguments.dot_dp_path,
        configuration=arguments.config,
        skip_cleanup=arguments.skip_cleanup,
        sanitize=arguments.sanitize,
        suggestions=arguments.suggestions,
        search_space=arguments.search_space,
        allow_plots=arguments.plot,
        thread_count=arguments.threads,
        hotspot_types=arguments.hotspot_types,
        algorithm=arguments.algorithm,
        compile_only=arguments.compile_only,
        noise_threshold=arguments.noise_threshold,
        hs_min_share=arguments.hs_min_share,
        max_measurements=arguments.max_measurements,
        skip_removal_pass=arguments.skip_removal_pass,
        execution_time_regex=arguments.execution_time_regex,
        execution_repetitions=arguments.execution_repetitions,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    arguments.log()
    run(arguments)


if __name__ == "__main__":
    main()
