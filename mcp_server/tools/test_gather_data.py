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
from typing import Any, Callable, List, Optional, Tuple
from unittest import mock

from mcp_server.tools import gather_data
from mcp_server.tools.helpers import ToolContext

CONFIG_NAME = "default"


class TestGatherDataCompileScriptResolution(unittest.TestCase):
    """The instrumentation steps must honour a per-configuration compile.sh override."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(self.configs_dir, CONFIG_NAME))
        self.ctx = ToolContext(debug=False)

        for filename in ["compile.sh", "hd_settings.json", "dp_settings.json"]:
            self.__write(filename)

        self.script_paths: List[str] = []
        # _instrument_project treats a build that produced no Data.xml as a failure
        data_xml = os.path.join(self.project_path, ".discopop", "profiler", "Data.xml")

        def fake_execute_configuration(**kwargs: Any) -> Tuple[int, float, str, str]:
            self.script_paths.append(kwargs["script_path"])
            os.makedirs(os.path.dirname(data_xml), exist_ok=True)
            with open(data_xml, "w") as f:
                f.write("<Nodes></Nodes>\n")
            return (0, 1.0, "", "")

        patcher = mock.patch.object(gather_data, "execute_configuration", side_effect=fake_execute_configuration)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, *parts: str) -> str:
        path = os.path.join(self.configs_dir, *parts)
        with open(path, "w") as f:
            f.write("{}\n" if path.endswith(".json") else "#!/bin/bash\nexit 0\n")
        return path

    def __steps(self) -> List[Tuple[str, Callable[..., dict[str, Any]]]]:
        return [
            ("hotspot", gather_data._hotspot_instrument),
            ("instrument", gather_data._instrument_project),
        ]

    def __run(self, step: Callable[..., dict[str, Any]], config_name: str = CONFIG_NAME) -> dict[str, Any]:
        self.script_paths.clear()
        return step(self.project_path, config_name, 60, True, self.ctx, None)

    def test_shared_script_is_used_without_an_override(self) -> None:
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.script_paths, [os.path.join(self.configs_dir, "compile.sh")])

    def test_per_config_override_is_used_when_present(self) -> None:
        override = self.__write(CONFIG_NAME, "compile.sh")
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.script_paths, [override])

    def test_missing_configuration_errors_before_compiling(self) -> None:
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step, config_name="does_not_exist")
                self.assertEqual(result["status"], "error")
                self.assertIn("does_not_exist", result["message"])
                self.assertEqual(self.script_paths, [])

    def test_missing_shared_script_errors_when_no_override_exists(self) -> None:
        os.remove(os.path.join(self.configs_dir, "compile.sh"))
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "error")
                self.assertIn("compile.sh not found", result["message"])
                self.assertEqual(self.script_paths, [])

    def test_override_satisfies_the_check_without_a_shared_script(self) -> None:
        os.remove(os.path.join(self.configs_dir, "compile.sh"))
        override = self.__write(CONFIG_NAME, "compile.sh")
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.script_paths, [override])


class TestGatherDataRestoresThePlainBuild(unittest.TestCase):
    """`gather_data` must not leave the project's build directory instrumented.

    The instrumentation steps compile *in place* (`execute_inplace=True`), so a
    compile script that configures a build directory leaves it pinned to
    `discopop_cc`/`discopop_cxx`. Nothing says so, and anyone who then builds and
    runs the program to check their own work measures DiscoPoP's instrumentation
    instead -- one observed harness run lost six minutes to three such
    executions hitting its agent's shell timeout, and then discarded a working
    parallelization because it read the resulting crash as its own bug.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(self.configs_dir, CONFIG_NAME))
        self.ctx = ToolContext(debug=False)

        for filename in ["compile.sh", "dp_settings.json", "hd_settings.json", "par_settings.json"]:
            self.__write(filename)
        self.__write(CONFIG_NAME, "execute.sh")

        profiler_dir = os.path.join(self.project_path, ".discopop", "profiler")
        self.settings_used: List[str] = []
        self.compile_returncode = 0
        self.restore_returncode = 0

        def fake_execute_configuration(**kwargs: Any) -> Tuple[int, float, str, str]:
            settings = os.path.basename(kwargs["settings_path"])
            script = os.path.basename(kwargs["script_path"])
            self.settings_used.append(settings)
            # The instrumented steps produce what the next step checks for.
            os.makedirs(profiler_dir, exist_ok=True)
            for name in ("Data.xml", "dynamic_dependencies.txt"):
                with open(os.path.join(profiler_dir, name), "w") as f:
                    f.write("\n")
            if settings in ("par_settings.json", "seq_settings.json"):
                return (self.restore_returncode, 1.0, "", "")
            if script == "compile.sh":
                return (self.compile_returncode, 1.0, "", "")
            return (0, 1.0, "", "")

        patcher = mock.patch.object(gather_data, "execute_configuration", side_effect=fake_execute_configuration)
        patcher.start()
        self.addCleanup(patcher.stop)

        # The explorer is a subprocess of its own and not what is under test here.
        detection = mock.patch.object(gather_data, "_run_pattern_detection", return_value={"status": "success"})
        detection.start()
        self.addCleanup(detection.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, *parts: str) -> str:
        path = os.path.join(self.configs_dir, *parts)
        with open(path, "w") as f:
            f.write("{}\n" if path.endswith(".json") else "#!/bin/bash\nexit 0\n")
        return path

    def __handle(self, **extra: Any) -> dict[str, Any]:
        self.settings_used.clear()
        arguments = {"project_path": self.project_path, "config_name": CONFIG_NAME, "force": True}
        arguments.update(extra)
        response = gather_data.handle(arguments, self.ctx)
        return json.loads(response[0].text)

    def test_the_last_build_is_a_plain_one(self) -> None:
        result = self.__handle()
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.settings_used[-1], "par_settings.json")
        self.assertEqual(result["steps"]["build_restore"]["status"], "success")

    def test_seq_settings_are_used_when_there_are_no_par_settings(self) -> None:
        os.remove(os.path.join(self.configs_dir, "par_settings.json"))
        self.__write("seq_settings.json")
        result = self.__handle()
        self.assertEqual(self.settings_used[-1], "seq_settings.json")
        self.assertEqual(result["steps"]["build_restore"]["settings"], "seq_settings.json")

    def test_a_failed_instrumentation_still_restores_the_build(self) -> None:
        # The case most in need of it: the compile that broke is the one that
        # left the build directory instrumented.
        self.compile_returncode = 1
        result = self.__handle()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.settings_used[-1], "par_settings.json")

    def test_a_failed_restore_is_reported_but_not_fatal(self) -> None:
        self.restore_returncode = 1
        result = self.__handle()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["steps"]["build_restore"]["status"], "error")
        self.assertIn("instrumented", result["warning"])

    def test_nothing_is_rebuilt_when_every_step_was_skipped(self) -> None:
        # Current results and force=False: no in-place compile happened, so the
        # build is the one the previous call already restored.
        self.__handle()
        result = self.__handle(force=False)
        self.assertEqual(result["steps"]["instrumentation"]["status"], "skipped")
        self.assertNotIn("build_restore", result["steps"])
        self.assertEqual(self.settings_used, [])


