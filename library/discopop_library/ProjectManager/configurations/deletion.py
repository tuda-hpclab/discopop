# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import shutil

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

PATH = str

logger = logging.getLogger("ConfigurationManager")


def delete_configuration(arguments: ProjectManagerArguments, project_copy_root_path: PATH) -> None:
    if not os.path.exists(project_copy_root_path):
        return
    if arguments.project_root == project_copy_root_path:
        return
    shutil.rmtree(project_copy_root_path)
    logger.debug("removed project copy: " + project_copy_root_path)
