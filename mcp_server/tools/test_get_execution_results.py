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

from mcp_server.tools import get_execution_results
from mcp_server.tools.get_execution_results import OUTPUT_TAIL_CHARS
from mcp_server.tools.helpers import ToolContext


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "applied_suggestions": [],
        "requested_suggestions": [],
        "failed_suggestions": [],
        "suggestion_application_failed": False,
        "label": "",
        "code": 0,
        "stdout": "all fine\n",
        "stderr": "",
        "timeout_expired": False,
        "time": 1.5,
        "wall_clock_time": 1.5,
        "time_source": "wall_clock",
        "thread_count": 1,
        "executed": True,
        "repetitions": 1,
    }
    entry.update(overrides)
    return entry


class TestGetExecutionResults(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)
        self.long_output = "x" * (OUTPUT_TAIL_CHARS + 500) + "\nerror: expected ';'\n"
        self.__record(
            {
                "small": {
                    "compile.sh": {
                        "par_settings.json": [
                            _entry(code=1, applied_suggestions=[3], stderr=self.long_output),
                        ]
                    },
                    "execute.sh": {
                        "seq_settings.json": [_entry(time=9.5, wall_clock_time=9.9, time_source="console")],
                        "par_settings.json": [
                            _entry(applied_suggestions=[1, 2], thread_count=4, time=3.1, wall_clock_time=3.1),
                            _entry(
                                code=-1,
                                executed=False,
                                requested_suggestions=[5],
                                failed_suggestions=[5],
                                suggestion_application_failed=True,
                            ),
                        ],
                    },
                },
                "large": {"execute.sh": {"seq_settings.json": [_entry(timeout_expired=True, code=124)]}},
            }
        )

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __record(self, results: dict[str, Any]) -> None:
        path = os.path.join(self.project_path, ".discopop", "project")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "execution_results.json"), "w") as f:
            json.dump(results, f)

    def __handle(self, **arguments: Any) -> Any:
        return json.loads(
            get_execution_results.handle({"project_path": self.project_path, **arguments}, self.ctx)[0].text
        )

    def test_the_default_leaves_out_program_output(self) -> None:
        # The output is what made a single call cost tens of thousands of tokens.
        data = self.__handle()
        text = json.dumps(data)
        self.assertNotIn("stdout", text)
        self.assertNotIn("stderr", text)
        self.assertEqual(data["num_runs"], 5)
        self.assertEqual(data["num_failed"], 3)

    def test_an_entry_omits_what_carries_no_information(self) -> None:
        run = self.__handle()["execution_results"]["small"]["execute.sh"]["par_settings.json"][0]
        self.assertEqual(
            run, {"code": 0, "time": 3.1, "time_source": "wall_clock", "thread_count": 4, "applied_suggestions": [1, 2]}
        )

    def test_a_console_time_comes_with_its_wall_clock_time(self) -> None:
        run = self.__handle()["execution_results"]["small"]["execute.sh"]["seq_settings.json"][0]
        self.assertEqual(run["time_source"], "console")
        self.assertEqual(run["wall_clock_time"], 9.9)

    def test_what_makes_a_run_fail_is_kept(self) -> None:
        results = self.__handle()["execution_results"]
        not_applied = results["small"]["execute.sh"]["par_settings.json"][1]
        self.assertEqual(not_applied["code"], -1)
        self.assertEqual(not_applied["failed_suggestions"], [5])
        self.assertTrue(results["large"]["execute.sh"]["seq_settings.json"][0]["timeout_expired"])

    def test_failed_only_keeps_failed_builds_runs_and_unapplied_suggestions(self) -> None:
        results = self.__handle(failed_only=True)["execution_results"]
        self.assertEqual(len(results["small"]["compile.sh"]["par_settings.json"]), 1)
        self.assertEqual(len(results["small"]["execute.sh"]["par_settings.json"]), 1)
        self.assertNotIn("seq_settings.json", results["small"]["execute.sh"])
        self.assertIn("large", results)

    def test_output_is_cut_to_its_end(self) -> None:
        build = self.__handle(include_output=True)["execution_results"]["small"]["compile.sh"]["par_settings.json"][0]
        self.assertEqual(len(build["stderr"]), OUTPUT_TAIL_CHARS)
        self.assertTrue(build["stderr"].endswith("error: expected ';'\n"))
        self.assertEqual(build["stderr_length"], len(self.long_output))
        self.assertEqual(build["stdout"], "all fine\n")
        self.assertNotIn("stdout_length", build)

    def test_filters_select_configuration_and_script(self) -> None:
        data = self.__handle(config_name="small", script="execute.sh")
        self.assertEqual(list(data["execution_results"]), ["small"])
        self.assertEqual(list(data["execution_results"]["small"]), ["execute.sh"])
        self.assertEqual(data["num_runs"], 3)

    def test_failures_point_at_the_call_that_shows_why(self) -> None:
        self.assertIn("include_output=true", self.__handle()["next_step"])
        self.assertNotIn("next_step", self.__handle(failed_only=True, include_output=True))

    def test_no_recorded_runs_name_the_tools_that_record_them(self) -> None:
        os.remove(os.path.join(self.project_path, ".discopop", "project", "execution_results.json"))
        data = self.__handle()
        self.assertEqual(data["execution_results"], {})
        self.assertIn("gather_data", data["next_step"])


if __name__ == "__main__":
    unittest.main()
