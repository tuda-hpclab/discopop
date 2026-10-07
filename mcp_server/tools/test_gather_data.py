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
from typing import Any, Callable, List, Optional, Tuple
from unittest import mock

from mcp_server.tools import gather_data
from mcp_server.tools.helpers import OUTPUT_TAIL_CHARS, ToolContext

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
            ("hotspot", lambda path, config, *rest: gather_data._hotspot_instrument(path, config, [config], *rest)),
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


class TestGatherDataFailureHints(unittest.TestCase):
    """A failed pipeline names the way out, but only where it has one to name."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __pipeline(self, **step_results: dict[str, Any]) -> dict[str, Any]:
        success = {"status": "success"}
        with (
            mock.patch.object(gather_data, "_instrument_project", return_value=step_results.get("instr", success)),
            mock.patch.object(gather_data, "_run_profiling", return_value=step_results.get("prof", success)),
            mock.patch.object(
                gather_data, "_run_pattern_detection", return_value=step_results.get("detection", success)
            ),
            mock.patch.object(gather_data, "_progress"),
        ):
            return gather_data._pipeline(self.project_path, CONFIG_NAME, [], 60, False, self.ctx)

    def test_a_failed_build_points_at_its_output_and_the_compile_script(self) -> None:
        result = self.__pipeline(
            instr={"status": "error", "message": "Instrumentation failed (rc=1).", "returncode": 1}
        )
        self.assertIn("get_execution_results", result["next_step"])
        self.assertIn("set_compile_script", result["next_step"])

    def test_a_failed_run_points_at_its_output_and_the_execute_script(self) -> None:
        result = self.__pipeline(prof={"status": "error", "message": "Profiling failed (rc=139).", "returncode": 139})
        self.assertIn("get_execution_results", result["next_step"])
        self.assertIn("create_execution_configuration", result["next_step"])

    def test_a_step_refused_before_running_gets_no_invented_cause(self) -> None:
        # Its own message already says what is missing, e.g. the configuration names.
        result = self.__pipeline(instr={"status": "error", "message": "Configuration 'x' not found."})
        self.assertNotIn("next_step", result)

    def test_a_run_that_exited_0_without_output_gets_no_execute_script_hint(self) -> None:
        result = self.__pipeline(
            prof={"status": "error", "message": "dynamic_dependencies.txt missing", "returncode": 0}
        )
        self.assertNotIn("next_step", result)

    def test_a_failed_pattern_detection_points_at_the_reset(self) -> None:
        result = self.__pipeline(detection={"status": "error", "message": "discopop_explorer failed."})
        self.assertIn("reset=true", result["next_step"])


class TestGatherDataCancelledStep(unittest.TestCase):
    """A cancel stops the running step, which fails; the answer is the cancel, not that failure."""

    def test_a_step_stopped_by_a_cancel_is_reported_as_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as project_path:
            ctx = ToolContext(debug=False)

            def profiling_stopped_by_a_cancel(*_args: Any) -> dict[str, Any]:
                ctx.cancel()
                return {"status": "error", "message": "Profiling failed (rc=-15).", "returncode": -15}

            with (
                ctx.cancellable(),
                mock.patch.object(gather_data, "_instrument_project", return_value={"status": "success"}),
                mock.patch.object(gather_data, "_run_profiling", side_effect=profiling_stopped_by_a_cancel),
                mock.patch.object(gather_data, "_run_pattern_detection") as detection,
                mock.patch.object(gather_data, "_progress"),
            ):
                result = gather_data._pipeline(project_path, CONFIG_NAME, [], 60, False, ctx)
        self.assertIs(result["cancelled"], True)
        self.assertNotIn("next_step", result)
        self.assertEqual(result["steps"]["profiling"]["returncode"], -15)
        detection.assert_not_called()

    def test_the_plain_rebuild_is_not_stopped_by_the_cancel_it_cleans_up_after(self) -> None:
        # processes a cancelled call registers are stopped, also those started after the cancel
        with tempfile.TemporaryDirectory() as project_path:
            configs_dir = os.path.join(project_path, ".discopop", "project", "configs")
            os.makedirs(os.path.join(configs_dir, CONFIG_NAME))
            for name in ["compile.sh", "par_settings.json"]:
                with open(os.path.join(configs_dir, name), "w") as f:
                    f.write("{}\n")
            ctx = ToolContext(debug=False)
            with (
                ctx.cancellable(),
                mock.patch.object(gather_data, "execute_configuration", return_value=(0, 1.0, "", "")) as execute,
            ):
                ctx.cancel()
                result = gather_data._restore_plain_build(project_path, CONFIG_NAME, 60, ctx)
        self.assertEqual(result["status"], "success")
        self.assertIsNone(execute.call_args.kwargs["process_started_callback"])


class TestIncompleteStepsAreNotTakenAsCurrent(unittest.TestCase):
    """What a failed, timed-out or cancelled step wrote must not make the next call skip it."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.dot_dp = os.path.join(self.project_path, ".discopop")
        configs_dir = os.path.join(self.dot_dp, "project", "configs")
        os.makedirs(os.path.join(configs_dir, CONFIG_NAME))
        for filename in ["dp_settings.json", os.path.join(CONFIG_NAME, "execute.sh")]:
            with open(os.path.join(configs_dir, filename), "w") as f:
                f.write("{}\n")
        self.profiler_dir = os.path.join(self.dot_dp, "profiler")
        os.makedirs(self.profiler_dir)
        with open(os.path.join(self.profiler_dir, "Data.xml"), "w") as f:
            f.write("\n")
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("partial\n")

    def test_a_profiling_run_that_failed_leaves_no_dependencies_behind(self) -> None:
        dyn_deps = os.path.join(self.profiler_dir, "dynamic_dependencies.txt")

        def killed_after_writing(**_kwargs: Any) -> Tuple[int, float, str, str]:
            self.__write(dyn_deps)
            return (-15, 1.0, "", "")

        with mock.patch.object(gather_data, "execute_configuration", side_effect=killed_after_writing):
            result = gather_data._run_profiling(self.project_path, CONFIG_NAME, 60, False, self.ctx, None)
        self.assertEqual(result["status"], "error")
        self.assertFalse(os.path.exists(dyn_deps))

    def test_a_pattern_detection_that_failed_is_run_again(self) -> None:
        self.__write(os.path.join(self.profiler_dir, "dynamic_dependencies.txt"))
        patterns_json = os.path.join(self.dot_dp, "explorer", "patterns.json")

        def stopped_while_generating_patches(*_args: Any, **_kwargs: Any) -> Any:
            self.__write(patterns_json)
            return subprocess.CompletedProcess(args=["discopop_explorer"], returncode=-15, stdout="", stderr="")

        def timed_out(*_args: Any, **_kwargs: Any) -> Any:
            self.__write(patterns_json)
            raise subprocess.TimeoutExpired("discopop_explorer", 60)

        for stop in (stopped_while_generating_patches, timed_out):
            with self.subTest(stop=stop.__name__):
                with (
                    mock.patch("mcp_server.tools.gather_data.shutil.which", return_value="discopop_explorer"),
                    mock.patch.object(self.ctx, "run_process", side_effect=stop),
                ):
                    result = gather_data._run_pattern_detection(self.project_path, 60, False, self.ctx, None)
                self.assertEqual(result["status"], "error")
                self.assertFalse(os.path.exists(patterns_json))


