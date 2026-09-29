# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

import logging

logger = logging.getLogger("ConfigurationManager")


def initialize_directories(arguments: ProjectManagerArguments) -> None:
    """Initializes the .discopop directory, if it does not exist already"""
    if not os.path.exists(arguments.dot_dp):
        logger.info("Creating project directory: " + arguments.dot_dp)
        os.mkdir(arguments.dot_dp)

    if not os.path.exists(arguments.project_dir):
        logger.info("Creating directory: " + arguments.project_dir)
        os.mkdir(arguments.project_dir)

    if not os.path.exists(arguments.project_config_dir):
        logger.info("Creating directory: " + arguments.project_config_dir)
        os.mkdir(arguments.project_config_dir)
