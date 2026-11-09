# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tempfile
import unittest
from typing import Any

from discopop_library.ProjectManager.configurations.project_environment import PROJECT_ENVIRONMENT_FILE
from mcp_server.tools import set_compile_script
from mcp_server.tools.helpers import ToolContext


class TestSetCompileScript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(self.configs_dir)
        os.makedirs(os.path.join(self.configs_dir, "default"))
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _handle(self, **kwargs: Any) -> Any:
        arguments = {"project_path": self.project_path, "script_body": "$CXX $CXXFLAGS main.cpp -o a.out\n"}
        arguments.update(kwargs)
        result = set_compile_script.handle(arguments, self.ctx)
        return json.loads(result[0].text)

    def test_omitted_config_name_writes_shared_script(self) -> None:
        data = self._handle()
        self.assertNotIn("status", data)
        self.assertNotIn("config_name", data)
        shared_path = os.path.join(self.configs_dir, "compile.sh")
        self.assertEqual(data["path"], shared_path)
        self.assertTrue(os.path.exists(shared_path))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "default", "compile.sh")))

    def test_valid_config_name_writes_per_config_script_only(self) -> None:
        data = self._handle(config_name="default")
        self.assertNotIn("status", data)
        self.assertEqual(data["config_name"], "default")
        per_config_path = os.path.join(self.configs_dir, "default", "compile.sh")
        self.assertEqual(data["path"], per_config_path)
        self.assertTrue(os.path.exists(per_config_path))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile.sh")))

    def test_purpose_validate_writes_shared_validation_script(self) -> None:
        data = self._handle(purpose="validate")
        self.assertNotIn("status", data)
        self.assertEqual(data["purpose"], "validate")
        shared_path = os.path.join(self.configs_dir, "compile_validate.sh")
        self.assertEqual(data["path"], shared_path)
        self.assertTrue(os.access(shared_path, os.X_OK))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile.sh")))

    def test_purpose_validate_with_config_name_writes_per_config_override(self) -> None:
        data = self._handle(purpose="validate", config_name="default")
        per_config_path = os.path.join(self.configs_dir, "default", "compile_validate.sh")
        self.assertEqual(data["path"], per_config_path)
        self.assertTrue(os.path.exists(per_config_path))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile_validate.sh")))

    def test_purpose_defaults_to_execute(self) -> None:
        data = self._handle()
        self.assertEqual(data["purpose"], "execute")
        self.assertNotIn("applies_to", data)

    def test_validation_scope_reports_configurations_without_validate_sh(self) -> None:
        os.makedirs(os.path.join(self.configs_dir, "other"))
        with open(os.path.join(self.configs_dir, "other", "validate.sh"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")

        data = self._handle(purpose="validate")

        self.assertEqual(data["applies_to"], {"used_by": ["other"], "ignored_for": ["default"]})

    def test_invalid_purpose_errors_without_writing(self) -> None:
        data = self._handle(purpose="bogus")
        self.assertEqual(data["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile.sh")))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile_validate.sh")))

    def test_nonexistent_config_name_errors_without_writing(self) -> None:
        data = self._handle(config_name="does_not_exist")
        self.assertEqual(data["status"], "error")
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "does_not_exist")))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "compile.sh")))

    def test_uninitialized_project_errors(self) -> None:
        with tempfile.TemporaryDirectory() as empty_project:
            arguments = {"project_path": empty_project, "script_body": "exit 0\n"}
            result = set_compile_script.handle(arguments, self.ctx)
            data = json.loads(result[0].text)
            self.assertEqual(data["status"], "error")

    def _stored_environment(self) -> Any:
        with open(os.path.join(self.configs_dir, PROJECT_ENVIRONMENT_FILE)) as f:
            return json.load(f)

    def test_instrumentation_scope_is_stored_relative_to_the_project_root(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        data = self._handle(instrumentation_scope="src")
        self.assertEqual(data["instrumentation_scope"], {"scope": "src", "warnings": []})
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": "src"})

    def test_absolute_instrumentation_scope_inside_the_project_is_stored_relative(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        data = self._handle(instrumentation_scope=os.path.join(self.project_path, "src"))
        self.assertEqual(data["instrumentation_scope"], {"scope": "src", "warnings": []})
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": "src"})

    def test_nonexistent_instrumentation_scope_is_stored_with_a_warning(self) -> None:
        data = self._handle(instrumentation_scope="missing")
        self.assertEqual(data["instrumentation_scope"]["scope"], "missing")
        self.assertEqual(len(data["instrumentation_scope"]["warnings"]), 1)
        self.assertIn("not an existing directory", data["instrumentation_scope"]["warnings"][0])
        # the scope is stored and the script is still written: the directory may be created by the build
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": "missing"})
        self.assertTrue(os.path.exists(data["path"]))

    def test_instrumentation_scope_outside_the_project_is_stored_absolute_with_a_warning(self) -> None:
        outside = os.path.normpath(os.path.join(self.project_path, "..", "outside_scope"))
        data = self._handle(instrumentation_scope="../outside_scope")
        self.assertEqual(data["instrumentation_scope"]["scope"], outside)
        self.assertIn("outside the project root", data["instrumentation_scope"]["warnings"][0])
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": outside})

    def test_omitted_instrumentation_scope_leaves_the_stored_scope_alone(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        stored = os.path.join(self.configs_dir, PROJECT_ENVIRONMENT_FILE)
        with open(stored, "w") as f:
            f.write('{"DP_PROJECT_ROOT_DIR": "src"}\n')
        data = self._handle()
        self.assertNotIn("instrumentation_scope", data)
        with open(stored) as f:
            self.assertEqual(f.read(), '{"DP_PROJECT_ROOT_DIR": "src"}\n')

    def test_omitted_instrumentation_scope_creates_no_environment_file(self) -> None:
        data = self._handle()
        self.assertNotIn("instrumentation_scope", data)
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, PROJECT_ENVIRONMENT_FILE)))

    def test_instrumentation_scope_with_config_name_is_stored_project_wide(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        data = self._handle(config_name="default", instrumentation_scope="src")
        self.assertEqual(data["config_name"], "default")
        self.assertEqual(data["instrumentation_scope"]["scope"], "src")
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": "src"})
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "default", PROJECT_ENVIRONMENT_FILE)))

    def test_instrumentation_scope_with_purpose_validate_is_stored_project_wide(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        data = self._handle(purpose="validate", instrumentation_scope="src")
        self.assertEqual(data["purpose"], "validate")
        self.assertEqual(data["instrumentation_scope"]["scope"], "src")
        self.assertEqual(self._stored_environment(), {"DP_PROJECT_ROOT_DIR": "src"})
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "compile_validate.sh")))


if __name__ == "__main__":
    unittest.main()
