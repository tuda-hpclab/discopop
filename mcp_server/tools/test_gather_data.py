# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Any, Callable, Iterator, List, Optional, Tuple
from unittest import mock

from discopop_library.ProjectManager.configurations.building import BuildLockAborted, BuildOutcome, BuildResult
from discopop_library.ProjectManager.configurations.builds import BuildKey, BuildPolicy, BuildRecord, build_tree_path_of
from discopop_library.ProjectManager.configurations.runs import ActivationError, RunRecord
from mcp_server.tools import gather_data
from mcp_server.tools.helpers import OUTPUT_TAIL_CHARS, ToolContext

CONFIG_NAME = "default"


@contextlib.contextmanager
def hotspot_steps_succeed() -> Iterator[None]:
    """The hotspot steps always run, but most tests are about what comes after them."""
    ok = {"status": "success"}
    with (
        mock.patch.object(gather_data, "_hotspot_instrument", return_value=ok),
        mock.patch.object(gather_data, "_hotspot_profiling_single", return_value=ok),
        mock.patch.object(gather_data, "_hotspot_analysis", return_value=ok),
    ):
        yield


class FakeBuilds:
    """Stands in for the builds and runs of the project manager (which have tests of their own).

    Records what is compiled, run and put into the project, and leaves what the real ones leave: the static data of
    a dp build, the results of a run and, once activated, the data in the project's ``.discopop``.
    """

    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self.compiles: List[str] = []
        self.compile_modes: List[str] = []
        self.policies: List[BuildPolicy] = []
        self.runs: List[Tuple[str, str]] = []
        self.activated: List[List[str]] = []
        self.reused = False
        self.compile_result: Tuple[int, float, str, str] = (0, 1.0, "", "")
        self.write_data_xml = True
        self.failing_runs: set[str] = set()
        self.run_stderr = ""

    @contextlib.contextmanager
    def patched(self) -> Iterator["FakeBuilds"]:
        with (
            mock.patch.object(gather_data, "ensure_build", side_effect=self.ensure_build),
            mock.patch.object(gather_data, "execute_in_build", side_effect=self.execute_in_build),
            mock.patch.object(gather_data, "activate_run", side_effect=self.activate_run),
            mock.patch.object(gather_data, "activate_runs", side_effect=self.activate_runs),
        ):
            yield self

    def ensure_build(
        self,
        arguments: Any,
        key: BuildKey,
        config_path: str,
        settings_path: str,
        compile_script: str,
        thread_count: int,
        policy: BuildPolicy,
        timeout: Optional[float] = None,
        **_kwargs: Any,
    ) -> BuildOutcome:
        self.compiles.append(compile_script)
        self.compile_modes.append(key.mode)
        self.policies.append(policy)
        tree = build_tree_path_of(self.project_path, key)
        if self.reused:
            outcome = BuildResult.REUSED
        elif self.compile_result[0] != 0:
            return BuildOutcome(BuildResult.COMPILE_FAILED, key, compile_result=self.compile_result)
        else:
            outcome = BuildResult.BUILT
        if key.mode == "dp" and self.write_data_xml:
            os.makedirs(os.path.join(tree, ".discopop", "profiler"), exist_ok=True)
            with open(os.path.join(tree, ".discopop", "profiler", "Data.xml"), "w") as f:
                f.write("<Nodes></Nodes>\n")
        record = BuildRecord(key.build_id, key.configuration, key.mode, [], "", tree, 0.0, 0.0, compile_script)
        return BuildOutcome(
            outcome, key, tree=tree, record=record, compile_result=None if self.reused else self.compile_result
        )

    def execute_in_build(
        self,
        arguments: Any,
        build: BuildRecord,
        config_path: str,
        settings_path: str,
        thread_count: int,
        timeout: Optional[float],
        regex: Optional[str],
        repetitions: int,
        **_kwargs: Any,
    ) -> Tuple[Tuple[int, float, str, str], RunRecord]:
        config = os.path.basename(config_path)
        self.runs.append((build.mode, config))
        run_id = f"run{len(self.runs)}"
        dot = os.path.join(self.project_path, ".fake_runs", run_id)
        returncode = -15 if config in self.failing_runs else 0
        if build.mode == "dp":
            os.makedirs(os.path.join(dot, "profiler"), exist_ok=True)
            with open(os.path.join(dot, "profiler", "dynamic_dependencies.txt"), "w") as f:
                f.write(config)
        else:
            os.makedirs(os.path.join(dot, "hotspot_detection", "private"), exist_ok=True)
            with open(os.path.join(dot, "hotspot_detection", "private", "hotspot_result_0.txt"), "w") as f:
                f.write(config)
        run = RunRecord(
            run_id, build.build_id, build.configuration, build.mode, 1, "", 0.0, dot, return_code=returncode
        )
        return (returncode, 1.0, "", self.run_stderr), run

    def activate_run(self, arguments: Any, run: RunRecord) -> List[str]:
        self.activated.append([run.run_id])
        target = os.path.join(self.project_path, ".discopop", "profiler")
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(run.dot_discopop, "profiler"), target)
        return ["profiler"]

    def activate_runs(self, arguments: Any, runs: List[RunRecord]) -> List[str]:
        self.activated.append([run.run_id for run in runs])
        target = os.path.join(self.project_path, ".discopop", "hotspot_detection")
        shutil.rmtree(target, ignore_errors=True)
        os.makedirs(os.path.join(target, "private"))
        for position, run in enumerate(runs):
            shutil.copy(
                os.path.join(run.dot_discopop, "hotspot_detection", "private", "hotspot_result_0.txt"),
                os.path.join(target, "private", f"hotspot_result_{position}.txt"),
            )
        return ["hotspot_detection"]


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

        # _instrument_project treats a build that produced no Data.xml as a failure
        self.builds = FakeBuilds(self.project_path)
        patcher = self.builds.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)

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
        self.builds.compiles.clear()
        return step(self.project_path, config_name, 60, True, self.ctx, None)

    def test_shared_script_is_used_without_an_override(self) -> None:
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.builds.compiles, [os.path.join(self.configs_dir, "compile.sh")])

    def test_per_config_override_is_used_when_present(self) -> None:
        override = self.__write(CONFIG_NAME, "compile.sh")
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.builds.compiles, [override])

    def test_missing_configuration_errors_before_compiling(self) -> None:
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step, config_name="does_not_exist")
                self.assertEqual(result["status"], "error")
                self.assertIn("does_not_exist", result["message"])
                self.assertEqual(self.builds.compiles, [])

    def test_missing_shared_script_errors_when_no_override_exists(self) -> None:
        os.remove(os.path.join(self.configs_dir, "compile.sh"))
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "error")
                self.assertIn("compile.sh not found", result["message"])
                self.assertEqual(self.builds.compiles, [])

    def test_override_satisfies_the_check_without_a_shared_script(self) -> None:
        os.remove(os.path.join(self.configs_dir, "compile.sh"))
        override = self.__write(CONFIG_NAME, "compile.sh")
        for name, step in self.__steps():
            with self.subTest(step=name):
                result = self.__run(step)
                self.assertEqual(result["status"], "success")
                self.assertEqual(self.builds.compiles, [override])


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
            hotspot_steps_succeed(),
            mock.patch.object(gather_data, "_instrument_project", return_value=step_results.get("instr", success)),
            mock.patch.object(gather_data, "_run_profiling", return_value=step_results.get("prof", success)),
            mock.patch.object(
                gather_data, "_run_pattern_detection", return_value=step_results.get("detection", success)
            ),
            mock.patch.object(gather_data, "_progress"),
        ):
            return gather_data._pipeline(self.project_path, CONFIG_NAME, [CONFIG_NAME], 60, False, self.ctx)

    def test_a_failed_build_points_at_its_output_and_the_compile_script(self) -> None:
        result = self.__pipeline(
            instr={"status": "error", "message": "Instrumentation failed (rc=1).", "returncode": 1}
        )
        self.assertIn("steps.instrumentation.stderr", result["next_step"])
        self.assertIn("set_compile_script", result["next_step"])

    def test_a_failed_run_points_at_its_output_and_the_execute_script(self) -> None:
        result = self.__pipeline(prof={"status": "error", "message": "Profiling failed (rc=139).", "returncode": 139})
        self.assertIn("steps.profiling.stderr", result["next_step"])
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
                hotspot_steps_succeed(),
                mock.patch.object(gather_data, "_instrument_project", return_value={"status": "success"}),
                mock.patch.object(gather_data, "_run_profiling", side_effect=profiling_stopped_by_a_cancel),
                mock.patch.object(gather_data, "_run_pattern_detection") as detection,
                mock.patch.object(gather_data, "_progress"),
            ):
                result = gather_data._pipeline(project_path, CONFIG_NAME, [CONFIG_NAME], 60, False, ctx)
        self.assertIs(result["cancelled"], True)
        self.assertNotIn("next_step", result)
        self.assertEqual(result["steps"]["profiling"]["returncode"], -15)
        detection.assert_not_called()

    def test_a_cancel_while_waiting_for_a_build_is_reported_as_an_error_of_the_step(self) -> None:
        with tempfile.TemporaryDirectory() as project_path:
            configs_dir = os.path.join(project_path, ".discopop", "project", "configs")
            os.makedirs(os.path.join(configs_dir, CONFIG_NAME))
            for name in ["compile.sh", "dp_settings.json"]:
                with open(os.path.join(configs_dir, name), "w") as f:
                    f.write("{}\n")
            ctx = ToolContext(debug=False)
            with mock.patch.object(gather_data, "build_lock", side_effect=BuildLockAborted("b")):
                result = gather_data._instrument_project(project_path, CONFIG_NAME, 60, True, ctx, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("Cancelled", result["message"])


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

    def test_a_profiling_run_that_failed_is_not_put_into_the_project(self) -> None:
        dyn_deps = os.path.join(self.profiler_dir, "dynamic_dependencies.txt")
        builds = FakeBuilds(self.project_path)
        builds.failing_runs = {CONFIG_NAME}
        with builds.patched():
            result = gather_data._run_profiling(self.project_path, CONFIG_NAME, 60, False, self.ctx, None)
        self.assertEqual(result["status"], "error")
        self.assertEqual(builds.activated, [])
        self.assertFalse(os.path.exists(dyn_deps))

    def test_a_successful_profiling_run_is_put_into_the_project(self) -> None:
        dyn_deps = os.path.join(self.profiler_dir, "dynamic_dependencies.txt")
        builds = FakeBuilds(self.project_path)
        with builds.patched():
            result = gather_data._run_profiling(self.project_path, CONFIG_NAME, 60, False, self.ctx, None)
        self.assertEqual(result["status"], "success")
        self.assertEqual(builds.activated, [[result["run_id"]]])
        self.assertTrue(os.path.exists(dyn_deps))

    def test_a_run_that_cannot_be_put_into_the_project_is_an_error(self) -> None:
        builds = FakeBuilds(self.project_path)
        with (
            builds.patched(),
            mock.patch.object(gather_data, "activate_run", side_effect=ActivationError("ids differ")),
        ):
            result = gather_data._run_profiling(self.project_path, CONFIG_NAME, 60, False, self.ctx, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("ids differ", result["message"])
        self.assertIn("force=true", result["message"])

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

    def test_doall_reduction_and_task_detection_are_run_and_results_without_them_are_repeated(self) -> None:
        self.__write(os.path.join(self.profiler_dir, "dynamic_dependencies.txt"))
        patterns_json = os.path.join(self.dot_dp, "explorer", "patterns.json")
        os.makedirs(os.path.dirname(patterns_json), exist_ok=True)
        proc = subprocess.CompletedProcess(args=["discopop_explorer"], returncode=0, stdout="", stderr="")
        for detected, expected_status in (
            (None, "success"),  # results of a version which did not say what was detected
            (["reduction", "doall"], "success"),
            (["reduction", "doall", "task"], "skipped"),
            (["task", "doall", "reduction", "pipeline"], "skipped"),
        ):
            with self.subTest(detected=detected):
                with open(patterns_json, "w") as f:
                    json.dump(
                        {"patterns": {}} if detected is None else {"patterns": {}, "enabled_patterns": detected}, f
                    )
                with (
                    mock.patch("mcp_server.tools.gather_data.shutil.which", return_value="discopop_explorer"),
                    mock.patch.object(self.ctx, "run_process", return_value=proc) as run,
                ):
                    result = gather_data._run_pattern_detection(self.project_path, 60, False, self.ctx, None)
                self.assertEqual(result["status"], expected_status)
                if expected_status == "success":
                    self.assertEqual(
                        run.call_args.args[0], ["discopop_explorer", "--enable-patterns", "task,doall,reduction"]
                    )
                else:
                    run.assert_not_called()


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
        self.builds = FakeBuilds(self.project_path)
        patcher = self.builds.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)

    @property
    def runs(self) -> list[str]:
        return [config for _mode, config in self.builds.runs]

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __collect(self, names: list[str]) -> list[str]:
        """instrumentation plus profiling of `names`, as gather_data runs them; the statuses"""
        state = gather_data._PipelineState(build_config=names[0])
        statuses = [
            gather_data._hotspot_instrument(self.project_path, names[0], names, 60, False, self.ctx, None, state)[
                "status"
            ]
        ]
        for name in names:
            statuses.append(
                gather_data._hotspot_profiling_single(self.project_path, name, 60, False, self.ctx, None, state)[
                    "status"
                ]
            )
        if all(status != "error" for status in statuses):
            gather_data._hotspot_activate(self.project_path, 60, self.ctx, state)
        return statuses

    def test_a_complete_set_is_not_collected_again(self) -> None:
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.__collect(["small", "large"]), ["skipped", "skipped", "skipped"])
        self.assertEqual(self.runs, ["small", "large"])

    def test_a_configuration_that_failed_has_every_configuration_profiled_again(self) -> None:
        self.builds.failing_runs = {"large"}
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "error"])
        self.assertEqual(self.builds.activated, [])
        self.builds.failing_runs = set()
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.runs, ["small", "large", "small", "large"])
        # only this call's results are left: one per configuration
        self.assertEqual(sorted(os.listdir(self.private_dir)), ["hotspot_result_0.txt", "hotspot_result_1.txt"])
        self.assertEqual(self.builds.activated, [["run3", "run4"]])

    def test_a_configuration_added_later_is_profiled(self) -> None:
        self.__collect(["small"])
        self.assertEqual(self.__collect(["small", "large"]), ["success", "success", "success"])
        self.assertEqual(self.runs, ["small", "small", "large"])


