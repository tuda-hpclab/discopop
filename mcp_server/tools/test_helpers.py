# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from mcp_server.tools import (
    create_execution_configuration,
    gather_data,
    initialize_discopop_directory,
    set_compile_script,
)
from mcp_server.tools.helpers import (
    ToolContext,
    compile_script_configured,
    configuration_names,
    setup_next_step,
    unknown_configuration_message,
)


class TestSetupState(unittest.TestCase):
    """What the setup tools read from a project to decide which step is still missing."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.configs_dir = Path(self._tmp_dir.name) / ".discopop" / "project" / "configs"

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, relative: str, content: str = "#!/bin/bash\n./app\n") -> None:
        path = self.configs_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_the_initial_placeholder_is_not_a_configured_compile_script(self) -> None:
        self.__write("compile.sh", "echo 'compile.sh has not been configured yet. Use set_compile_script.'\nexit 1\n")
        self.assertFalse(compile_script_configured(self.configs_dir))

    def test_a_real_script_that_bails_out_with_exit_1_is_configured(self) -> None:
        # The check used to test for "exit 1", which misread every such script.
        self.__write("compile.sh", "$CXX $CXXFLAGS main.cpp -o app || exit 1\n")
        self.assertTrue(compile_script_configured(self.configs_dir))

    def test_only_configurations_with_an_execute_script_count(self) -> None:
        self.__write("small/execute.sh")
        (self.configs_dir / "empty").mkdir()
        self.assertEqual(configuration_names(self.configs_dir), ["small"])

    def test_the_next_step_follows_what_is_missing(self) -> None:
        self.assertIn("initialize_discopop_directory", setup_next_step(self.configs_dir))
        self.configs_dir.mkdir(parents=True)
        self.assertIn("set_compile_script", setup_next_step(self.configs_dir))
        self.__write("compile.sh", "$CXX $CXXFLAGS main.cpp -o app\n")
        self.assertIn("create_execution_configuration", setup_next_step(self.configs_dir))
        self.__write("small/execute.sh")
        self.assertIn("gather_data", setup_next_step(self.configs_dir))

    def test_a_single_configuration_is_told_how_to_enable_hotspot_detection(self) -> None:
        self.__write("compile.sh", "$CXX $CXXFLAGS main.cpp -o app\n")
        self.__write("small/execute.sh")
        self.assertIn("second configuration", setup_next_step(self.configs_dir))

    def test_two_configurations_are_proposed_for_hotspot_detection(self) -> None:
        self.__write("compile.sh", "$CXX $CXXFLAGS main.cpp -o app\n")
        self.__write("small/execute.sh")
        self.__write("medium/execute.sh")
        next_step = setup_next_step(self.configs_dir)
        self.assertIn("hotspot_config_names", next_step)
        self.assertIn("'medium', 'small'", next_step)

    def test_an_unknown_configuration_is_answered_with_the_defined_ones(self) -> None:
        self.__write("small/execute.sh")
        message = unknown_configuration_message(self.configs_dir, "large")
        self.assertIn("'large' not found", message)
        self.assertIn("small", message)
        self.assertIn("get_configurations", message)

    def test_an_unknown_configuration_without_any_defined_names_how_to_create_one(self) -> None:
        self.configs_dir.mkdir(parents=True)
        self.assertIn("create_execution_configuration", unknown_configuration_message(self.configs_dir, "large"))


class TestSetupChain(unittest.TestCase):
    """Each setup tool's result names the step that is still missing, up to gather_data."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __call(self, tool: Any, **arguments: Any) -> Any:
        data = json.loads(tool.handle({"project_path": self.project_path, **arguments}, self.ctx)[0].text)
        self.assertEqual(data["status"], "success", data)
        return data

    def test_the_results_lead_from_initialization_to_gather_data(self) -> None:
        data = self.__call(initialize_discopop_directory)
        self.assertIn("set_compile_script", data["next_step"])

        # Repeating the call changes nothing and still names the same missing step.
        data = self.__call(initialize_discopop_directory)
        self.assertTrue(data["already_initialized"])
        self.assertIn("set_compile_script", data["next_step"])

        data = self.__call(set_compile_script, script_body="$CXX $CXXFLAGS main.cpp -o app || exit 1")
        self.assertIn("create_execution_configuration", data["next_step"])

        data = self.__call(create_execution_configuration, config_name="small", script_body="./app")
        self.assertIn("gather_data", data["next_step"])

        data = self.__call(initialize_discopop_directory)
        self.assertIn("gather_data", data["next_step"])

    def test_a_missing_settings_file_is_recreated_instead_of_reported_as_initialized(self) -> None:
        self.__call(initialize_discopop_directory)
        dp_settings = os.path.join(self.project_path, ".discopop", "project", "configs", "dp_settings.json")
        os.remove(dp_settings)
        data = self.__call(initialize_discopop_directory)
        self.assertNotIn("already_initialized", data)
        self.assertEqual(data["created_files"], [os.path.join(".discopop", "project", "configs", "dp_settings.json")])
        self.assertTrue(os.path.exists(dp_settings))

    def test_configuration_names_cannot_leave_the_configuration_directory(self) -> None:
        self.__call(initialize_discopop_directory)
        self.__call(create_execution_configuration, config_name="small", script_body="./app")
        project_compile_sh = os.path.join(self.project_path, "compile.sh")
        for name in ("..", "../../..", ".", "small/..", "small/../small", self.project_path):
            with self.subTest(name=name):
                for tool, extra in (
                    (set_compile_script, {"script_body": "$CXX main.cpp"}),
                    (create_execution_configuration, {"script_body": "./app"}),
                ):
                    result = tool.handle({"project_path": self.project_path, "config_name": name, **extra}, self.ctx)
                    data = json.loads(result[0].text)
                    self.assertEqual(data["status"], "error", (tool.TOOL.name, data))
                    self.assertIn("Invalid config_name", data["message"])
        self.assertFalse(os.path.exists(project_compile_sh))

    def test_a_reset_names_the_next_step_as_well(self) -> None:
        self.__call(initialize_discopop_directory)
        self.assertIn("set_compile_script", self.__call(initialize_discopop_directory, reset=True)["next_step"])

    def test_a_compile_override_for_an_unknown_configuration_lists_the_defined_ones(self) -> None:
        self.__call(initialize_discopop_directory)
        self.__call(create_execution_configuration, config_name="small", script_body="./app")
        result = set_compile_script.handle(
            {"project_path": self.project_path, "script_body": "$CXX main.cpp", "config_name": "large"}, self.ctx
        )
        message = json.loads(result[0].text)["message"]
        self.assertIn("'large' not found", message)
        self.assertIn("small", message)


