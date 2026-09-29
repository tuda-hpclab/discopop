# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os
import shutil
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
import logging

logger = logging.getLogger("ConfigurationManager")


def reset_project(arguments: ProjectManagerArguments) -> None:

    if arguments.reset:
        logger.info("Resetting project directory.")
        if not os.path.exists(arguments.dot_dp):
            return

        keep_elements = ["project"]
        for content in os.listdir(arguments.dot_dp):
            if content in keep_elements:
                continue
            content_path = os.path.join(arguments.dot_dp, content)
            if os.path.isdir(content_path):
                shutil.rmtree(content_path)
            else:
                os.remove(content_path)

    if arguments.reset or arguments.reset_execution_results:
        # manually delete project/execution_results.json if existent
        per_path = os.path.join(arguments.dot_dp, "project", "execution_results.json")
        if os.path.exists(per_path):
            os.remove(per_path)
        # manually delete project/reports if existent
        per_path = os.path.join(arguments.dot_dp, "project", "reports")
        if os.path.exists(per_path):
            shutil.rmtree(per_path)
