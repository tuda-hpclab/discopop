# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments
from discopop_library.ConfigProvider.config_provider import run


def parse_args() -> ConfigProviderArguments:
    """Parse the arguments passed to the discopop_config_provider"""
    parser = ArgumentParser(description="DiscoPoP Config Provider")

    # fmt: off
    mutually_exclusive = parser.add_mutually_exclusive_group()
    mutually_exclusive.add_argument("-b", "--dp-build-dir", action="store_true",
                        help="Return the path to the DiscoPoP build directory")
    mutually_exclusive.add_argument("--llvm-bin-dir", action="store_true",
                        help="Return the path to the LLVM bin directory")
    mutually_exclusive.add_argument("-f", "--full", action="store_true",
                        help="Return the full configuration")
    mutually_exclusive.add_argument("-v", "--version", action="store_true",
                        help="Return the version string of the DiscoPoP library")
    # EXPERIMENTAL FLAGS:
    # fmt: on

    arguments = parser.parse_args()

    return ConfigProviderArguments(
        return_dp_build_dir=arguments.dp_build_dir,
        return_llvm_bin_dir=arguments.llvm_bin_dir,
        return_full_config=arguments.full,
        return_version_string=arguments.version,
    )


def main() -> None:
    arguments = parse_args()
    retval = run(arguments)
    print(retval)


if __name__ == "__main__":
    main()
