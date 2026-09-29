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

    def test_omitted_compile_script_body_creates_only_execute_sh(self) -> None:
        data = self._handle()
        self.assertEqual(data["status"], "success")
        self.assertNotIn("compile_script_path", data)
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "default", "execute.sh")))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "default", "compile.sh")))

    def test_compile_script_body_creates_per_config_override(self) -> None:
        data = self._handle(compile_script_body="$CXX $CXXFLAGS main.cpp -o a.out\n")
        self.assertEqual(data["status"], "success")
        compile_path = os.path.join(self.configs_dir, "default", "compile.sh")
        self.assertEqual(data["compile_script_path"], compile_path)
        self.assertTrue(os.path.exists(compile_path))
        self.assertTrue(os.access(compile_path, os.X_OK))

    def test_validate_script_body_creates_validate_sh(self) -> None:
        data = self._handle(validate_script_body="./a.out | diff - reference.txt\n")
        self.assertEqual(data["status"], "success")
        validate_path = os.path.join(self.configs_dir, "default", "validate.sh")
        self.assertEqual(data["validate_script_path"], validate_path)
        self.assertTrue(os.access(validate_path, os.X_OK))
        self.assertNotIn("validation_compile_script_path", data)

    def test_validation_compile_script_body_creates_override_alongside_validate_sh(self) -> None:
        data = self._handle(
            validate_script_body="./a.out | diff - reference.txt\n",
            validation_compile_script_body="$CXX $CXXFLAGS -DVALIDATE main.cpp -o a.out\n",
        )
        self.assertEqual(data["status"], "success")
        validation_compile_path = os.path.join(self.configs_dir, "default", "compile_validate.sh")
        self.assertEqual(data["validation_compile_script_path"], validation_compile_path)
        self.assertTrue(os.access(validation_compile_path, os.X_OK))

    def test_validation_compile_script_body_without_validate_sh_errors(self) -> None:
        data = self._handle(validation_compile_script_body="$CXX $CXXFLAGS main.cpp -o a.out\n")
        self.assertEqual(data["status"], "error")
        # nothing at all is written, not even execute.sh's directory content
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "default", "compile_validate.sh")))
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "default", "execute.sh")))

    def test_validation_compile_script_body_accepts_preexisting_validate_sh(self) -> None:
        os.makedirs(os.path.join(self.configs_dir, "default"))
        with open(os.path.join(self.configs_dir, "default", "validate.sh"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")

        data = self._handle(validation_compile_script_body="$CXX $CXXFLAGS -DVALIDATE main.cpp -o a.out\n")

        self.assertEqual(data["status"], "success")
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "default", "compile_validate.sh")))


if __name__ == "__main__":
    unittest.main()
