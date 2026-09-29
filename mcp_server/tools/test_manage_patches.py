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
from typing import Any
from unittest import mock

from mcp_server.tools import manage_patches
from mcp_server.tools.helpers import applicator_failure_details
from mcp_server.tools.helpers import ToolContext


class TestApplicatorFailureDetails(unittest.TestCase):
    """What a caller is told when discopop_patch_applicator gives up.

    The applicator reports the reason on stdout and leaves stderr empty, so an error
    built from stderr alone is a bare return code -- which is exactly what made the
    documented recovery ("run clear first") a dead end.
    """

    def __process(self, stdout: str = "", stderr: str = "") -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(
            args=["discopop_patch_applicator"], returncode=1, stdout=stdout, stderr=stderr
        )

    def test_stdout_is_part_of_the_report(self) -> None:
        output, _cause = applicator_failure_details(self.__process(stdout="STDOUT: \nHunk #1 FAILED at 17."))
        self.assertIn("Hunk #1 FAILED at 17.", output)

    def test_a_patch_that_no_longer_matches_is_named_as_such(self) -> None:
        _output, cause = applicator_failure_details(self.__process(stdout="Rollback of suggestion 3 not successful."))
        assert cause is not None
        self.assertIn("edited by hand", cause)
        self.assertIn("gather_data", cause)

    def test_an_unrecognised_failure_gets_no_invented_cause(self) -> None:
        _output, cause = applicator_failure_details(self.__process(stderr="Traceback (most recent call last):"))
        self.assertIsNone(cause)

    def test_both_streams_are_reported(self) -> None:
        output, _cause = applicator_failure_details(self.__process(stdout="on stdout", stderr="on stderr"))
        self.assertIn("on stdout", output)
        self.assertIn("on stderr", output)


class TestManagePatches(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = os.path.join(self._tmp_dir.name, "project")
        dot_dp = os.path.join(self.project_path, ".discopop")
        os.makedirs(os.path.join(dot_dp, "patch_generator", "1"))
        with open(os.path.join(dot_dp, "FileMapping.txt"), "w") as f:
            f.write("1\t/tmp/main.cpp\n")
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __handle(self, applicator_result: Any, **overrides: Any) -> Any:
        arguments: dict[str, Any] = {"project_path": self.project_path, "action": "clear"}
        arguments.update(overrides)
        with mock.patch.object(manage_patches, "run_patch_applicator", return_value=applicator_result):
            result = manage_patches.handle(arguments, self.ctx)
        return json.loads(result[0].text)

    def test_a_failure_carries_the_applicator_output_and_the_cause(self) -> None:
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="Rollback of suggestion 3 not successful.", stderr=""
        )
        data = self.__handle((proc, None))
        self.assertEqual(data["status"], "error")
        self.assertIn("Rollback of suggestion 3 not successful.", data["output"])
        self.assertIn("edited by hand", data["message"])

    def test_a_successful_clear_reports_success(self) -> None:
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        data = self.__handle((proc, None))
        self.assertEqual(data["status"], "success")

    def test_an_applicator_that_cannot_be_run_is_an_error(self) -> None:
        data = self.__handle((None, "discopop_patch_applicator not found on PATH."))
        self.assertEqual(data["status"], "error")
        self.assertIn("not found on PATH", data["message"])


if __name__ == "__main__":
    unittest.main()
