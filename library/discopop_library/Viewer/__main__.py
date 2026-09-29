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
from discopop_library.Viewer.ViewerArguments import ViewerArguments
from discopop_library.Viewer.viewer import run


def parse_args() -> ViewerArguments:
    """Parse the arguments passed to the discopop_viewer"""
    parser = ArgumentParser(description="DiscoPoP Viewer")

    # fmt: off
    mutually_exclusive = parser.add_mutually_exclusive_group()
    mutually_exclusive.add_argument("-so", "--suggestions_overview", action="store_true",
                        help="Print an overview of the identified parallelization suggestions to the console.")
    parser.add_argument(
        "--path", type=str, default=str(os.getcwd()),
        help="Path to the .discopop directory to be analyzed")
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # EXPERIMENTAL FLAGS:
    # fmt: on

    arguments = parser.parse_args()

    return ViewerArguments(
        path=arguments.path,
        print_suggestions_overview=arguments.suggestions_overview,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    run(arguments)


if __name__ == "__main__":
    main()
