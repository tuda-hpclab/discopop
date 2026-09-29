# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
from discopop_library.Compatibility.LegacyDiscoPoP.GEPDependencyRemover.ArgumentClasses import (
    GEPDependencyRemoverArguments,
)
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.Compatibility.LegacyDiscoPoP.GEPDependencyRemover.GEPDependencyRemover import run


def parse_args() -> GEPDependencyRemoverArguments:
    """Parse the arguments passed to the discopop GEPDependencyRemover"""
    parser = ArgumentParser(description="DiscoPoP GEPDependencyRemover")

    # fmt: off

    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    parser.add_argument("--dyndep-file-path", type=str, default=os.path.join(os.getcwd(), ".discopop", "profiler", "dynamic_dependencies.txt"), help="Path to the dynamic dependencies file to be converted.")
    # fmt: on

    arguments = parser.parse_args()

    return GEPDependencyRemoverArguments(
        log_level=arguments.log.upper(), write_log=arguments.write_log, dyndep_file_path=arguments.dyndep_file_path
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    arguments.log()
    run(arguments)


if __name__ == "__main__":
    main()
