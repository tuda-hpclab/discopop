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
from typing import Any, Callable, Dict, List, Optional, Sequence
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
from discopop_library.ProjectManager.configurations.build_sharing import build_owner_of
from discopop_library.ProjectManager.configurations.building import (
    BuildResult,
    build_lock,
    check_suggestions,
    ensure_build,
)
from discopop_library.ProjectManager.configurations.builds import (
    INCREMENTAL_MODES,
    BuildKey,
    BuildPolicy,
    invalidate_build,
    kept_tree_path_of,
)

logger = logging.getLogger("CodeConfiguration")

# the directories of the project's .discopop a candidate does not need
AUTOTUNER_LEFT_OUT_OF_COPIES = ("profiler", "explorer")

# the modes of the settings files a candidate is compiled with
_MODE_OF_SETTINGS = {"seq_settings.json": "seq", "par_settings.json": "par"}


def uses_kept_build_trees(arguments: AutotunerArguments, settings_name: str) -> bool:
    """Whether candidates with ``settings_name`` are compiled in the kept build tree of their mode (one after the
    other, incrementally if the configuration has a compile_incremental.sh) instead of in copies of their own.

    Not with ``--skip-cleanup`` (which keeps every candidate's code), not with ``--no-kept-build-trees`` and not for
    instrumented candidates (``hd``: the hotspot comparison needs two of them at once)."""
    return (
        arguments.kept_build_trees
        and not arguments.skip_cleanup
        and _MODE_OF_SETTINGS.get(settings_name) in INCREMENTAL_MODES
    )


