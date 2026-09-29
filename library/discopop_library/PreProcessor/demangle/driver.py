# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import subprocess
from discopop_library.PreProcessor.PreProcessorArguments import PreProcessorArguments

import logging

from discopop_library.PreProcessor.demangle.data_xml import demangle_data_xml
from discopop_library.PreProcessor.demangle.dependency_metadata import demangle_dependency_metadata
from discopop_library.PreProcessor.demangle.dynamic_dependencies import demangle_dynamic_dependencies
from discopop_library.PreProcessor.demangle.reduction import demangle_reduction
from discopop_library.PreProcessor.demangle.static_dependencies import demangle_static_dependencies


def demangle(arguments: PreProcessorArguments, parent_logger: logging.Logger) -> None:
    logger = parent_logger.getChild("Demangle")
    logger.info("Demangling value and function names")

    # get required path of llvm-cxxfilt
    llvm_bin_dir = subprocess.run(["discopop_config_provider", "--llvm-bin-dir"], stdout=subprocess.PIPE).stdout.decode(
        "UTF-8"
    )
    llvm_bin_dir = llvm_bin_dir.replace("\n", "")
    cxxfilt_bin = os.path.join(llvm_bin_dir, "llvm-cxxfilt")

    # Data.xml
    # demangle_data_xml(arguments, logger, cxxfilt_bin)
    # dependency_metadata.txt
    # demangle_dependency_metadata(arguments, logger, cxxfilt_bin)
    # dynamic_dependencies.txt
    # demangle_dynamic_dependencies(arguments, logger, cxxfilt_bin)
    # reduction.txt
    demangle_reduction(arguments, logger, cxxfilt_bin)
    # static_dependencies.txt
    # demangle_static_dependencies(arguments, logger, cxxfilt_bin)