class TestHotspotDetectionAlwaysRuns(unittest.TestCase):
    """The suggestions are ranked by the hotspots, so the hotspot steps are not optional."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)

    def _requested_hotspot_configs(self, **extra: Any) -> List[str]:
        arguments = {"project_path": self.project_path, "config_name": CONFIG_NAME, **extra}
        with mock.patch.object(gather_data, "_pipeline", return_value={"status": "success", "steps": {}}) as pipeline:
            gather_data.handle(arguments, self.ctx)
        requested: List[str] = pipeline.call_args.args[2]
        return requested

    def test_the_main_configuration_is_profiled_when_none_is_named(self) -> None:
        self.assertEqual(self._requested_hotspot_configs(), [CONFIG_NAME])

    def test_an_empty_list_is_taken_as_none_named(self) -> None:
        self.assertEqual(self._requested_hotspot_configs(hotspot_config_names=[]), [CONFIG_NAME])

    def test_the_named_configurations_are_profiled(self) -> None:
        self.assertEqual(self._requested_hotspot_configs(hotspot_config_names=["a", "b"]), ["a", "b"])


class TestWarningsOfSuccessfulSteps(unittest.TestCase):
    """What a build or a run warned about reaches the agent although the step succeeded."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = self._tmp_dir.name
        configs = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(configs, CONFIG_NAME))
        for name in ("compile.sh", "dp_settings.json", "hd_settings.json"):
            with open(os.path.join(configs, name), "w") as f:
                f.write("{}\n")
        with open(os.path.join(configs, CONFIG_NAME, "execute.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        self.ctx = ToolContext(debug=False)

    def __instrument(self, stdout: str, stderr: str) -> dict[str, Any]:
        builds = FakeBuilds(self.project_path)
        builds.compile_result = (0, 1.0, stdout, stderr)
        with builds.patched():
            return gather_data._instrument_project(self.project_path, CONFIG_NAME, 60, True, self.ctx, None)

    def test_the_warnings_of_the_instrumentation_build_are_listed(self) -> None:
        result = self.__instrument("", "".join(f"a.cpp:{n}:1: warning: w{n}\n" for n in range(7)))
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["warnings"]), 6)
        self.assertEqual(result["warnings"][0], "a.cpp:0:1: warning: w0")
        self.assertEqual(result["warnings"][-1], "2 more warnings.")

    def test_a_step_without_warnings_says_nothing(self) -> None:
        result = self.__instrument("built\n", "")
        self.assertEqual(result["status"], "success")
        self.assertNotIn("warnings", result)


