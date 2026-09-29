# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import sys
from argparse import ArgumentParser
from discopop_library.GlobalLogger.setup import setup_logger

from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.patch_applicator import run


def parse_args() -> PatchApplicatorArguments:
    """Parse the arguments passed to the discopop_explorer"""
    parser = ArgumentParser(description="DiscoPoP Patch Generator")
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments for the task pattern detector and other experimental features. These flags are considered EXPERIMENTAL and they may or may not be removed or changed in the near future.",
    )

    # fmt: off
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument('-a', '--apply', nargs='+', default=[], help="Apply the parallelization suggestions with the "
                                                                     "given ids.")
    parser.add_argument('-r', '--rollback', nargs='+', default=[], help="Roll back the application of the "
                                                                        "parallelization suggestions with the given "
                                                                        "ids.")
    parser.add_argument('-C', '--clear', action="store_true", help="Reset the code to it's original state. Preserves "
                                                                   "the list of applied suggestion for loading."
                                                                   "Old saves will be overwritten!")
    # todo: in the long run, saving configurations to different locations could be easily implemented.

    parser.add_argument('-L', '--load', action="store_true", help="Load a previous state after clearing.")
    parser.add_argument('-l', '--list', action="store_true", help="Show the list of applied suggestions."
                                                                  "If set, nothing else will be done.")

    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # EXPERIMENTAL FLAGS:
    # fmt: on

    arguments = parser.parse_args()

    return PatchApplicatorArguments(
        verbose=arguments.verbose,
        apply=arguments.apply,
        rollback=arguments.rollback,
        clear=arguments.clear,
        load=arguments.load,
        list=arguments.list,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
    )


def main() -> int:
    """Return values:"
    "0: Applied successfully"
    "1: Nothing applied"
    "2: Some changes applied successfully
    "3: Nothing to roll back, trivially successful"
    """
    retval = 0
    arguments = parse_args()
    setup_logger(arguments)
    retval = run(arguments)
    return retval


if __name__ == "__main__":
    # the console-script wrapper passes the return value to sys.exit; do the same
    # here so `python -m ...` reports a failed application instead of swallowing it
    sys.exit(main())
