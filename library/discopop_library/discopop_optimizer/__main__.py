# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from argparse import ArgumentParser
import logging
from discopop_library.GlobalLogger.setup import setup_logger

from discopop_library.discopop_optimizer.optimizer import run
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments


def parse_args() -> OptimizerArguments:
    """Parse the arguments passed to the discopop_optimizer"""
    parser = ArgumentParser(description="DiscoPoP Optimizer")
    # all flags that belong to the interactive optimizer for pattern merging
    interactive_parser = parser.add_argument_group(
        "Interactive (Pattern merging)", "Arguments related to pattern merging."
    )
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments marked as experimental features. These flags may or may not be removed or changed in the future.",
    )

    # fmt: off
    parser.add_argument("-v", "--verbose", action="store_true",
        help="Enable verbose output.")
    parser.add_argument("-p", type=int, default=0,
        help="Program path pruning aggressiveness. 0: no pruning. 1: prune to paths that cover 80%% of observed decisions per path split. 2: prune to most likely path.")
    parser.add_argument("-o", type=int, default=0, help="Optimization level: 0 -> no optimization. 1 -> greedy. 2 -> evolutionary. 3 -> exhaustive")

    parser.add_argument("-opt-2-params", type=str, default=None, nargs=2, metavar=("population_size", "generations"), help="Configure parameters of the evolutionary optimization (-o2). Default: 50 5")
    parser.add_argument("-s", "--single-suggestions", action="store_true", help="Enable the generation of individual suggestions for device mappings.")

    parser.add_argument(
        "--doall-microbench-file", type=str, default="None",
        help="Do-All microbenchmark results"
    )
    parser.add_argument(
        "--reduction-microbench-file", type=str, default="None",
        help="Reduction microbenchmark results"
    )
    parser.add_argument(
        "--system-configuration", type=str, default="optimizer/system_configuration.json",
        help="System configuration file"
    )
    parser.add_argument("--profiling", action="store_true",
        help="Enable profiling.")
    parser.add_argument("--pin-function-calls-to-host", action="store_true", help="Force functions calls on the host system. Prevent offloading of entire functions.")
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # INTERACTIVE (Merge) flags
    interactive_parser.add_argument("-i", "--interactive", action="store_true",
        help="Enable interactive pattern merge tool.")
    interactive_parser.add_argument("--interactive-export", metavar="suggestion_ids", type=str, default="None", help="Merge and export the result for the comma-separated list of suggestion ids. Requires '-i' .")
    # EXPERIMENTAL FLAGS:
    experimental_parser.add_argument("--allow-nested-parallelism", action="store_true",
        help="Allow the creation of nested parallelism suggestions. "
        + "WARNING: Cost estimations may not be accurrate due to potentially"
        + "high overhead introduced by entering nested parallelism!")
    experimental_parser.add_argument("--check-called-function-for-nested-parallelism", action="store_true", help="Extend the check for nested parallelism to called functions."
        + "WARNING: Execution time may increase significantly!")

    experimental_parser.add_argument("--plot", action="store_true",
        help="Plot the internal graph.")
    # fmt: on

    arguments = parser.parse_args()

    return OptimizerArguments(
        verbose=arguments.verbose,
        interactive=arguments.interactive,
        interactive_export=arguments.interactive_export,
        doall_microbench_file=arguments.doall_microbench_file,
        reduction_microbench_file=arguments.reduction_microbench_file,
        allow_nested_parallelism=arguments.allow_nested_parallelism,
        plot=arguments.plot,
        system_configuration_path=arguments.system_configuration,
        check_called_function_for_nested_parallelism=arguments.check_called_function_for_nested_parallelism,
        profiling=arguments.profiling,
        pruning_level=arguments.p,
        optimization_level=arguments.o,
        optimization_level_2_parameters=arguments.opt_2_params,
        single_suggestions=arguments.single_suggestions,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        pin_function_calls_to_host=arguments.pin_function_calls_to_host,
    )


def main() -> None:
    arguments = parse_args()

    setup_logger(arguments)

    run(arguments)


if __name__ == "__main__":
    main()