def _project_manager_arguments(
    arguments: AutotunerArguments, timeout: Optional[float], suggestions: Sequence[str] = ()
) -> ProjectManagerArguments:
    return ProjectManagerArguments(
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
        apply_suggestions=",".join(suggestions) if suggestions else None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_compilation=timeout,
        timeout_execution=timeout,
        timeout_validation=timeout,
    )


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
        # the build of a candidate in a kept build tree (uses_kept_build_trees), None for a copy of its own
        self.kept_key: Optional[BuildKey] = None
        logger.debug("Created configuration: " + root_path)

    def __str__(self) -> str:
        return self.label

    @property
    def label(self) -> str:
        """What names the configuration in logs and the statistics graph: its directory, or, in a kept build tree
        that holds every candidate in turn, the build tree with the applied suggestions."""
        if self.kept_key is None:
            return self.root_path
        return self.root_path + " [" + (", ".join(self.kept_key.suggestions) or "no suggestions") + "]"

    def execute(
        self, arguments: AutotunerArguments, timeout: Optional[float], thread_count: int, is_initial: bool = False
    ) -> None:
        if self.record_failed_application():
            return
        # ``timeout`` is derived from the reference configuration's *runtime*, which
        # says nothing about how long a build may take: a program running for a second
        # may well take minutes to compile. Builds are therefore never bounded by it.
        if self.kept_key is not None and not arguments.compile_only:
            # the tree holds one candidate at a time: build and run it without another build in between
            with build_lock(_project_manager_arguments(arguments, timeout), self.kept_key):
                if self._compile_in_kept_tree(arguments, thread_count):
                    self.execute_only(arguments, timeout, thread_count, is_initial)
            return
        compilation_successful = self.compile_only(arguments, thread_count, is_initial)
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

    def compile_only(self, arguments: AutotunerArguments, thread_count: int, is_initial: bool = False) -> bool:
        """Build the configuration; returns whether the build succeeded.

        A build has no time limit: the autotuner's timeout is derived from the runtime
        of the reference configuration and bounds runs, never compilations.
        """
        if self.kept_key is not None:
            with build_lock(_project_manager_arguments(arguments, None), self.kept_key):
                return self._compile_in_kept_tree(arguments, thread_count)
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
            None,
        )

        if ret is None or ret[0] != 0:
            message = "Error during compilation of " + self.root_path
            if ret is not None:
                message += " (return code " + str(ret[0]) + ")"
                if ret[3]:
                    message += "\nSTDERR: " + ret[3]
            print(message)
            self.execution_result = ExecutionResult(0.1, 1, False, False, compilation_failed=True)
            compilation_successful = False
        return compilation_successful

    def _compile_in_kept_tree(self, arguments: AutotunerArguments, thread_count: int) -> bool:
        """Make the kept build tree hold this candidate (``configurations/building.py``: the tree is updated, and
        compiled incrementally if the configuration has a compile_incremental.sh). The caller holds the lock. Like
        every build of the autotuner, it has no time limit (see compile_only)."""
        assert self.kept_key is not None
        key = self.kept_key
        pm_arguments = _project_manager_arguments(arguments, None, key.suggestions)
        project_config_dir = pm_arguments.project_config_dir
        settings_path = os.path.join(project_config_dir, self.settings_name)
        if not os.path.exists(settings_path):
            settings_path = os.path.join(project_config_dir, arguments.configuration, self.settings_name)
        outcome = ensure_build(
            pm_arguments,
            key,
            os.path.join(project_config_dir, key.configuration),
            settings_path,
            resolve_compile_script_path(project_config_dir, key.configuration),
            thread_count,
            BuildPolicy.AUTO,
            timeout=None,
            message=lambda text: logger.debug(text.rstrip()),
        )
        if outcome.result in (BuildResult.BUILT, BuildResult.REUSED) and outcome.tree is not None:
            self.root_path = outcome.tree
            self.config_dot_dp_path = os.path.join(outcome.tree, ".discopop")
            return True
        if outcome.result == BuildResult.APPLICATION_FAILED and outcome.application_result is not None:
            self.suggestion_application = outcome.application_result
            self.record_failed_application()
            return False
        stderr = outcome.compile_result[3] if outcome.compile_result is not None else outcome.message
        print("Error during compilation!\nSTDERR: " + stderr)
        self.execution_result = ExecutionResult(0.1, 1, False, False, compilation_failed=True)
        return False

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
            timeout_compilation=None,
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
                # a build, which the runtime derived timeout must not bound (see compile_only)
                timeout_compilation=None,
                timeout_validation=timeout,
            )
            if validation.compile_required and self.kept_key is not None:
                # the validation build changed the kept tree: the next candidate is compiled in full
                invalidate_build(cm_args.project_dir, self.kept_key)
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
        if uses_kept_build_trees(arguments, settings_name):
            # nothing is copied: the candidate is compiled in the kept build tree of its mode when it is executed
            project_config_dir = os.path.join(arguments.dot_dp_path, "project", "configs")
            key = BuildKey(
                build_owner_of(project_config_dir, arguments.configuration), _MODE_OF_SETTINGS[settings_name]
            )
            tree = kept_tree_path_of(arguments.project_path, key)
            configuration = CodeConfiguration(tree, os.path.join(tree, ".discopop"), settings_name)
            configuration.kept_key = key
            return configuration
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
            # the profiling data and the pattern detection results are not needed by a candidate (it compiles and
            # runs, the patches are in patch_generator); the hotspot data stays for the comparison of hd candidates
            leave_out_of_dot_discopop=AUTOTUNER_LEFT_OUT_OF_COPIES,
        )
        new_dot_discopop_path = os.path.join(dest_path, ".discopop")

        # create a new CodeConfiguration object
        return CodeConfiguration(dest_path, new_dot_discopop_path, settings_name)

    def deleteFolder(self) -> None:
        if self.kept_key is not None:
            return  # the kept build tree serves the next candidate
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

        if self.kept_key is not None:
            # applied when the candidate is compiled; checked now, so that callers see a failure as before
            self.kept_key = BuildKey(self.kept_key.configuration, self.kept_key.mode, tuple(suggestion_ids_str))
            application_result = check_suggestions(
                _project_manager_arguments(arguments, None, suggestion_ids_str), self.kept_key
            )
            self.suggestion_application = application_result
            if application_result is not None and application_result.failure:
                sub_logger.error(application_result.summary())
            return application_result

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
        res_str = "" + self.label + "\n"
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
