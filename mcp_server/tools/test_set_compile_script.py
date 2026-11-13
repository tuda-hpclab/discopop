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

    def _stored(self, name: str) -> Any:
        with open(os.path.join(self.project_path, ".discopop", "project", name + "_directories.json")) as f:
            return json.load(f)[name + "_directories"]

    def test_project_directories_are_stored(self) -> None:
        os.makedirs(os.path.join(self.project_path, "build", "_deps"))
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        shared = os.path.realpath(outside.name)
        data = self._handle(excluded_directories=["./build/_deps/"], included_directories=[shared])
        self.assertEqual(
            data["project_directories"], {"included": [shared], "excluded": ["build/_deps"], "warnings": []}
        )
        self.assertEqual(self._stored("excluded"), ["build/_deps"])
        self.assertEqual(self._stored("included"), [shared])

    def test_unusable_entries_are_dropped_with_warnings(self) -> None:
        data = self._handle(excluded_directories=["/abs", "later"], included_directories=["rel", self.project_path])
        self.assertEqual(data["project_directories"]["excluded"], ["later"])
        self.assertEqual(data["project_directories"]["included"], [])
        self.assertEqual(len(data["project_directories"]["warnings"]), 4)
        # the script is still written
        self.assertTrue(os.path.exists(data["path"]))

    def test_unchanged_lists_do_not_rewrite_the_files(self) -> None:
        # the files' mtimes mark the analysis as stale, so unchanged lists must not touch them
        os.makedirs(os.path.join(self.project_path, "src"))
        self._handle(excluded_directories=["src"])
        stored = os.path.join(self.project_path, ".discopop", "project", "excluded_directories.json")
        os.utime(stored, (1000.0, 1000.0))
        self._handle(excluded_directories=["./src/"])
        self.assertEqual(os.path.getmtime(stored), 1000.0)

    def test_omitted_lists_are_left_alone(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        self._handle(excluded_directories=["src"])
        data = self._handle()
        self.assertNotIn("project_directories", data)
        self.assertEqual(self._stored("excluded"), ["src"])
        self.assertFalse(
            os.path.exists(os.path.join(self.project_path, ".discopop", "project", "included_directories.json"))
        )

    def test_project_directories_with_config_name_apply_project_wide(self) -> None:
        os.makedirs(os.path.join(self.project_path, "src"))
        data = self._handle(config_name="default", excluded_directories=["src"])
        self.assertEqual(data["config_name"], "default")
        self.assertEqual(self._stored("excluded"), ["src"])


if __name__ == "__main__":
    unittest.main()
