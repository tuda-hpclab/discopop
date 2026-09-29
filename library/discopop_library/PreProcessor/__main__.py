# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.PreProcessor.PreProcessorArguments import PreProcessorArguments
from discopop_library.PreProcessor.pre_processor import run


def parse_args() -> PreProcessorArguments:
    """Parse the arguments passed to the discopop_preprocessor"""
    parser = ArgumentParser(description="DiscoPoP Preprocessor")
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments for the task pattern detector and other experimental features. These flags are considered EXPERIMENTAL and they may or may not be removed or changed in the near future.",
    )

    # fmt: off
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # EXPERIMENTAL FLAGS:
    # fmt: on

    arguments = parser.parse_args()

    return PreProcessorArguments(
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    run(arguments)


if __name__ == "__main__":
    main()
