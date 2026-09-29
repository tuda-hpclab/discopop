# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.ParallelRegionMerger.ArgumentClasses import ParallelRegionMergerArguments
from discopop_library.ParallelRegionMerger.ParallelRegionMerger import run


def parse_args() -> ParallelRegionMergerArguments:
    """Parse the arguments passed to the discopop parallel region merger"""
    parser = ArgumentParser(description="DiscoPoP parallel region merger")

    # fmt: off
    parser.add_argument("--dot-dp-path", type=str, default=os.getcwd(), help="Path to the .discopop folder. Default: $(cwd)")
    parser.add_argument("-a", "--apply-suggestions", help="Comma separated list of suggestions ids to be considered for the merge. Use the keyword 'auto' to load the configuration determined by the autotuner (if multiple configurations exist, union will be considered, if '--config' is not specified).")
    parser.add_argument("-c", "--config", default="tiny", help="Configurations to be loaded from the autotuning results. If specified config does not exist, union will be considered. Requires '-s auto' to have any effect. Default: tiny")
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    parser.add_argument("-p", "--plot", action="store_true", help="Allow the creation of interactive plots.")
    # fmt:  is provided.

    arguments = parser.parse_args()

    return ParallelRegionMergerArguments(
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        dot_dp_path=arguments.dot_dp_path,
        suggestions=arguments.apply_suggestions,
        allow_plots=arguments.plot,
        auto_tuner_config=arguments.config,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    arguments.log()
    run(arguments)


if __name__ == "__main__":
    main()