class TestAppliedSuggestionsSurviveReanalysis(unittest.TestCase):
    """The applicator's record of applied suggestions is what a rollback needs; the analysis deletes it."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)
        initialize_discopop_directory.handle({"project_path": self.project_path}, self.ctx)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_gather_data_refuses_while_suggestions_are_applied(self) -> None:
        with (
            mock.patch.object(gather_data, "recorded_applied_suggestions", return_value=(["3"], None)),
            mock.patch.object(gather_data, "_pipeline") as pipeline,
        ):
            result = gather_data.handle({"project_path": self.project_path, "config_name": "small"}, self.ctx)
        data = json.loads(result[0].text)
        self.assertEqual(data["status"], "error")
        self.assertIn("manage_patches(action='clear')", data["message"])
        pipeline.assert_not_called()

    def test_a_reset_rolls_the_applied_suggestions_back_first(self) -> None:
        clear = mock.Mock(return_value=(subprocess.CompletedProcess([], 0, "", ""), None))
        with (
            mock.patch.object(
                initialize_discopop_directory, "recorded_applied_suggestions", return_value=(["3"], None)
            ),
            mock.patch.object(initialize_discopop_directory, "run_patch_applicator", clear),
            mock.patch.object(initialize_discopop_directory, "reset_project") as reset,
        ):
            reset.side_effect = lambda _args: self.assertEqual(clear.call_count, 1)
            result = initialize_discopop_directory.handle({"project_path": self.project_path, "reset": True}, self.ctx)
        data = json.loads(result[0].text)
        self.assertEqual(clear.call_args.args[1], ["--clear"])
        self.assertEqual(data["rolled_back_suggestions"], ["3"])
        self.assertNotIn("warning", data)

    def test_a_reset_whose_rollback_fails_warns_that_patches_may_remain(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "patch: can't find file", "")
        with (
            mock.patch.object(
                initialize_discopop_directory, "recorded_applied_suggestions", return_value=(["3"], None)
            ),
            mock.patch.object(initialize_discopop_directory, "run_patch_applicator", return_value=(failed, None)),
            mock.patch.object(initialize_discopop_directory, "reset_project"),
        ):
            result = initialize_discopop_directory.handle({"project_path": self.project_path, "reset": True}, self.ctx)
        data = json.loads(result[0].text)
        self.assertEqual(data["status"], "success")
        self.assertIn("by hand", data["warning"])
        self.assertNotIn("rolled_back_suggestions", data)


class TestLogCall(unittest.TestCase):
    def test_a_project_path_without_a_discopop_directory_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            missing = os.path.join(parent, "mistyped")
            ToolContext(debug=False).log_call("get_configurations", {"project_path": missing})
            self.assertFalse(os.path.exists(missing))

    def test_script_bodies_are_logged_by_size_only(self) -> None:
        with tempfile.TemporaryDirectory() as project_path:
            os.mkdir(os.path.join(project_path, ".discopop"))
            ToolContext(debug=False).log_call(
                "create_execution_configuration",
                {"project_path": project_path, "script_body": "./a.out\n", "validate_script_body": "diff out ref\n"},
            )
            log = (Path(project_path) / ".discopop" / "mcp_server" / "log.txt").read_text()
        self.assertNotIn("diff out ref", log)
        self.assertIn("validate_script_body=<13 chars>", log)
        self.assertIn("script_body=<8 chars>", log)


if __name__ == "__main__":
    unittest.main()
