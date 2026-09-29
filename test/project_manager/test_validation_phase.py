# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import tempfile
import unittest
from typing import Any, List, Optional, Tuple
from unittest import mock

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations import validation
from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_validation_compile_script_path,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
)
from discopop_library.ProjectManager.configurations.validation import (
    has_validate_script,
    run_validation_phase,
)

CONFIG_NAME = "default"


def _arguments(project_root: str) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=project_root,
        full_execute=False,
        list=False,
        execute_configurations=CONFIG_NAME,
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


class TestRunValidationPhase(unittest.TestCase):
    """Covers the validation phase without ever running a real script.

    ``execute_configuration`` is stubbed so the tests assert on *which* scripts
    the phase decides to run, in which order, and on the verdict it derives.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_root = self._tmp_dir.name
        self.arguments = _arguments(self.project_root)
        self.project_config_dir = self.arguments.project_config_dir
        self.config_path = os.path.join(self.project_config_dir, CONFIG_NAME)
        os.makedirs(self.config_path)
        self.settings_path = os.path.join(self.project_config_dir, "par_settings.json")

        self.__write(get_shared_compile_script_path(self.project_config_dir))
        self.__write(self.settings_path)

        # scripts handed to execute_configuration, in call order
        self.executed: List[str] = []
        self.return_codes: dict[str, int] = {}

        def fake_execute_configuration(
            arguments: Any,
            project_copy_root_path: str,
            config_path: str,
            settings_path: str,
            script_path: str,
            thread_count: int,
            timeout: Optional[float] = None,
            process_started_callback: Any = None,
        ) -> Tuple[int, float, str, str]:
            self.executed.append(os.path.basename(script_path))
            return (self.return_codes.get(os.path.basename(script_path), 0), 1.0, "", "")

        patcher = mock.patch.object(validation, "execute_configuration", side_effect=fake_execute_configuration)
        self.fake_execute = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, path: str) -> str:
        with open(path, "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        return path

    def __add_validate_script(self) -> str:
        return self.__write(os.path.join(self.config_path, "validate.sh"))

    def __run(self, **kwargs: Any) -> validation.ValidationPhaseResult:
        return run_validation_phase(
            self.arguments,
            self.project_root,
            self.config_path,
            self.settings_path,
            1,
            **kwargs,
        )

    def test_no_validate_script_runs_nothing(self) -> None:
        result = self.__run()

        self.assertEqual(self.executed, [])
        self.assertFalse(result.applicable)
        self.assertFalse(result.compile_required)
        # without a validate.sh, execute.sh's outcome alone decides
        self.assertTrue(result.verdict(True))
        self.assertFalse(result.verdict(False))

    def test_validation_compile_script_without_validate_script_is_ignored(self) -> None:
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        result = self.__run()

        self.assertEqual(self.executed, [])
        self.assertFalse(result.applicable)

    def test_validate_script_alone_runs_no_extra_build(self) -> None:
        self.__add_validate_script()

        result = self.__run()

        self.assertEqual(self.executed, ["validate.sh"])
        self.assertTrue(result.applicable)
        self.assertFalse(result.compile_required)
        self.assertTrue(result.validate_successful)
        self.assertTrue(result.verdict(True))

    def test_failing_validate_script_invalidates_the_run(self) -> None:
        self.__add_validate_script()
        self.return_codes["validate.sh"] = 1

        result = self.__run()

        self.assertEqual(self.executed, ["validate.sh"])
        self.assertFalse(result.validate_successful)
        self.assertFalse(result.verdict(True))

    def test_separate_build_runs_before_validate_script(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        result = self.__run()

        self.assertEqual(self.executed, ["compile_validate.sh", "validate.sh"])
        self.assertTrue(result.compile_required)
        self.assertTrue(result.compile_successful)
        self.assertTrue(result.verdict(True))

    def test_per_config_override_is_preferred_for_the_separate_build(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))
        per_config = self.__write(get_per_config_validation_compile_script_path(self.project_config_dir, CONFIG_NAME))

        result = self.__run()

        self.assertEqual(result.compile_script_path, per_config)
        self.assertEqual(self.executed, ["compile_validate.sh", "validate.sh"])

    def test_failed_separate_build_skips_validation_and_invalidates_the_run(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))
        self.return_codes["compile_validate.sh"] = 2

        result = self.__run()

        self.assertEqual(self.executed, ["compile_validate.sh"])
        self.assertTrue(result.compile_required)
        self.assertFalse(result.compile_successful)
        self.assertIsNone(result.validate_result)
        self.assertFalse(result.verdict(True))

    def test_timeouts_are_passed_per_step(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        self.__run(timeout_compilation=11.0, timeout_validation=22.0)

        timeouts = [call.args[6] for call in self.fake_execute.call_args_list]
        self.assertEqual(timeouts, [11.0, 22.0])

    def test_progress_callbacks_receive_the_scripts(self) -> None:
        self.__add_validate_script()
        shared_validation_compile = self.__write(get_shared_validation_compile_script_path(self.project_config_dir))
        reported: List[Tuple[str, str]] = []

        self.__run(
            on_compile_start=lambda script: reported.append(("compile", script)),
            on_validate_start=lambda script: reported.append(("validate", script)),
        )

        self.assertEqual(
            reported,
            [
                ("compile", shared_validation_compile),
                ("validate", os.path.join(self.config_path, "validate.sh")),
            ],
        )

    def test_abort_before_the_separate_build(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        result = self.__run(should_abort=lambda: True)

        self.assertEqual(self.executed, [])
        self.assertTrue(result.aborted)
        self.assertFalse(result.verdict(True))

    def test_abort_between_the_separate_build_and_validation(self) -> None:
        self.__add_validate_script()
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))
        aborts = iter([False, True])

        result = self.__run(should_abort=lambda: next(aborts))

        self.assertEqual(self.executed, ["compile_validate.sh"])
        self.assertTrue(result.aborted)
        self.assertTrue(result.compile_successful)
        self.assertFalse(result.verdict(True))


class TestHasValidateScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_detects_presence_and_absence(self) -> None:
        self.assertFalse(has_validate_script(self._tmp_dir.name))
        with open(os.path.join(self._tmp_dir.name, "validate.sh"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        self.assertTrue(has_validate_script(self._tmp_dir.name))


if __name__ == "__main__":
    unittest.main()
