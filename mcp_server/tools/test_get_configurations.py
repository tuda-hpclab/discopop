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

from mcp_server.tools import get_configurations
from mcp_server.tools.helpers import ToolContext


class TestGetConfigurations(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(self.configs_dir, "default"))
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _handle(self) -> Any:
        result = get_configurations.handle({"project_path": self.project_path}, self.ctx)
        return json.loads(result[0].text)

    def __write(self, *parts: str, content: str = "#!/bin/bash\nexit 0\n") -> None:
        with open(os.path.join(self.configs_dir, *parts), "w") as f:
            f.write(content)

    def test_absent_optional_scripts_are_reported_as_null(self) -> None:
        self.__write("compile.sh")
        self.__write("default", "execute.sh")

        data = self._handle()

        self.assertEqual(data["status"], "success")
        self.assertIsNone(data["validation_compile_script"])
        config = data["configurations"][0]
        self.assertEqual(config["name"], "default")
        self.assertIsNotNone(config["execute_script"])
        self.assertIsNone(config["compile_script_override"])
        self.assertIsNone(config["validate_script"])
        self.assertIsNone(config["validation_compile_script"])

    def test_shared_and_per_config_scripts_are_reported(self) -> None:
        self.__write("compile.sh", content="shared compile\n")
        self.__write("compile_validate.sh", content="shared validation build\n")
        self.__write("default", "execute.sh", content="run\n")
        self.__write("default", "compile.sh", content="override compile\n")
        self.__write("default", "validate.sh", content="check output\n")
        self.__write("default", "compile_validate.sh", content="override validation build\n")

        data = self._handle()

        self.assertEqual(data["compile_script"], "shared compile\n")
        self.assertEqual(data["validation_compile_script"], "shared validation build\n")
        config = data["configurations"][0]
        self.assertEqual(config["execute_script"], "run\n")
        self.assertEqual(config["compile_script_override"], "override compile\n")
        self.assertEqual(config["validate_script"], "check output\n")
        self.assertEqual(config["validation_compile_script"], "override validation build\n")

    def test_uninitialized_project_reports_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as empty_project:
            result = get_configurations.handle({"project_path": empty_project}, self.ctx)
            data = json.loads(result[0].text)

        self.assertEqual(data["status"], "success")
        self.assertIsNone(data["compile_script"])
        self.assertIsNone(data["validation_compile_script"])
        self.assertEqual(data["configurations"], [])


if __name__ == "__main__":
    unittest.main()
