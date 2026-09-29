# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The optional output-validation phase of a configuration run.

A run consists of a build, the timed ``execute.sh`` run and -- when the
configuration provides a ``validate.sh`` -- an untimed validation run. Since
``validate.sh`` may need a differently compiled binary than ``execute.sh``, the
validation phase may perform a build of its own. That build deliberately happens
*after* the timed ``execute.sh`` run, so it can never clobber the binary whose
runtime is being measured.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import (
    resolve_validation_compile_script_path,
    validation_needs_separate_compile,
)
from discopop_library.ProjectManager.configurations.execution import execute_configuration

PATH = str

VALIDATE_SCRIPT_NAME = "validate.sh"

logger = logging.getLogger("ConfigurationManager")

ExecutionOutcome = Tuple[int, float, str, str]


def get_validate_script_path(config_path: PATH) -> PATH:
    return os.path.join(config_path, VALIDATE_SCRIPT_NAME)


def has_validate_script(config_path: PATH) -> bool:
    return os.path.exists(get_validate_script_path(config_path))


@dataclass
class ValidationPhaseResult:
    """Outcome of the validation phase of a single configuration run."""

    #: The configuration's validate.sh, or None if it does not define one.
    validate_script_path: Optional[PATH] = None
    #: The separate validation build script, or None if no separate build was required.
    compile_script_path: Optional[PATH] = None
    #: Result of the validation build, or None if it was not run.
    compile_result: Optional[ExecutionOutcome] = None
    #: Result of validate.sh, or None if it was not run.
    validate_result: Optional[ExecutionOutcome] = None
    #: Whether the phase was cut short by the caller's abort signal.
    aborted: bool = False

    @property
    def applicable(self) -> bool:
        """Whether the configuration defines a validate.sh at all."""
        return self.validate_script_path is not None

    @property
    def compile_required(self) -> bool:
        """Whether validate.sh needed a build separate from the execute.sh build."""
        return self.compile_script_path is not None

    @property
    def compile_successful(self) -> bool:
        return self.compile_result is not None and self.compile_result[0] == 0

    @property
    def validate_successful(self) -> bool:
        return self.validate_result is not None and self.validate_result[0] == 0

    def verdict(self, execute_successful: bool) -> bool:
        """Whether the run counts as correct.

        Without a validate.sh, execute.sh's exit code alone decides. With one,
        both its build and validate.sh itself must have succeeded.
        """
        if not self.applicable:
            return execute_successful
        return self.validate_successful


def run_validation_phase(
    arguments: ProjectManagerArguments,
    project_copy_root_path: PATH,
    config_path: PATH,
    settings_path: PATH,
    thread_count: int,
    timeout_compilation: Optional[float] = None,
    timeout_validation: Optional[float] = None,
    process_started_callback: Optional[Callable[["subprocess.Popen[bytes]"], None]] = None,
    on_compile_start: Optional[Callable[[PATH], None]] = None,
    on_validate_start: Optional[Callable[[PATH], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
) -> ValidationPhaseResult:
    """Builds for validation if required, then runs validate.sh.

    Must be called after a successful ``execute.sh`` run. Returns immediately if
    the configuration defines no ``validate.sh``; a ``compile_validate.sh``
    without a ``validate.sh`` is deliberately ignored, since there would be
    nothing to run against that build.

    ``on_compile_start`` / ``on_validate_start`` are invoked with the script
    about to be run so callers can report progress. ``should_abort`` is polled
    before each step.
    """
    result = ValidationPhaseResult()

    validate_script_path = get_validate_script_path(config_path)
    if not os.path.exists(validate_script_path):
        return result
    result.validate_script_path = validate_script_path

    project_config_dir = os.path.dirname(config_path)
    config_name = os.path.basename(config_path)

    if validation_needs_separate_compile(project_config_dir, config_name):
        if should_abort is not None and should_abort():
            result.aborted = True
            return result

        compile_script_path = resolve_validation_compile_script_path(project_config_dir, config_name)
        result.compile_script_path = compile_script_path
        logger.debug("validation requires a separate build via: " + compile_script_path)
        if on_compile_start is not None:
            on_compile_start(compile_script_path)

        result.compile_result = execute_configuration(
            arguments,
            project_copy_root_path,
            config_path,
            settings_path,
            compile_script_path,
            thread_count,
            timeout_compilation,
            process_started_callback=process_started_callback,
        )
        if not result.compile_successful:
            return result

    if should_abort is not None and should_abort():
        result.aborted = True
        return result

    if on_validate_start is not None:
        on_validate_start(validate_script_path)

    result.validate_result = execute_configuration(
        arguments,
        project_copy_root_path,
        config_path,
        settings_path,
        validate_script_path,
        thread_count,
        timeout_validation,
        process_started_callback=process_started_callback,
    )
    return result
