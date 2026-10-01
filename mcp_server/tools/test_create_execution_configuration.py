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

from mcp_server.tools import create_execution_configuration
from mcp_server.tools.helpers import ToolContext


class TestCreateExecutionConfiguration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(self.configs_dir)
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _handle(self, **kwargs: Any) -> Any:
        arguments = {"project_path": self.project_path, "config_name": "default", "script_body": "./a.out\n"}
        arguments.update(kwargs)
        result = create_execution_configuration.handle(arguments, self.ctx)
        return json.loads(result[0].text)

    def test_creates_only_execute_sh(self) -> None:
        data = self._handle()
        self.assertEqual(data["status"], "success")
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "default", "execute.sh")))
        self.assertEqual(os.listdir(os.path.join(self.configs_dir, "default")), ["execute.sh"])

    def test_compile_scripts_are_only_set_via_set_compile_script(self) -> None:
        properties = create_execution_configuration.TOOL.inputSchema["properties"]
        self.assertNotIn("compile_script_body", properties)
        self.assertNotIn("validation_compile_script_body", properties)

    def test_validate_script_body_creates_validate_sh(self) -> None:
        data = self._handle(validate_script_body="./a.out | diff - reference.txt\n")
        self.assertEqual(data["status"], "success")
        validate_path = os.path.join(self.configs_dir, "default", "validate.sh")
        self.assertEqual(data["validate_script_path"], validate_path)
        self.assertTrue(os.access(validate_path, os.X_OK))
        self.assertEqual(sorted(os.listdir(os.path.join(self.configs_dir, "default"))), ["execute.sh", "validate.sh"])

    def test_a_repeated_call_keeps_a_validate_sh_it_is_not_given(self) -> None:
        self._handle(validate_script_body="./a.out | diff - reference.txt\n")
        data = self._handle(script_body="./a.out --small\n")
        self.assertEqual(data["status"], "success")
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "default", "validate.sh")))
        with open(os.path.join(self.configs_dir, "default", "execute.sh")) as f:
            self.assertIn("--small", f.read())


if __name__ == "__main__":
    unittest.main()
