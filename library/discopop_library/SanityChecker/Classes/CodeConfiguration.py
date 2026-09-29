# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
import os
import shutil
import subprocess
import time
from typing import Callable, List, Optional
from discopop_library.SanityChecker.ArgumentClasses import SanityCheckerArguments
from discopop_library.SanityChecker.Classes.ExecutionResult import ExecutionResult
from discopop_library.SanityChecker.Types import SUGGESTION_ID
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.PatchApplicator.patch_applicator import run_with_result as apply_patches

logger = logging.getLogger("CodeConfiguration")


class CodeConfiguration(object):
    root_path: str
    config_dot_dp_path: str
    execution_result: Optional[ExecutionResult]

    def __init__(self, root_path: str, config_dot_dp_path: str):
        self.root_path = root_path
        if self.root_path.endswith("/"):
            self.root_path = self.root_path[:-1]
        self.config_dot_dp_path = config_dot_dp_path
        if self.config_dot_dp_path.endswith("/"):
            self.config_dot_dp_path = self.config_dot_dp_path[:-1]
        self.execution_result = None
        logger.debug("Created configuration: " + root_path)

    def __str__(self) -> str:
        return self.root_path

    def execute(self, arguments: SanityCheckerArguments, timeout: Optional[float], is_initial: bool = False) -> None:
        # create timeout string
        timeout_string = "" if timeout is None else "timeout " + str(timeout) + " "
        if is_initial:
            timeout_string += "source "
        # compile code
        logger.info("Compiling configuration: " + str(self))
        compile_result = subprocess.run(
            "./DP_COMPILE_SANITIZE.sh", cwd=self.root_path, executable="/bin/bash", shell=True, capture_output=True
        )
        logger.getChild("compilationOutput").debug(str(compile_result.stdout.decode("utf-8")))

        # check for result validity using thread sanitizer
        thread_sanitizer_valid = True
        logger.info("Checking thread sanity: " + str(self))
        thread_sanitizer_result = subprocess.run(
            "source ./DP_EXECUTE_SANITIZE.sh",
            cwd=self.root_path,
            executable="/bin/bash",
            shell=True,
            capture_output=True,
        )
        thread_sanitizer_output = "\n" + str(thread_sanitizer_result.stdout.decode("utf-8"))
        thread_sanitizer_error = "\n" + str(thread_sanitizer_result.stderr.decode("utf-8"))
        logger.getChild("ThreadSanitizerOutput").debug(thread_sanitizer_output)
        logger.getChild("ThreadSanitizerError").debug(thread_sanitizer_error)
        if "WARNING: ThreadSanitizer: data race" in thread_sanitizer_error:
            thread_sanitizer_valid = False

        # check for regular result validity, if a data race was identified to reduce false positives
        validation_result: Optional[bool] = None
        if os.path.exists(os.path.join(self.root_path, "DP_VALIDATE.sh")) and not thread_sanitizer_valid:
            logger.info("Data races found. Checking result validity: " + str(self))
            validity_check_result = subprocess.run(
                "source ./DP_VALIDATE.sh", cwd=self.root_path, executable="/bin/bash", shell=True, capture_output=True
            )
            logger.getChild("validationOutput").debug(str(validity_check_result.stdout.decode("utf-8")))
            logger.getChild("validationResult").debug("Returncode: " + str(validity_check_result.returncode))
            if validity_check_result.returncode != 0:
                validation_result = False
            validation_result = True

        # reporting
        logger.debug("Execution return code: " + str(thread_sanitizer_result.returncode))
        logger.debug("ThreadSanitizer valid: " + str(thread_sanitizer_valid))
        logger.debug("Validation result: " + str(validation_result))

        self.execution_result = ExecutionResult(
            thread_sanitizer_result.returncode, thread_sanitizer_valid, validation_result
        )

    def create_copy(self, get_new_configuration_id: Callable[[], int]) -> CodeConfiguration:
        # create a copy of the project folder
        dest_path = self.root_path + "_dpsanitize_" + str(get_new_configuration_id())
        if os.path.exists(dest_path):
            shutil.rmtree(dest_path)
        shutil.copytree(self.root_path, dest_path)
        # get updated .discopop folder location
        new_dot_discopop_path = self.config_dot_dp_path.replace(self.root_path, dest_path)
        logger.debug("Copied folder: " + self.root_path + " to " + dest_path)
        logger.debug("Set " + self.config_dot_dp_path + " to " + new_dot_discopop_path)
        # update FileMapping.txt in new .discopop folder
        with open(os.path.join(new_dot_discopop_path, "NewFileMapping.txt"), "w+") as o:
            with open(os.path.join(new_dot_discopop_path, "FileMapping.txt"), "r") as f:
                for line in f.readlines():
                    line = line.replace(self.root_path, dest_path)
                    o.write(line)
        shutil.move(
            os.path.join(new_dot_discopop_path, "NewFileMapping.txt"),
            os.path.join(new_dot_discopop_path, "FileMapping.txt"),
        )
        logger.debug("Updated " + os.path.join(new_dot_discopop_path, "FileMapping.txt"))

        # create a new CodeConfiguration object
        return CodeConfiguration(dest_path, new_dot_discopop_path)

    def deleteFolder(self) -> None:
        # delete the root folder.
        if not os.path.exists(self.root_path):
            raise FileNotFoundError(self.root_path)
        shutil.rmtree(self.root_path)
        logger.debug("Deleted " + self.root_path)

    def apply_suggestions(
        self, arguments: SanityCheckerArguments, suggestion_ids: List[SUGGESTION_ID]
    ) -> Optional[PatchApplicationResult]:
        """Applies the given suggestion to the code configuration via discopop_patch_applicator

        Returns which of the requested suggestions reached the code. A caller that
        ignores a failure would be checking the unmodified original instead.
        """
        sub_logger = logger.getChild("apply_suggestions")

        sub_logger.debug("Applying patch applicator for: " + str(suggestion_ids))
        suggestion_ids_str = [str(id) for id in suggestion_ids]

        save_dir = os.getcwd()
        os.chdir(self.config_dot_dp_path)
        try:
            ret_val, application_result = apply_patches(
                PatchApplicatorArguments(
                    arguments.log_level, arguments.write_log, False, suggestion_ids_str, [], False, False, False
                )
            )
            sub_logger.debug("Patch applicator return code: " + str(ret_val))
            os.chdir(save_dir)
        except Exception as ex:
            sub_logger.debug("Got Exception during call to patch applicator.")
            os.chdir(save_dir)
            raise ex
        if application_result is not None and application_result.failure:
            sub_logger.error(application_result.summary())
        return application_result
