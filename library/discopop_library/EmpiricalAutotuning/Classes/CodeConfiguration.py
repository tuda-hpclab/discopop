# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional
from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Statistics.StatisticsGraph import NodeColor
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.patch_applicator import run_with_result as apply_patches
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.copying import copy_configuration
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.execution_time import resolve_execution_time_regex
from discopop_library.ProjectManager.configurations.validation import run_validation_phase

logger = logging.getLogger("CodeConfiguration")


class CodeConfiguration(object):
    root_path: str
    config_dot_dp_path: str
    settings_name: str
    execution_result: Optional[ExecutionResult]
    # Outcome of the last apply_suggestions() call on this configuration. None means
    # no suggestions were requested (e.g. the reference configuration).
    suggestion_application: Optional[PatchApplicationResult]

    def __init__(self, root_path: str, config_dot_dp_path: str, settings_name: str):

        self.root_path = root_path
        self.settings_name = settings_name
        if self.root_path.endswith("/"):
            self.root_path = self.root_path[:-1]
        self.config_dot_dp_path = config_dot_dp_path
        if self.config_dot_dp_path.endswith("/"):
            self.config_dot_dp_path = self.config_dot_dp_path[:-1]
        self.execution_result = None
        self.suggestion_application = None
        logger.debug("Created configuration: " + root_path)

    def __str__(self) -> str:
        return self.root_path

    def execute(
        self, arguments: AutotunerArguments, timeout: Optional[float], thread_count: int, is_initial: bool = False
    ) -> None:
        if self.record_failed_application():
            return
        # ``timeout`` is derived from the reference configuration's *runtime*, which
        # says nothing about how long a build may take -- and in compile-only mode no
        # run was measured at all, so it is a bound on nothing. Builds are therefore
        # left unbounded in that mode rather than cut off by a number picked for runs.
        compile_timeout = None if arguments.compile_only else timeout
        compilation_successful = self.compile_only(arguments, compile_timeout, thread_count, is_initial)
        if arguments.compile_only:
            # The build is the whole answer here. A failed build already stored its
            # result in compile_only(); a successful one gets a result that carries no
            # measurement, flagged so nothing downstream reads its 0.0 as a fast run.
            if compilation_successful:
                self.execution_result = ExecutionResult(0.0, 0, True, True, compiled_only=True)
            return
        if compilation_successful:
            self.execute_only(arguments, timeout, thread_count, is_initial)

    def record_failed_application(self) -> bool:
        """Turn an incomplete suggestion application into an invalid result, no run.

        Returns True when the configuration must not be built or measured: its code is
        the unmodified original, so any runtime measured here would be attributed to
        parallelizations that are not in the code. Marking the result invalid keeps the
        candidate out of every search algorithm's accepted set, and the recorded flags
        let the progress channel and the GUI show it as "not applied" rather than as a
        parallel run that happened to yield no speedup.
        """
        application = self.suggestion_application
        if application is None or not application.failure:
            return False
        logger.error("Not executing " + self.root_path + ": " + application.summary())
        self.execution_result = ExecutionResult(
            0.0,
            0,
            False,
            False,
            application_failed=True,
            failed_suggestions=application.unapplied_ids,
        )
        return True

    def compile_only(
        self, arguments: AutotunerArguments, timeout: Optional[float], thread_count: int, is_initial: bool = False
    ) -> bool:
        cm_args = ProjectManagerArguments(
            log_level=arguments.log_level,
            write_log=arguments.write_log,
            project_root=arguments.project_path,
            full_execute=False,
            list=False,
            execute_configurations=arguments.configuration,
            execute_inplace=False,
            skip_cleanup=arguments.skip_cleanup,
            generate_report=False,
            show_report=False,
            initialize_directory=False,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="",
            timeout_compilation=timeout,
            timeout_execution=timeout,
            timeout_validation=timeout,
        )

        compilation_successful = True
        project_config_dir = os.path.join(self.config_dot_dp_path, "project", "configs")
        config_path = os.path.join(project_config_dir, arguments.configuration)
        compile_sh = resolve_compile_script_path(project_config_dir, arguments.configuration)

        # All settings files are now shared
        if self.settings_name in ["seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json"]:
            settings_path = os.path.join(self.config_dot_dp_path, "project", "configs", self.settings_name)
        else:
            settings_path = os.path.join(config_path, self.settings_name)

        ret = execute_configuration(
            cm_args,
            self.root_path,
            config_path,
            settings_path,
            compile_sh,
            thread_count,
            timeout,
        )

        if ret is None or ret[0] != 0:
            print("Error during compilation!\n" + "" if ret is None else ("STDERR: " + ret[3]))
            self.execution_result = ExecutionResult(0.1, 1, False, False)
            compilation_successful = False
        return compilation_successful

    def execute_only(
        self, arguments: AutotunerArguments, timeout: Optional[float], thread_count: int, is_initial: bool = False
    ) -> None:
        cm_args = ProjectManagerArguments(
            log_level=arguments.log_level,
            write_log=arguments.write_log,
            project_root=arguments.project_path,
            full_execute=False,
            list=False,
            execute_configurations=arguments.configuration,
            execute_inplace=False,
            skip_cleanup=arguments.skip_cleanup,
            generate_report=False,
            show_report=False,
            initialize_directory=False,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="",
            timeout_compilation=timeout,
            timeout_execution=timeout,
            timeout_validation=timeout,
        )

        config_path = os.path.join(self.config_dot_dp_path, "project", "configs", arguments.configuration)
        # Only execute.sh is timed and counted towards the measured runtime. An
        # optional validate.sh (run below) contributes to a configuration's
        # validity but never to its runtime.
        execute_sh_path = os.path.join(config_path, "execute.sh")

        # All settings files are now shared
        if self.settings_name in ["seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json"]:
            settings_path = os.path.join(self.config_dot_dp_path, "project", "configs", self.settings_name)
        else:
            settings_path = os.path.join(config_path, self.settings_name)

        # The reported time is what candidates are ranked by; the wall clock time
        # is read alongside it because the per-candidate timeout derived from this
        # run has to bound the whole process, not just the part the program times.
        measurement: Dict[str, Any] = {}
        ret = execute_configuration(
            cm_args,
            self.root_path,
            config_path,
            settings_path,
            execute_sh_path,
            thread_count,
            timeout,
            execution_time_regex=resolve_execution_time_regex(config_path, arguments.execution_time_regex),
            measurement=measurement,
            repetitions=arguments.execution_repetitions,
        )
        if ret is None:
            result_returncode = 1
            required_time = 1.0
        else:
            result_returncode, required_time, out, err = ret
        wall_clock_time = float(measurement.get("wall_clock_time", required_time))

        # A configuration is valid only if execute.sh succeeded AND, when an
        # optional validate.sh exists, it also succeeds. validate.sh re-runs the
        # code and validates its output; it is executed separately here so its
        # duration is never counted towards required_time (the measured runtime
        # above stays purely the execute.sh time). validate.sh is skipped when
        # execute.sh already failed, or when no validate.sh is present (in which
        # case execute.sh's return code alone decides validity, as before).
        # A configuration providing a compile_validate.sh is rebuilt for validation
        # first; that build happens here, after the timed run, so it can never
        # affect the measured runtime.
        result_valid = result_returncode == 0
        if result_valid:
            validation = run_validation_phase(
                cm_args,
                self.root_path,
                config_path,
                settings_path,
                thread_count,
                timeout_compilation=timeout,
                timeout_validation=timeout,
            )
            if validation.compile_required and not validation.compile_successful:
                logger.debug("Validation build failed; treating the configuration as invalid.")
            result_valid = validation.verdict(result_valid)
            if validation.applicable:
                logger.debug(
                    "Validation return code: "
                    + str(validation.validate_result[0] if validation.validate_result else None)
                )
        thread_sanitizer_valid = True

        # reporting
        logger.debug("Execution took " + str(round(required_time, 4)) + " s")
        if wall_clock_time != required_time:
            logger.debug("Wall clock duration of the run: " + str(round(wall_clock_time, 4)) + " s")
        logger.debug("Execution return code: " + str(result_returncode))
        logger.debug("Execution result valid: " + str(result_valid))
        logger.debug("ThreadSanitizer valid: " + str(thread_sanitizer_valid))

        self.execution_result = ExecutionResult(
            required_time,
            result_returncode,
            result_valid,
            thread_sanitizer_valid,
            wall_clock_runtime=wall_clock_time,
            repetition_runtimes=measurement.get("repetition_times", []),
        )

    def create_copy(
        self, arguments: AutotunerArguments, settings_name: str, get_new_configuration_id: Callable[[], int]
    ) -> CodeConfiguration:
        # create a copy of the project folder
        cm_args = ProjectManagerArguments(
            log_level=arguments.log_level,
            write_log=arguments.write_log,
            project_root=arguments.project_path,
            full_execute=False,
            list=False,
            execute_configurations=arguments.configuration,
            execute_inplace=False,
            skip_cleanup=arguments.skip_cleanup,
            generate_report=False,
            show_report=False,
            initialize_directory=False,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="",
            timeout_compilation=None,
            timeout_execution=None,
            timeout_validation=None,
        )
        # Settings files are now shared
        if settings_name in ["seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json"]:
            settings_path = os.path.join(self.config_dot_dp_path, "project", "configs", settings_name)
        else:
            settings_path = os.path.join(
                self.config_dot_dp_path, "project", "configs", arguments.configuration, settings_name
            )

        dest_path = copy_configuration(
            cm_args,
            arguments.configuration,
            settings_path,
            get_new_configuration_id(),
        )
        new_dot_discopop_path = os.path.join(dest_path, ".discopop")

        # create a new CodeConfiguration object
        return CodeConfiguration(dest_path, new_dot_discopop_path, settings_name)

    def deleteFolder(self) -> None:
        # delete the root folder.
        if not os.path.exists(self.root_path):
            raise FileNotFoundError(self.root_path)
        shutil.rmtree(self.root_path)
        logger.debug("Deleted " + self.root_path)

    def apply_suggestions(
        self, arguments: AutotunerArguments, suggestion_ids: List[SUGGESTION_ID]
    ) -> Optional[PatchApplicationResult]:
        """Applies the given suggestion to the code configuration via discopop_patch_applicator

        The result is stored on the configuration (``suggestion_application``) and
        returned. It must not be ignored: when a patch does not apply, the code stays
        sequential and measuring it would fabricate a parallel data point. ``execute``
        checks the stored result and refuses to run such a configuration.
        """
        sub_logger = logger.getChild("apply_suggestions")

        sub_logger.debug("Applying patch applicator for: " + str(suggestion_ids))
        suggestion_ids_str = [str(id) for id in suggestion_ids]

        save_dir = os.getcwd()
        os.chdir(self.config_dot_dp_path)
        try:
            ret_val, application_result = apply_patches(
                PatchApplicatorArguments(
                    "WARNING", arguments.write_log, False, suggestion_ids_str, [], False, False, False
                )
            )
            sub_logger.debug("Patch applicator return code: " + str(ret_val))
            os.chdir(save_dir)
        except Exception as ex:
            sub_logger.debug("Got Exception during call to patch applicator.")
            os.chdir(save_dir)
            raise ex
        self.suggestion_application = application_result
        if application_result is not None and application_result.failure:
            sub_logger.error(application_result.summary())
        return application_result

    def get_statistics_graph_label(self) -> str:
        res_str = "" + self.root_path + "\n"
        if self.execution_result is not None and self.execution_result.application_failed:
            res_str += "Suggestions not applied."
        elif self.execution_result is None:
            res_str += "Not executed."
        elif self.execution_result.compiled_only:
            res_str += "Compiled, not executed."
        else:
            res_str += str(round(self.execution_result.runtime, 3)) + "s"

        return res_str

    def get_statistics_graph_color(self) -> NodeColor:
        if self.execution_result is not None and self.execution_result.application_failed:
            return NodeColor.RED
        if self.execution_result is None:
            return NodeColor.ORANGE
        if self.execution_result.result_valid and self.execution_result.return_code == 0:
            return NodeColor.GREEN
        if self.execution_result.return_code == 0 and not self.execution_result.result_valid:
            return NodeColor.ORANGE
        return NodeColor.RED