class TestFailedHotspotDetectionFailsTheCall(unittest.TestCase):
    """Without the hotspots there is nothing to rank the suggestions by, so the pipeline stops."""

    def setUp(self) -> None:
        self.ctx = ToolContext(debug=False)
        self.ok = {"status": "success"}
        self.failed = {"status": "error", "message": "boom", "returncode": 1, "stderr": "oops"}
        self.later_steps = {
            name: mock.patch.object(gather_data, name, return_value=self.ok)
            for name in ("_instrument_project", "_run_profiling", "_run_pattern_detection")
        }
        self.later = {name: patcher.start() for name, patcher in self.later_steps.items()}
        for patcher in self.later_steps.values():
            self.addCleanup(patcher.stop)

    def _run(self, instrument: Any, profiling: Any, analysis: Any) -> dict[str, Any]:
        with (
            mock.patch.object(gather_data, "_hotspot_instrument", return_value=instrument),
            mock.patch.object(gather_data, "_hotspot_profiling_single", return_value=profiling),
            mock.patch.object(gather_data, "_hotspot_analysis", return_value=analysis),
        ):
            return gather_data._pipeline("/p", CONFIG_NAME, [CONFIG_NAME], 60, False, self.ctx)

    def _assert_stopped_at(self, result: dict[str, Any], step: str) -> None:
        self.assertEqual(result["status"], "error")
        self.assertIn(f"steps.{step}", result["message"])
        self.assertIn(f"steps.{step}", result["next_step"])
        self.assertNotIn("instrumentation", result["steps"])
        for later in self.later.values():
            later.assert_not_called()

    def test_a_failed_hotspot_instrumentation_stops_the_pipeline(self) -> None:
        result = self._run(self.failed, self.ok, self.ok)
        self._assert_stopped_at(result, "hotspot_instrumentation")
        self.assertEqual(result["steps"]["hotspot_profiling"], [])

    def test_a_failed_hotspot_run_stops_the_pipeline(self) -> None:
        result = self._run(self.ok, self.failed, self.ok)
        self._assert_stopped_at(result, "hotspot_profiling")
        self.assertEqual(result["steps"]["hotspot_analysis"]["reason"], "hotspot_profiling_failed")

    def test_a_failed_hotspot_analysis_stops_the_pipeline(self) -> None:
        self._assert_stopped_at(self._run(self.ok, self.ok, self.failed), "hotspot_analysis")

    def test_successful_hotspot_detection_goes_on_to_the_pipeline(self) -> None:
        result = self._run(self.ok, self.ok, self.ok)
        self.assertNotIn("status", result)
        self.assertEqual(result["steps"]["instrumentation"], self.ok)


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
        self.long_stderr = "warning: unused variable\n" * (OUTPUT_TAIL_CHARS // 10) + "error: expected ';'\n"
        self.builds = FakeBuilds(self.project_path)
        patcher = self.builds.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __instrument(self, stderr: str) -> dict[str, Any]:
        self.builds.compile_result = (1, 1.0, "", stderr)
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


class TestGatherDataLeavesTheProjectAlone(unittest.TestCase):
    """`gather_data` compiles in builds next to the project, so the project's build directory stays plain.

    It used to compile in place, which left a build directory pinned to `discopop_cc` / `discopop_cxx`: whoever then
    built and ran the program by hand measured DiscoPoP's instrumentation (and once discarded a working
    parallelization over the resulting crash). Nothing is compiled in the project any more, so nothing needs to be
    rebuilt afterwards.
    """

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.configs_dir = os.path.join(self.project_path, ".discopop", "project", "configs")
        os.makedirs(os.path.join(self.configs_dir, CONFIG_NAME))
        self.ctx = ToolContext(debug=False)
        for filename in ["compile.sh", "dp_settings.json", "hd_settings.json"]:
            with open(os.path.join(self.configs_dir, filename), "w") as f:
                f.write("{}\n")
        with open(os.path.join(self.configs_dir, CONFIG_NAME, "execute.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        self.builds = FakeBuilds(self.project_path)
        patcher = self.builds.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        # the explorer and the hotspot analysis are subprocesses of their own and not what is under test here
        for step in ("_run_pattern_detection", "_hotspot_analysis"):
            detection = mock.patch.object(gather_data, step, return_value={"status": "success"})
            detection.start()
            self.addCleanup(detection.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __handle(self, **extra: Any) -> dict[str, Any]:
        arguments = {"project_path": self.project_path, "config_name": CONFIG_NAME, "force": True}
        arguments.update(extra)
        result: dict[str, Any] = json.loads(gather_data.handle(arguments, self.ctx)[0].text)
        return result

    def test_every_compilation_happens_in_a_build_and_nothing_is_rebuilt_afterwards(self) -> None:
        result = self.__handle()
        self.assertNotIn("status", result)
        # each mode: the compilation, then the run looks at the build again under its lock
        self.assertEqual(self.builds.compile_modes, ["hd", "hd", "dp", "dp"])
        self.assertNotIn("build_restore", result["steps"])

    def test_the_hotspot_runs_and_the_dp_run_are_put_into_the_project(self) -> None:
        self.__handle()
        self.assertEqual(self.builds.runs, [("hd", CONFIG_NAME), ("dp", CONFIG_NAME)])
        self.assertEqual(self.builds.activated, [["run1"], ["run2"]])

    def test_force_rebuilds_and_the_default_compiles_only_what_is_not_current(self) -> None:
        self.__handle()
        # the compilations (the runs ask for the build as it is)
        self.assertEqual(self.builds.policies[::2], [BuildPolicy.REBUILD, BuildPolicy.REBUILD])
        self.assertEqual(set(self.builds.policies[1::2]), {BuildPolicy.AUTO})
        self.builds.policies.clear()
        self.__handle(force=False)
        self.assertEqual(set(self.builds.policies), {BuildPolicy.AUTO})

    def test_a_failed_instrumentation_is_an_error_of_the_call(self) -> None:
        self.builds.compile_result = (1, 1.0, "", "boom")
        result = self.__handle()
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.builds.runs, [])

    def test_hotspot_runs_of_several_configurations_are_put_into_the_project_together(self) -> None:
        os.makedirs(os.path.join(self.configs_dir, "large"))
        with open(os.path.join(self.configs_dir, "large", "execute.sh"), "w") as f:
            f.write("#!/bin/bash\n")
        result = self.__handle(hotspot_config_names=[CONFIG_NAME, "large"])
        self.assertNotIn("status", result)
        self.assertEqual(self.builds.runs[:2], [("hd", CONFIG_NAME), ("hd", "large")])
        self.assertEqual(self.builds.activated[0], ["run1", "run2"])
        # both are run in the build of the main configuration
        self.assertEqual(set(self.builds.compile_modes[:1]), {"hd"})


class TestStorageWarning(unittest.TestCase):
    """Builds and runs are kept, so the result says how much of them there is once they pile up."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = os.path.join(self._tmp_dir.name, "proj")
        os.makedirs(os.path.join(self.project_path, ".discopop", "project", "builds"))
        self.ctx = ToolContext(debug=False)

    def __build(self, build_id: str, size: int) -> None:
        from discopop_library.ProjectManager.configurations.builds import (
            MANIFEST_VERSION,
            builds_dir_of,
        )

        trees = os.path.join(self._tmp_dir.name, "proj_discopop_builds")
        tree = os.path.join(trees, build_id)
        os.makedirs(tree)
        with open(os.path.join(tree, "prog"), "wb") as f:
            f.write(b"x" * size)
        configuration, mode = build_id.rsplit("_", 1)
        record = {
            "build_id": build_id,
            "configuration": configuration,
            "mode": mode,
            "suggestions": [],
            "fingerprint": "",
            "tree": tree,
            "built_at": 0.0,
            "compile_seconds": 0.0,
            "compile_script": "",
            "version": MANIFEST_VERSION,
            "fingerprint_parts": {},
        }
        with open(
            os.path.join(builds_dir_of(os.path.join(self.project_path, ".discopop", "project")), build_id + ".json"),
            "w",
        ) as f:
            json.dump(record, f)

    def test_no_warning_while_only_the_builds_of_the_call_exist(self) -> None:
        self.__build(f"{CONFIG_NAME}_hd", 10)
        self.__build(f"{CONFIG_NAME}_dp", 10)
        self.assertIsNone(gather_data._storage_warning(self.project_path, CONFIG_NAME, self.ctx))

    def test_further_builds_are_reported_with_their_number_and_storage(self) -> None:
        self.__build(f"{CONFIG_NAME}_hd", 1024)
        self.__build(f"{CONFIG_NAME}_dp", 1024)
        self.__build("other_dp", 2048)
        warning = gather_data._storage_warning(self.project_path, CONFIG_NAME, self.ctx)
        assert warning is not None
        self.assertIn("3 builds and 0 runs", warning)
        self.assertIn("4.0 KiB", warning)
        self.assertIn("--delete-builds", warning)

    def test_the_warning_is_part_of_the_result(self) -> None:
        self.__build(f"{CONFIG_NAME}_dp", 10)
        self.__build("other_dp", 10)
        with mock.patch.object(gather_data, "_pipeline", return_value={"status": "success", "steps": {}}):
            response = gather_data.handle({"project_path": self.project_path, "config_name": CONFIG_NAME}, self.ctx)
        self.assertIn("2 builds", json.loads(response[0].text)["warning"])


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
        self.builds = FakeBuilds(self.project_path)
        patcher = self.builds.patched()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)

    @property
    def compiled(self) -> int:
        return len(self.builds.compiles)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __instrument(self) -> dict[str, Any]:
        # source_mtime=None: the sources count as unchanged
        result: dict[str, Any] = gather_data._instrument_project(
            self.project_path, CONFIG_NAME, 60, False, self.ctx, None
        )
        return result

    def test_reinstruments_when_profiling_never_produced_its_output(self) -> None:
        """A previous call whose profiling failed left no dependencies, so the run needs the build again."""
        result = self.__instrument()
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.compiled, 1)

    def test_skips_when_profiling_output_is_current(self) -> None:
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt"), "w") as f:
            f.write("\n")
        result = self.__instrument()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(self.compiled, 0)