class TestHotspotResultsCoverTheRequestedConfigurations(unittest.TestCase):
    """Hotspot results are compared across inputs, so they count only as a complete set."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        for name in ("small", "large"):
            os.makedirs(os.path.join(configs_dir, name))
            with open(os.path.join(configs_dir, name, "execute.sh"), "w") as f:
                f.write("./app\n")
        for filename in ["compile.sh", "hd_settings.json"]:
            with open(os.path.join(configs_dir, filename), "w") as f:
                f.write("{}\n")
        self.private_dir = os.path.join(self.project_path, ".discopop", "hotspot_detection", "private")
        self.ctx = ToolContext(debug=False)
        self.failing: set[str] = set()
        self.runs: list[str] = []

        def fake_execute_configuration(**kwargs: Any) -> Tuple[int, float, str, str]:
            script = kwargs["script_path"]
            if script.endswith("compile.sh"):
                return (0, 1.0, "", "")
            config = os.path.basename(kwargs["config_path"])
            self.runs.append(config)
            os.makedirs(self.private_dir, exist_ok=True)
            with open(os.path.join(self.private_dir, f"hotspot_result_{len(self.runs)}.txt"), "w") as f:
                f.write(config)
            return (-15, 1.0, "", "") if config in self.failing else (0, 1.0, "", "")

        patcher = mock.patch.object(gather_data, "execute_configuration", side_effect=fake_execute_configuration)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __collect(self, names: list[str]) -> list[str]:
        """instrumentation plus profiling of `names`, as gather_data runs them; the statuses"""
        statuses = [
            gather_data._hotspot_instrument(self.project_path, names[0], names, 60, False, self.ctx, None)["status"]
        ]
        for name in names:
            statuses.append(
                gather_data._hotspot_profiling_single(self.project_path, name, 60, False, self.ctx, None)["status"]
            )
        return statuses

    def test_a_complete_set_is_not_collected_again(self) -> None:
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.__collect(["small", "large"]), ["skipped", "skipped", "skipped"])
        self.assertEqual(self.runs, ["small", "large"])

    def test_a_configuration_that_failed_has_every_configuration_profiled_again(self) -> None:
        self.failing = {"large"}
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "error"])
        self.failing = set()
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.runs, ["small", "large", "small", "large"])
        # only this call's results are left: one per configuration
        self.assertEqual(sorted(os.listdir(self.private_dir)), ["hotspot_result_3.txt", "hotspot_result_4.txt"])

    def test_a_configuration_added_later_is_profiled(self) -> None:
        self.__collect(["small"])
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.runs, ["small", "small", "large"])


class TestGatherDataStderrTail(unittest.TestCase):
    """A failed step returns the end of its stderr, not a log of hundreds of KB."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(configs_dir, CONFIG_NAME))
        for filename in ["compile.sh", "dp_settings.json"]:
            with open(os.path.join(configs_dir, filename), "w") as f:
                f.write("{}\n")
        self.ctx = ToolContext(debug=False)
        self.stderr = ""
        self.long_stderr = "warning: unused variable\n" * (OUTPUT_TAIL_CHARS // 10) + "error: expected ';'\n"

        def fake_execute_configuration(**kwargs: Any) -> Tuple[int, float, str, str]:
            return (1, 1.0, "", self.stderr)

        patcher = mock.patch.object(gather_data, "execute_configuration", side_effect=fake_execute_configuration)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __instrument(self, stderr: str) -> dict[str, Any]:
        self.stderr = stderr
        result: dict[str, Any] = gather_data._instrument_project(
            self.project_path, CONFIG_NAME, 60, True, self.ctx, None
        )
        return result

    def test_a_long_stderr_is_cut_to_its_tail(self) -> None:
        result = self.__instrument(self.long_stderr)
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["stderr"]), OUTPUT_TAIL_CHARS)
        self.assertTrue(result["stderr"].endswith("error: expected ';'\n"))
        self.assertEqual(result["stderr_length"], len(self.long_stderr))

    def test_a_short_stderr_is_returned_unchanged(self) -> None:
        result = self.__instrument("error: expected ';'\n")
        self.assertEqual(result["stderr"], "error: expected ';'\n")
        self.assertNotIn("stderr_length", result)

    def test_a_failed_pattern_detection_is_cut_as_well(self) -> None:
        profiler_dir = os.path.join(self.project_path, ".discopop", "profiler")
        os.makedirs(profiler_dir)
        for filename in ["Data.xml", "dynamic_dependencies.txt"]:
            with open(os.path.join(profiler_dir, filename), "w") as f:
                f.write("\n")
        proc = subprocess.CompletedProcess(args=["discopop_explorer"], returncode=1, stdout="", stderr=self.long_stderr)
        with (
            mock.patch("mcp_server.tools.gather_data.shutil.which", return_value="discopop_explorer"),
            mock.patch.object(self.ctx, "run_process", return_value=proc),
        ):
            result = gather_data._run_pattern_detection(self.project_path, 60, True, self.ctx, None)
        self.assertEqual(len(result["stderr"]), OUTPUT_TAIL_CHARS)
        self.assertEqual(result["stderr_length"], len(self.long_stderr))


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
        result: dict[str, Any] = json.loads(response[0].text)
        return result

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
