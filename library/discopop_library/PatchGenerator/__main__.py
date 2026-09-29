# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os.path
from argparse import ArgumentParser
from pathlib import Path
from discopop_library.GlobalLogger.setup import setup_logger

from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.patch_generator import run
from discopop_library.ConfigProvider.config_provider import run as run_config_provider
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments


def parse_args() -> PatchGeneratorArguments:
    """Parse the arguments passed to the discopop_explorer"""
    parser = ArgumentParser(description="DiscoPoP Patch Generator")
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments marked as experimental features. These flags may or may not be removed or changed in the future.",
    )
    benchmarking_parser = parser.add_argument_group(
        "BENCHMARKING",
        "Arguments marked as benchmarking features. These flags may or may not be removed or changed in the future.",
    )

    # fmt: off
    parser.add_argument("-v", "--verbose", action="store_true",
        help="Enable verbose output.")
    parser.add_argument(
        "-a", "--add-from-json", type=str, default="None",
        help="Add additional patches specified in the given patterns.json file."
    )
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # EXPERIMENTAL FLAGS:
    # BENCHMARKING FLAGS:
    benchmarking_parser.add_argument("--only-optimizer-output-patterns", action="store_true", help="Only generate code for optimizer_output patterns.")
    benchmarking_parser.add_argument("--only-maximum-id-pattern", action="store_true", help="Only generate code for the pattern with the highest id.")
    # fmt: on

    arguments = parser.parse_args()

    # determine DP build path
    arguments.dp_build_path = run_config_provider(
        ConfigProviderArguments(
            return_dp_build_dir=True,
            return_llvm_bin_dir=False,
            return_full_config=False,
            return_version_string=False,
        )
    )

    # determine LLVM_BIN_DIR
    llvm_bin_dir = run_config_provider(
        ConfigProviderArguments(
            return_dp_build_dir=False,
            return_llvm_bin_dir=True,
            return_full_config=False,
            return_version_string=False,
        )
    )
    # determine CC
    arguments.cc = None
    for _name in ["clang"] + [f"clang-{v}" for v in [22, 21, 20, 19]]:
        candidate = os.path.join(llvm_bin_dir, _name)
        if os.path.exists(candidate):
            arguments.cc = candidate
            break
    if arguments.cc is None:
        raise ValueError("Could not determine CC from LLVM_BIN_DIR: ", llvm_bin_dir)

    # determine CXX
    arguments.cxx = None
    for _name in ["clang++"] + [f"clang++-{v}" for v in [22, 21, 20, 19]]:
        candidate = os.path.join(llvm_bin_dir, _name)
        if os.path.exists(candidate):
            arguments.cxx = candidate
            break
    if arguments.cxx is None:
        raise ValueError("Could not determine CXX from LLVM_BIN_DIR: ", llvm_bin_dir)

    return PatchGeneratorArguments(
        verbose=arguments.verbose,
        discopop_build_path=arguments.dp_build_path,
        CC=arguments.cc,
        CXX=arguments.cxx,
        add_from_json=arguments.add_from_json,
        only_optimizer_output_patterns=arguments.only_optimizer_output_patterns,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        only_maximum_id_pattern=arguments.only_maximum_id_pattern,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    run(arguments)


if __name__ == "__main__":
    main()
