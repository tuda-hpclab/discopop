# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
import shutil

from discopop_library.FolderStructure.setup import setup_patch_applicator
from discopop_library.PathManagement.PathManagement import load_file_mapping

import logging

from discopop_library.PreProcessor.PreProcessorArguments import PreProcessorArguments
from discopop_library.PreProcessor.demangle.driver import demangle

logger = logging.getLogger("Preprocessor")


def run(arguments: PreProcessorArguments) -> None:

    logger.info("Started DiscoPoP Preprocessor...")
    logger.debug("Working directory: " + str(os.getcwd()))
    logger.debug(arguments)

    # check prerequisited
    data_dir = os.path.join(os.getcwd(), "profiler")
    if not os.path.exists(data_dir):
        raise FileNotFoundError(data_dir)

    # create a copy of the raw profiling data
    raw_data_dir = os.path.join(os.getcwd(), "raw_profiler")
    if not os.path.exists(raw_data_dir):
        logger.info("Creating copy of raw data.")
        shutil.copytree(data_dir, raw_data_dir)
        logger.info("\tDone.")

    demangle(arguments, logger)
