# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
from typing import List
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.SanityChecker.ArgumentClasses import SanityCheckerArguments
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.SanityChecker.SanityChecker import run


def parse_args() -> SanityCheckerArguments:
    """Parse the arguments passed to the discopop sanity checker"""
    parser = ArgumentParser(description="DiscoPoP Sanity Checker")

    # fmt: off

    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    parser.add_argument("--project-path", type=str, default=os.getcwd(), help="Root path of the project to be tuned. \
                        Important: Project root will be copied multiple times! It has to contain the executable scripts DP_COMPILE_SANITIZE.sh and DP_EXECUTE_SANITIZE.sh! \
                        DP_COMPILE_SANITIZE.sh must allow the inclusion of OpenMP pragmas into the code and shall instrument the code using ThreadSanitizer.")
    parser.add_argument("--dot-dp-path", type=str, default=os.path.join(os.getcwd(), ".discopop"), help="Path to the .discopop folder.")
    parser.add_argument("-sc", "--suggestion_classes", metavar="CLASSES", type=str, default="YES", help="Filter considered suggestion to the specified, comma-separated list of classes of HotspotTypes. Options: YES,NO,MAYBE. Default: YES.")

    # fmt:  is provided.

    arguments = parser.parse_args()

    # prepare suggestion classification
    parsed_suggestion_classes: List[HotspotType] = []
    if "YES" in arguments.suggestion_classes.split(","):
        parsed_suggestion_classes.append(HotspotType.YES)
    if "NO" in arguments.suggestion_classes.split(","):
        parsed_suggestion_classes.append(HotspotType.NO)
    if "MAYBE" in arguments.suggestion_classes.split(","):
        parsed_suggestion_classes.append(HotspotType.MAYBE)

    return SanityCheckerArguments(
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        project_path=arguments.project_path,
        dot_dp_path=arguments.dot_dp_path,
        suggestion_classes=parsed_suggestion_classes
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    arguments.log()
    run(arguments)


if __name__ == "__main__":
    main()
