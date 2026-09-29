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
import subprocess
from typing import Dict
import warnings
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
import logging

logger = logging.getLogger("ConfigurationManager")

initial_settings_content: Dict[str, str] = {"CC": "clang", "CXX": "clang++", "CFLAGS": "", "CXXFLAGS": ""}

initial_script_content = """#!/bin/bash
# This script is executed from the project root directory.
# You can use relative paths as if you are already in the project root.
#
# The scripts need to make use of CC / CXX and the according flags CFLAGS / CXXFLAGS and return 0 upon successful execution.
# Please set the contents of the script according to the wiki: https://tuda-hpclab.github.io/discopop/

echo "Please set the contents of the script according to the wiki: https://tuda-hpclab.github.io/discopop/"
echo "The scripts need to make use of CC / CXX and the according flags CFLAGS / CXXFLAGS and return 0 upon successful execution."
echo "Document: $(realpath $0)"
exit 1
"""


def initialize_configuration_files(arguments: ProjectManagerArguments) -> None:
    """adds the missing files for stored configurations, for example after initialization of the directories"""
    # Create shared files (compile.sh and seq_settings.json) in project_config_dir
    # Derived settings (dp, hd, par) are created on-demand via derive_settings_files
    shared_files = [
        os.path.join(arguments.project_config_dir, "compile.sh"),
        os.path.join(arguments.project_config_dir, "seq_settings.json"),
    ]

    for file in shared_files:
        if not os.path.exists(file):
            if file.endswith("settings.json"):
                with open(file, "w+") as f:
                    json.dump(initial_settings_content, f)
                    logger.info("Created configuration file: " + str(file))
            else:
                with open(file, "w+") as f:
                    f.write(initial_script_content)
                    logger.info("Created configuration file: " + str(file))
                # make executable
                cmd = "chmod +x " + file
                result = subprocess.run(
                    cmd,
                    executable="/bin/bash",
                    shell=True,
                    capture_output=True,
                )
                if result.returncode != 0:
                    warnings.warn(
                        "Created script "
                        + str(file)
                        + " could not be marked as executable via \n"
                        + cmd
                        + "\nPlease fix this manually.\nstderr: \n->"
                        + str(result.stderr.decode("utf-8"))
                    )

    # Create configuration-specific files (execute.sh only)
    for configuration_path in [f.path for f in os.scandir(arguments.project_config_dir) if f.is_dir()]:
        config_specific_file = os.path.join(configuration_path, "execute.sh")

        if not os.path.exists(config_specific_file):
            with open(config_specific_file, "w+") as f:
                f.write(initial_script_content)
                logger.info("Created configuration file: " + str(config_specific_file))
            # make executable
            cmd = "chmod +x " + config_specific_file
            result = subprocess.run(
                cmd,
                executable="/bin/bash",
                shell=True,
                capture_output=True,
            )
            if result.returncode != 0:
                warnings.warn(
                    "Created script "
                    + str(config_specific_file)
                    + " could not be marked as executable via \n"
                    + cmd
                    + "\nPlease fix this manually.\nstderr: \n->"
                    + str(result.stderr.decode("utf-8"))
                )