if __name__ == "__main__":
    unittest.main()


class TestInstrumentationSkip(unittest.TestCase):
    """Instrumentation is skipped only when profiling has nothing left to do either."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(configs_dir, CONFIG_NAME))
        for filename in ["compile.sh", "dp_settings.json"]:
            with open(os.path.join(configs_dir, filename), "w") as f:
                f.write("{}\n")
        self.profiler_dir = os.path.join(self.project_path, ".discopop", "profiler")
        os.makedirs(self.profiler_dir)
        with open(os.path.join(self.profiler_dir, "Data.xml"), "w") as f:
            f.write("<Nodes></Nodes>\n")
        self.ctx = ToolContext(debug=False)
        self.compiled = 0

        def fake_execute_configuration(**kwargs: Any) -> Tuple[int, float, str, str]:
            self.compiled += 1
            os.makedirs(self.profiler_dir, exist_ok=True)
            with open(os.path.join(self.profiler_dir, "Data.xml"), "w") as f:
                f.write("<Nodes></Nodes>\n")
            return (0, 1.0, "", "")

        patcher = mock.patch.object(gather_data, "execute_configuration", side_effect=fake_execute_configuration)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __instrument(self) -> dict[str, Any]:
        # source_mtime=None: the sources count as unchanged
        result: dict[str, Any] = gather_data._instrument_project(
            self.project_path, CONFIG_NAME, 60, False, self.ctx, None
        )
        return result

    def test_reinstruments_when_profiling_never_produced_its_output(self) -> None:
        """A previous call whose profiling failed restored the plain build before returning."""
        result = self.__instrument()
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.compiled, 1)

    def test_skips_when_profiling_output_is_current(self) -> None:
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt"), "w") as f:
            f.write("\n")
        result = self.__instrument()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(self.compiled, 0)
