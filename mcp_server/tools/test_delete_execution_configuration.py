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

from mcp_server.tools import delete_execution_configuration
from mcp_server.tools.helpers import ToolContext


class TestDeleteExecutionConfiguration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        for name in ("small", "large"):
            os.makedirs(os.path.join(self.configs_dir, name))
            with open(os.path.join(self.configs_dir, name, "execute.sh"), "w") as f:
                f.write("#!/bin/bash\n./a.out\n")
        with open(os.path.join(self.configs_dir, "seq_settings.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.configs_dir, "compile.sh"), "w") as f:
            f.write("#!/bin/bash\n$CXX $CXXFLAGS main.cpp\n")
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _handle(self, config_name: str) -> Any:
        arguments = {"project_path": self.project_path, "config_name": config_name}
        return json.loads(delete_execution_configuration.handle(arguments, self.ctx)[0].text)

    def test_deletes_the_configuration_directory_only(self) -> None:
        data = self._handle("large")
        self.assertEqual(data["status"], "success")
        self.assertFalse(os.path.exists(os.path.join(self.configs_dir, "large")))
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "small", "execute.sh")))
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "seq_settings.json")))

    def test_deleting_the_last_configuration_asks_for_a_new_one(self) -> None:
        self._handle("large")
        data = self._handle("small")
        self.assertIn("create_execution_configuration", data["next_step"])

    def test_an_unknown_name_lists_the_defined_configurations(self) -> None:
        data = self._handle("medium")
        self.assertEqual(data["status"], "error")
        self.assertIn("large", data["message"])
        self.assertIn("small", data["message"])

    def test_names_outside_the_configuration_directory_are_refused(self) -> None:
        for name in (
            "",
            ".",
            "..",
            "../configs",
            "small/..",
            "small/../large",
            "seq_settings.json",
            os.path.abspath(self.project_path),
        ):
            with self.subTest(name=name):
                self.assertEqual(self._handle(name)["status"], "error")
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "small")))
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "large")))
        self.assertTrue(os.path.exists(os.path.join(self.configs_dir, "seq_settings.json")))

    def test_a_symlink_to_another_configuration_is_refused(self) -> None:
        os.symlink(os.path.join(self.configs_dir, "large"), os.path.join(self.configs_dir, "alias"))
        self.assertEqual(self._handle("alias")["status"], "error")
        self.assertTrue(os.path.isdir(os.path.join(self.configs_dir, "large")))

    def test_a_symlink_to_another_directory_is_refused(self) -> None:
        outside = os.path.join(self.project_path, "data")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(self.configs_dir, "linked"))
        self.assertEqual(self._handle("linked")["status"], "error")
        self.assertTrue(os.path.isdir(outside))


if __name__ == "__main__":
    unittest.main()
