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
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import run_configuration
from mcp_server.tools.helpers import ToolContext

Outcome = tuple[int, float, str, str]


class TestRunConfiguration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project = self._tmp_dir.name
        self.configs = Path(self.project) / ".discopop" / "project" / "configs"
        (self.configs / "small").mkdir(parents=True)
        (self.configs / "compile.sh").write_text("#!/bin/bash\n$CXX $CXXFLAGS main.cpp -o prog\n")
        (self.configs / "par_settings.json").write_text("{}")
        (self.configs / "small" / "execute.sh").write_text("#!/bin/bash\n./prog\n")
        self.ctx = ToolContext(debug=False)
        # what each script of a call returns, by its name, and the calls made
        self.outcomes: dict[str, Outcome] = {
            "compile.sh": (0, 1.0, "", ""),
            "execute.sh": (0, 0.35, "result: 42\n", ""),
            "validate.sh": (0, 0.1, "", ""),
            "compile_validate.sh": (0, 1.0, "", ""),
        }
        self.measurement: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []
        patcher = mock.patch.object(run_configuration, "execute_configuration", side_effect=self.__execute)
        patcher.start()
        self.addCleanup(patcher.stop)

    def __execute(self, **kwargs: Any) -> Optional[Outcome]:
        self.calls.append(kwargs)
        if kwargs.get("measurement") is not None:
            kwargs["measurement"].update(self.measurement)
        return self.outcomes[os.path.basename(kwargs["script_path"])]

    def __scripts(self) -> list[str]:
        return [os.path.basename(call["script_path"]) for call in self.calls]

    def __handle(self, **arguments: Any) -> str:
        arguments = {"project_path": self.project, "config_name": "small", **arguments}
        return run_configuration.handle(arguments, self.ctx)[0].text

    def test_a_successful_run_reports_time_the_missing_validation_and_the_output(self) -> None:
        lines = self.__handle(threads=4).splitlines()
        self.assertEqual(lines[0], "Configuration 'small' with 4 threads: built and ran successfully in 0.35 s.")
        self.assertIn("There is no validate.sh, so the output was not checked; only the exit code.", lines)
        self.assertEqual(lines[-2:], ["Output (the end):", "  result: 42"])
        self.assertEqual(self.__scripts(), ["compile.sh", "execute.sh"])

    def test_the_build_uses_one_thread_and_the_run_the_requested_ones(self) -> None:
        self.__handle(threads=8)
        build, run = self.calls
        self.assertEqual((build["thread_count"], run["thread_count"]), (1, 8))
        self.assertEqual(os.path.basename(run["settings_path"]), "par_settings.json")

    def test_the_default_is_one_thread_per_cpu(self) -> None:
        with mock.patch("os.cpu_count", return_value=6):
            self.assertIn("with 6 threads", self.__handle())

    def test_seq_settings_are_the_fallback_without_par_settings(self) -> None:
        (self.configs / "par_settings.json").unlink()
        (self.configs / "seq_settings.json").write_text("{}")
        self.__handle()
        self.assertEqual(os.path.basename(self.calls[0]["settings_path"]), "seq_settings.json")

    def test_without_a_rebuild_the_last_build_is_run_again(self) -> None:
        self.__handle(rebuild=False)
        self.assertEqual(self.__scripts(), ["execute.sh"])

    def test_the_median_of_repetitions_is_reported(self) -> None:
        text = self.__handle(repetitions=3, threads=2)
        self.assertIn("in 0.35 s (median of 3 runs).", text)
        self.assertEqual(self.calls[1]["repetitions"], 3)

    def test_a_time_the_program_reports_itself_is_said_so(self) -> None:
        self.measurement = {"time_source": "console"}
        self.assertIn("in 0.35 s, as the program reports it.", self.__handle())

    def test_build_warnings_are_listed_and_capped(self) -> None:
        warnings = "".join(f"main.cpp:{n}:3: warning: unused variable 'v{n}' [-Wunused]\n" for n in range(1, 8))
        self.outcomes["compile.sh"] = (0, 1.0, "", warnings + "main.cpp:9: note: declared here\n")
        text = self.__handle()
        self.assertIn("Build warnings (7):", text)
        self.assertIn("- main.cpp:1:3: warning: unused variable 'v1' [-Wunused]", text)
        self.assertIn("- 2 more.", text)
        self.assertNotIn("note: declared here", text)

    def test_a_failed_build_names_its_errors_and_does_not_run_the_program(self) -> None:
        self.outcomes["compile.sh"] = (
            2,
            1.0,
            "",
            "main.cpp:5:3: error: use of undeclared identifier 'x'\nmain.cpp:2:1: warning: unused\n",
        )
        text = self.__handle()
        self.assertIn("the build failed (exit code 2); the program was not run.", text)
        self.assertIn("Build errors (1):\n- main.cpp:5:3: error: use of undeclared identifier 'x'", text)
        self.assertIn("Build warnings (1):", text)
        self.assertEqual(self.__scripts(), ["compile.sh"])

    def test_a_failed_build_without_a_diagnostic_shows_the_end_of_its_output(self) -> None:
        self.outcomes["compile.sh"] = (1, 1.0, "", "make: *** No rule to make target 'main.o'.  Stop.\n")
        self.assertIn("End of the build output:\n  make: *** No rule", self.__handle())

    def test_a_failed_run_reports_the_exit_code_and_what_the_program_wrote(self) -> None:
        self.outcomes["execute.sh"] = (
            139,
            0.2,
            "starting\n",
            "main.cpp:7: error: index out of range\nSegmentation fault\n",
        )
        text = self.__handle()
        self.assertIn("the run failed (exit code 139).", text)
        self.assertIn("Errors of the run (1):\n- main.cpp:7: error: index out of range", text)
        self.assertIn(
            "The program wrote to stderr:\n  main.cpp:7: error: index out of range\n  Segmentation fault", text
        )
        self.assertNotIn("validate", text)
        self.assertNotIn("built and ran successfully", text)

    def test_a_timeout_is_not_taken_for_a_failure_of_the_program(self) -> None:
        self.outcomes["execute.sh"] = (-15, 5.0, "", "")
        self.measurement = {"timeout_expired": True}
        text = self.__handle(timeout_seconds=5)
        self.assertIn("the run timed out after 5 s.", text)
        self.assertNotIn("failed", text)

    def test_warnings_of_a_successful_run_are_listed(self) -> None:
        self.outcomes["execute.sh"] = (0, 0.3, "ok\n", "OMP: Warning #96: Cannot form a team with 64 threads.\n")
        text = self.__handle()
        self.assertIn("Warnings of the run (1):\n- OMP: Warning #96: Cannot form a team with 64 threads.", text)
        self.assertNotIn("The program wrote to stderr", text)

    def test_other_output_on_stderr_of_a_successful_run_is_shown(self) -> None:
        self.outcomes["execute.sh"] = (0, 0.3, "ok\n", "progress 50%\n")
        self.assertIn("The program wrote to stderr:\n  progress 50%", self.__handle())

    def test_a_program_that_prints_nothing_says_so(self) -> None:
        self.outcomes["execute.sh"] = (0, 0.3, "", "")
        self.assertIn("The program printed nothing.", self.__handle())

    def test_the_end_of_a_long_output_is_shown(self) -> None:
        self.outcomes["execute.sh"] = (0, 0.3, "".join(f"line {n}\n" for n in range(100)), "")
        text = self.__handle()
        self.assertIn("  line 99", text)
        self.assertNotIn("line 50\n", text)
        self.assertEqual(text.count("\n  line "), run_configuration.MAX_OUTPUT_LINES)

    def test_a_validation_that_passes_or_fails_is_reported(self) -> None:
        (self.configs / "small" / "validate.sh").write_text("#!/bin/bash\ndiff out.txt ref.txt\n")
        self.assertIn("Validation passed.", self.__handle())
        self.outcomes["validate.sh"] = (1, 0.1, "", "out.txt ref.txt differ\n")
        text = self.__handle()
        self.assertIn(
            "Validation failed (exit code 1): the output is not the expected one.\n  out.txt ref.txt differ", text
        )
        self.assertNotIn("no validate.sh", text)

    def test_validation_with_a_build_of_its_own_builds_it_first(self) -> None:
        (self.configs / "small" / "validate.sh").write_text("#!/bin/bash\n./prog_check\n")
        (self.configs / "compile_validate.sh").write_text("#!/bin/bash\n$CXX -DCHECK main.cpp -o prog_check\n")
        self.__handle()
        self.assertEqual(self.__scripts(), ["compile.sh", "execute.sh", "compile_validate.sh", "validate.sh"])

    def test_a_validation_is_not_run_after_a_failed_run(self) -> None:
        (self.configs / "small" / "validate.sh").write_text("#!/bin/bash\ntrue\n")
        self.outcomes["execute.sh"] = (1, 0.1, "", "")
        self.__handle()
        self.assertNotIn("validate.sh", self.__scripts())

    def test_an_unknown_configuration_names_the_existing_ones(self) -> None:
        data = json.loads(self.__handle(config_name="large"))
        self.assertEqual(data["status"], "error")
        self.assertIn("'large' not found", data["message"])
        self.assertIn("small", data["next_step"])

    def test_invalid_arguments_are_errors(self) -> None:
        for arguments, expected in (
            ({"config_name": "../x"}, "config_name"),
            ({"threads": 0}, "threads"),
            ({"repetitions": 0}, "repetitions"),
        ):
            with self.subTest(arguments=arguments):
                data = json.loads(self.__handle(**arguments))
                self.assertEqual(data["status"], "error")
                self.assertIn(expected, data["message"])
        self.assertEqual(self.calls, [])

    def test_the_schema_accepts_what_it_documents(self) -> None:
        schema = run_configuration.TOOL.inputSchema
        arguments, _ = coerce_arguments(
            {"project_path": "/p", "config_name": "small", "threads": "4", "repetitions": "3", "rebuild": "false"},
            schema,
        )
        self.assertEqual((arguments["threads"], arguments["repetitions"], arguments["rebuild"]), (4, 3, False))
        self.assertIsNone(validation_error(run_configuration.TOOL_NAME, arguments, schema))

    def test_the_description_fits_before_the_client_cuts_it_off(self) -> None:
        self.assertLessEqual(len(run_configuration.TOOL.description or ""), 2048)


if __name__ == "__main__":
    unittest.main()
