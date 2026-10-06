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
from typing import Any, Callable, Optional
from unittest import mock

from mcp_server.tools import run_auto_tuning
from mcp_server.tools.helpers import ToolContext


class _FakeProcess:
    """A stand-in for the autotuner subprocess.

    ``timeout_on_wait`` makes the first ``wait()`` raise, which is how the handler
    learns that the search ran out of time.
    """

    def __init__(self, returncode: int = 0, output: str = "", timeout_on_wait: bool = False) -> None:
        self.returncode: Optional[int] = None
        self._final_returncode = returncode
        self.stdout = output.splitlines(keepends=True)
        self.pid = os.getpid()
        self._timeout_on_wait = timeout_on_wait
        self.terminated = False

    def wait(self, timeout: Optional[float] = None) -> int:
        if self._timeout_on_wait:
            self._timeout_on_wait = False
            raise subprocess.TimeoutExpired(cmd="autotuner", timeout=timeout or 0)
        self.returncode = self._final_returncode
        return self._final_returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def poll(self) -> Optional[int]:
        return self.returncode

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9


class TestBestFromMeasurements(unittest.TestCase):
    def __measurement(self, index: int, suggestions: list[int], runtime: float, **overrides: Any) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event": "measurement",
            "index": index,
            "suggestions": suggestions,
            "runtime": runtime,
            "return_code": 0,
            "valid": True,
            "tsan": True,
            "application_failed": False,
        }
        event.update(overrides)
        return event

    def test_fastest_valid_measurement_wins(self) -> None:
        events = [
            {"event": "baseline", "runtime": 10.0, "valid": True},
            self.__measurement(1, [1], 8.0),
            self.__measurement(2, [1, 2], 4.0),
            self.__measurement(3, [3], 6.0),
        ]
        best, baseline = run_auto_tuning.best_from_measurements(events)
        assert best is not None
        self.assertEqual(best["suggestions"], [1, 2])
        self.assertEqual(baseline, 10.0)

    def test_unusable_measurements_are_ignored_even_when_faster(self) -> None:
        events = [
            {"event": "baseline", "runtime": 10.0, "valid": True},
            # never executed: the patches did not reach the code
            self.__measurement(1, [1], 0.0, application_failed=True, failed_suggestions=[1]),
            # ran, but the result did not validate
            self.__measurement(2, [2], 1.0, valid=False),
            # crashed
            self.__measurement(3, [3], 1.5, return_code=1),
            # data race reported
            self.__measurement(4, [4], 2.0, tsan=False),
            self.__measurement(5, [5], 7.0),
        ]
        best, _ = run_auto_tuning.best_from_measurements(events)
        assert best is not None
        self.assertEqual(best["suggestions"], [5])

    def test_no_usable_measurement_returns_none(self) -> None:
        events = [
            {"event": "baseline", "runtime": 10.0, "valid": True},
            self.__measurement(1, [1], 4.0, valid=False),
        ]
        best, baseline = run_auto_tuning.best_from_measurements(events)
        self.assertIsNone(best)
        self.assertEqual(baseline, 10.0)


class TestRunAutoTuning(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = os.path.join(self._tmp_dir.name, "project")
        self.dot_dp = os.path.join(self.project_path, ".discopop")
        self.configs_dir = os.path.join(self.dot_dp, "project", "configs")
        self.ctx = ToolContext(debug=False)
        self._pending_progress: Optional[list[dict[str, Any]]] = None
        self._popen_cmd: list[str] = []
        self._applicator_calls: list[list[str]] = []
        self.__create_complete_project()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __create_complete_project(self) -> None:
        """Everything AutotunerArguments.__validate() requires, plus hotspot results."""
        for directory in ["profiler", "explorer", "patch_generator", os.path.join(self.configs_dir, "tiny")]:
            os.makedirs(os.path.join(self.dot_dp, directory), exist_ok=True)
        for file_path, content in [
            (os.path.join(self.dot_dp, "FileMapping.txt"), "1\t/tmp/main.cpp\n"),
            (os.path.join(self.dot_dp, "line_mapping.json"), "{}"),
            (os.path.join(self.configs_dir, "seq_settings.json"), "{}"),
            (os.path.join(self.configs_dir, "compile.sh"), "#!/bin/bash\nexit 0\n"),
            (os.path.join(self.configs_dir, "tiny", "execute.sh"), "#!/bin/bash\nexit 0\n"),
        ]:
            with open(file_path, "w") as f:
                f.write(content)
        self.__write_hotspots()

    def __write_hotspots(self, node_type: str = "LOOP") -> None:
        hotspot_dir = os.path.join(self.dot_dp, "hotspot_detection")
        os.makedirs(hotspot_dir, exist_ok=True)
        with open(os.path.join(hotspot_dir, "Hotspots.json"), "w") as f:
            json.dump(
                {
                    "code_regions": [
                        {
                            "csid": 1,
                            "typ": node_type,
                            "fid": 1,
                            "lineNum": 10,
                            "name": "main",
                            "hotness": "YES",
                            "runtimes": [1.0, 2.0],
                            "avr": 1.5,
                            "minVal": 1.0,
                            "maxVal": 2.0,
                            "ratio": 0.66,
                            "topAvr": True,
                            "topRatio": True,
                        }
                    ]
                },
                f,
            )

    def __write_progress(self, events: list[dict[str, Any]]) -> None:
        """Queue the progress stream the fake tuner writes once it is started.

        The handler ignores a progress file it did not see change, so the events have
        to be written after it was launched — exactly as the real tuner does.
        """
        self._pending_progress = events

    def __write_progress_now(self, events: list[dict[str, Any]]) -> None:
        auto_tuner_dir = os.path.join(self.dot_dp, "auto_tuner")
        os.makedirs(auto_tuner_dir, exist_ok=True)
        with open(os.path.join(auto_tuner_dir, "progress.jsonl"), "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def __handle(self, **overrides: Any) -> Any:
        arguments: dict[str, Any] = {"project_path": self.project_path, "config_name": "tiny"}
        arguments.update(overrides)
        result = run_auto_tuning.handle(arguments, self.ctx)
        return json.loads(result[0].text)

    def __applicator(self, returncode: int = 0, output: str = "") -> Any:
        """A stand-in for discopop_patch_applicator that records how it was called."""

        def run(project_path: str, applicator_args: list[str], *_args: Any, **_kwargs: Any) -> Any:
            self._applicator_calls.append(list(applicator_args))
            return (
                subprocess.CompletedProcess(args=applicator_args, returncode=returncode, stdout=output, stderr=""),
                None,
            )

        return run

    def __run_with_fake_tuner(
        self,
        process: _FakeProcess,
        applied: Optional[list[str]] = None,
        applicator: Any = None,
        application_result: Optional[dict[str, Any]] = None,
        on_start: Optional[Callable[[], None]] = None,
        **overrides: Any,
    ) -> Any:
        def start(*args: Any, **_kwargs: Any) -> _FakeProcess:
            self._popen_cmd = list(args[0]) if args else []
            if self._pending_progress is not None:
                self.__write_progress_now(self._pending_progress)
            if on_start is not None:
                on_start()
            return process

        with (
            mock.patch.object(run_auto_tuning, "read_applied_suggestions", return_value=(applied or [], None)),
            mock.patch.object(run_auto_tuning, "run_patch_applicator", applicator or self.__applicator()),
            mock.patch.object(run_auto_tuning, "read_application_result", return_value=application_result),
            mock.patch("subprocess.Popen", side_effect=start),
            mock.patch.object(run_auto_tuning, "_terminate"),
        ):
            return self.__handle(**overrides)

    # -- preconditions ------------------------------------------------------------

    def test_missing_discopop_directory(self) -> None:
        data = run_auto_tuning.handle(
            {"project_path": os.path.join(self._tmp_dir.name, "elsewhere"), "config_name": "tiny"}, self.ctx
        )
        parsed = json.loads(data[0].text)
        self.assertEqual(parsed["status"], "error")
        self.assertIn("initialize_discopop_directory", parsed["message"])

    def test_missing_pipeline_artefact_names_the_path(self) -> None:
        os.remove(os.path.join(self.dot_dp, "line_mapping.json"))
        data = self.__handle()
        self.assertEqual(data["status"], "error")
        self.assertIn("line_mapping.json", data["message"])
        self.assertIn("gather_data", data["message"])

    def test_a_configuration_name_outside_the_configuration_directory_is_refused(self) -> None:
        data = self.__run_with_fake_tuner(_FakeProcess(), config_name="../..")
        self.assertEqual(data["status"], "error")
        self.assertIn("Invalid config_name", data["message"])
        self.assertEqual(self._popen_cmd, [])

    def test_unknown_configuration(self) -> None:
        data = self.__handle(config_name="does_not_exist")
        self.assertEqual(data["status"], "error")
        self.assertIn("does_not_exist", data["message"])
        self.assertIn("get_configurations", data["message"])

    def __completed_run_progress(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4},
                {"event": "result", "suggestions": [1], "speedup": 2.0, "runtime": 5.0, "evaluated": 1},
            ]
        )

    # -- algorithm selection --------------------------------------------------------

    def test_hotspot_guided_search_is_chosen_when_hotspots_exist(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["algorithm"], "hotspot_guided")
        self.assertIn("hotspot results are available", data["algorithm_selection"])
        self.assertIn("-A", self._popen_cmd)
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "6")

    def test_greedy_search_is_the_fallback_without_hotspot_results(self) -> None:
        os.remove(os.path.join(self.dot_dp, "hotspot_detection", "Hotspots.json"))
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["algorithm"], "greedy")
        self.assertIn("no hotspot detection results", data["algorithm_selection"])
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "4")

    def test_greedy_search_is_the_fallback_when_no_loop_is_hot(self) -> None:
        # hotspot results that classify only functions leave the hotspot-guided search
        # with nothing to descend into
        self.__write_hotspots(node_type="FUNCTION")
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["algorithm"], "greedy")
        self.assertIn("no hotspot detection results", data["algorithm_selection"])

    def test_explicit_algorithm_6_without_hotspots_is_refused(self) -> None:
        os.remove(os.path.join(self.dot_dp, "hotspot_detection", "Hotspots.json"))
        data = self.__handle(algorithm="hotspot_guided")
        self.assertEqual(data["status"], "error")
        self.assertIn("hotspot", data["message"])
        self.assertIn("hotspot_config_names", data["message"])

    def test_explicit_algorithm_6_without_hot_loops_is_refused(self) -> None:
        self.__write_hotspots(node_type="FUNCTION")
        data = self.__handle(algorithm="hotspot_guided")
        self.assertEqual(data["status"], "error")
        self.assertIn("hot loops", data["message"])

    def test_an_algorithm_number_of_earlier_versions_is_still_accepted(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess(), algorithm=5)
        self.assertEqual(data["algorithm"], "coordinate_descent")
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "5")

    def test_an_unknown_algorithm_lists_the_known_ones(self) -> None:
        for algorithm in (2, "fastest"):
            data = self.__handle(algorithm=algorithm)
            self.assertEqual(data["status"], "error")
            self.assertIn("hotspot_guided", data["message"])

    def test_explicit_algorithm_is_not_replaced(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess(), algorithm="coordinate_descent")
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["algorithm"], "coordinate_descent")
        self.assertNotIn("algorithm_selection", data)
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "5")

    # -- applied patches ------------------------------------------------------------

    def test_applied_patches_are_cleared_for_the_measurement_and_restored_after(self) -> None:
        # The search needs an un-patched project, but a caller who only asked for a
        # measurement must get the project back exactly as it was.
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess(), applied=["3", "7"])
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["cleared_before_tuning"], ["3", "7"])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])
        self.assertIs(data["applied"], False)
        self.assertFalse([warning for warning in data.get("warnings", []) if "could not be put back" in warning])

    def test_clearing_failure_reports_the_applicator_output_and_the_likely_cause(self) -> None:
        # rc=1 with an empty stderr is what the applicator produces when a patch can no
        # longer be reversed; reporting only the return code leaves nothing to act on.
        failing = self.__applicator(returncode=1, output="Rollback of suggestion 3 not successful.")
        data = self.__run_with_fake_tuner(_FakeProcess(), applied=["3"], applicator=failing)
        self.assertEqual(data["status"], "error")
        self.assertIn("could not be removed", data["message"])
        self.assertIn("Rollback of suggestion 3 not successful.", data["message"])
        self.assertIn("edited by hand", data["message"])
        self.assertEqual(self._applicator_calls, [["--clear"]])

    def test_a_search_without_measurements_still_restores_the_cleared_selection(self) -> None:
        data = self.__run_with_fake_tuner(_FakeProcess(returncode=1), applied=["3"])
        self.assertEqual(data["status"], "error")
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])
        self.assertIn("restored", data["message"])

    def test_a_cancelled_search_stops_and_restores_the_cleared_selection(self) -> None:
        self.__completed_run_progress()
        process = _FakeProcess()
        finish = process.wait

        def wait_until_cancelled(timeout: Optional[float] = None) -> int:
            self.ctx.cancel()  # what the server does when the client cancels the call
            return finish(timeout)

        process.wait = wait_until_cancelled  # type: ignore[method-assign]
        # the fake tuner's pid is the test's own, so the processes must not really be stopped
        with self.ctx.cancellable(), mock.patch("mcp_server.tools.helpers.terminate_process_tree"):
            data = self.__run_with_fake_tuner(process, applied=["3"])
        self.assertEqual(data["status"], "error")
        self.assertIn("Cancelled", data["message"])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])

    def test_a_cancel_while_clearing_does_not_start_the_tuner(self) -> None:
        clear = self.__applicator()

        def clear_and_get_cancelled(*args: Any, **kwargs: Any) -> Any:
            if not self._applicator_calls:
                self.ctx.cancel()
            return clear(*args, **kwargs)

        with self.ctx.cancellable():
            data = self.__run_with_fake_tuner(_FakeProcess(), applied=["3"], applicator=clear_and_get_cancelled)
        self.assertEqual(data["status"], "error")
        self.assertIn("Cancelled", data["message"])
        self.assertEqual(self._popen_cmd, [])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])

    # -- applying the selection -------------------------------------------------------

    def test_the_selection_is_not_applied_by_default(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertIs(data["applied"], False)
        self.assertEqual(self._applicator_calls, [])
        self.assertIn("manage_patches", data["message"])

    def test_apply_persists_the_selection(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(
            _FakeProcess(), apply=True, application_result={"applied": ["1"], "failed": [], "unknown": []}
        )
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["applied"], ["1"])
        self.assertEqual(self._applicator_calls, [["--apply", "1"]])
        self.assertIn("rollback", data["message"])

    def test_apply_replaces_a_previously_applied_selection(self) -> None:
        # Cleared for the measurement, then not restored: the tuner's selection is what
        # the caller asked to end up with.
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(
            _FakeProcess(),
            applied=["3", "7"],
            apply=True,
            application_result={"applied": ["1"], "failed": [], "unknown": []},
        )
        self.assertEqual(data["applied"], ["1"])
        self.assertEqual(data["cleared_before_tuning"], ["3", "7"])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--apply", "1"]])

    def test_a_selection_that_does_not_reach_the_code_is_reported(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(
            _FakeProcess(), apply=True, application_result={"applied": [], "failed": ["1"], "unknown": []}
        )
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["not_applied"], ["1"])
        self.assertTrue(any("NOT applied" in warning for warning in data["warnings"]))

    def test_nothing_is_applied_when_the_search_selected_nothing(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 9.5, "valid": True},
                {"event": "result", "suggestions": [], "speedup": 1.0, "runtime": 9.5, "evaluated": 3},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess(), apply=True)
        self.assertEqual(data["suggestion_ids"], [])
        self.assertEqual(self._applicator_calls, [])
        self.assertIn("No combination", data["message"])

    # -- results ------------------------------------------------------------------

    def test_completed_run_reports_the_final_result(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 9.52, "valid": True},
                {"event": "measurement", "index": 1, "suggestions": [7], "runtime": 6.0},
                {
                    "event": "result",
                    "suggestions": [7, 12],
                    "speedup": 2.31,
                    "efficiency": 0.58,
                    "runtime": 4.12,
                    "valid_count": 9,
                    "invalid_count": 2,
                    "failed_count": 1,
                    "not_applied_count": 0,
                    "evaluated": 14,
                    "optimization_time_s": 812.4,
                },
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["suggestion_ids"], ["7", "12"])
        self.assertEqual(data["speedup"], 2.31)
        self.assertEqual(data["baseline_runtime"], 9.52)
        self.assertEqual(data["evaluated_configurations"], 14)
        self.assertEqual(data["valid_count"], 9)
        self.assertIn("manage_patches", data["message"])
        # Rejected candidates are counted; where their reason is recorded is named.
        self.assertIn("get_execution_results", data["diagnosis_hint"])
        self.assertIn("invalid_count=2", data["diagnosis_hint"])
        self.assertIn("failed_count=1", data["diagnosis_hint"])
        self.assertNotIn("not_applied_count", data["diagnosis_hint"])

    def test_empty_selection_is_a_success(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 9.5, "valid": True},
                {"event": "result", "suggestions": [], "speedup": 1.0, "runtime": 9.5, "evaluated": 3},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["suggestion_ids"], [])
        self.assertIn("No combination", data["message"])
        self.assertNotIn("diagnosis_hint", data)

    def test_timeout_returns_the_best_measurement_so_far(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True},
                {
                    "event": "measurement",
                    "index": 1,
                    "suggestions": [1],
                    "runtime": 8.0,
                    "return_code": 0,
                    "valid": True,
                    "tsan": True,
                    "application_failed": False,
                    "speedup": 1.25,
                },
                {
                    "event": "measurement",
                    "index": 2,
                    "suggestions": [1, 5],
                    "runtime": 5.0,
                    "return_code": 0,
                    "valid": True,
                    "tsan": True,
                    "application_failed": False,
                    "speedup": 2.0,
                },
                {
                    "event": "measurement",
                    "index": 3,
                    "suggestions": [9],
                    "runtime": 1.0,
                    "return_code": 0,
                    "valid": False,
                    "tsan": True,
                    "application_failed": False,
                },
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess(timeout_on_wait=True), timeout_seconds=1)
        self.assertEqual(data["status"], "timeout")
        self.assertTrue(data["partial"])
        self.assertEqual(data["suggestion_ids"], ["1", "5"])
        self.assertEqual(data["speedup"], 2.0)
        self.assertEqual(data["baseline_runtime"], 10.0)
        self.assertIn("not completed", data["message"])

    def test_timeout_removes_leftover_project_copies(self) -> None:
        leftover = os.path.join(self._tmp_dir.name, "tiny_par_settings.json_project_3")
        # a hotspot-instrumented candidate, as the refinement of a selection builds one
        hotspot_leftover = os.path.join(self._tmp_dir.name, "tiny_hd_settings.json_project_4")
        unrelated = os.path.join(self._tmp_dir.name, "some_other_directory")
        # a copy of a sibling project whose name starts with this one's, e.g. one being tuned right now
        sibling_copy = os.path.join(self._tmp_dir.name, "tiny_par_settings.json_project_x_3")
        os.makedirs(leftover)
        os.makedirs(hotspot_leftover)
        os.makedirs(unrelated)
        os.makedirs(sibling_copy)
        self.__write_progress([{"event": "baseline", "runtime": 10.0, "valid": True}])

        data = self.__run_with_fake_tuner(_FakeProcess(timeout_on_wait=True), timeout_seconds=1)

        self.assertEqual(data["status"], "timeout")
        self.assertFalse(os.path.exists(leftover))
        self.assertFalse(os.path.exists(hotspot_leftover))
        self.assertTrue(os.path.exists(unrelated))
        self.assertTrue(os.path.exists(sibling_copy))
        self.assertEqual(
            data["removed_project_copies"], ["tiny_hd_settings.json_project_4", "tiny_par_settings.json_project_3"]
        )

    def test_no_measurements_is_an_error_carrying_the_output(self) -> None:
        data = self.__run_with_fake_tuner(_FakeProcess(returncode=1, output="compile.sh: command not found\n"))
        self.assertEqual(data["status"], "error")
        self.assertIn("compile.sh: command not found", data["message"])

    def test_nonzero_exit_with_measurements_is_partial(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True},
                {
                    "event": "measurement",
                    "index": 1,
                    "suggestions": [2],
                    "runtime": 5.0,
                    "return_code": 0,
                    "valid": True,
                    "tsan": True,
                    "application_failed": False,
                },
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess(returncode=1, output="Traceback ...\n"))
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["returncode"], 1)
        self.assertEqual(data["suggestion_ids"], ["2"])

    def test_missing_validate_script_is_reported_as_a_warning(self) -> None:
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4},
                {"event": "result", "suggestions": [1], "speedup": 2.0, "runtime": 5.0, "evaluated": 2},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["thread_count"], 4)
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("validate.sh", data["warnings"][0])

    def test_speedup_above_the_thread_count_is_flagged(self) -> None:
        with open(os.path.join(self.configs_dir, "tiny", "validate.sh"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 31.8, "valid": True, "thread_count": 4},
                {"event": "result", "suggestions": [0], "speedup": 2449.08, "runtime": 0.013, "evaluated": 2},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        # validate.sh exists, so only the implausible speedup is reported
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("exceeds the thread count", data["warnings"][0])

    def test_no_warnings_for_a_validated_plausible_result(self) -> None:
        with open(os.path.join(self.configs_dir, "tiny", "validate.sh"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        self.__write_progress(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4},
                {"event": "result", "suggestions": [1], "speedup": 3.2, "runtime": 3.1, "evaluated": 6},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertNotIn("warnings", data)

    # -- measuring a given selection ------------------------------------------------

    def __create_suggestions(self, *suggestion_ids: str) -> None:
        for suggestion_id in suggestion_ids:
            os.makedirs(os.path.join(self.dot_dp, "patch_generator", suggestion_id), exist_ok=True)

    def __selection_progress(self, suggestions: list[int], **overrides: Any) -> None:
        measurement: dict[str, Any] = {
            "event": "measurement",
            "index": 1,
            "suggestions": suggestions,
            "runtime": 4.0,
            "return_code": 0,
            "valid": True,
            "tsan": True,
            "application_failed": False,
            "failed_suggestions": [],
            "speedup": 2.5,
        }
        measurement.update(overrides)
        if measurement["application_failed"]:
            measurement["speedup"] = None  # nothing was run
        if measurement["application_failed"] or measurement["return_code"] != 0 or not measurement["valid"]:
            # the tuner then falls back to the un-patched reference as its best configuration
            final: dict[str, Any] = {"event": "result", "suggestions": [], "speedup": 1.0, "runtime": 10.0}
        else:
            final = {"event": "result", "suggestions": suggestions, "speedup": 2.4, "runtime": 4.2}
        self.__write_progress(
            [{"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4}, measurement, final]
        )

    def test_a_selection_is_measured_instead_of_searched(self) -> None:
        self.__create_suggestions("3", "5")
        self.__selection_progress([3, 5])
        data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=["3", "5"])
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-s") + 1], "3,5")
        # exactly the named selection: no search, and no refinement of the selection
        self.assertNotIn("-A", self._popen_cmd)
        self.assertIn("--skip-removal-pass", self._popen_cmd)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["mode"], "selection")
        self.assertNotIn("algorithm", data)
        self.assertEqual(data["outcome"], "valid")
        self.assertIs(data["result_valid"], True)
        self.assertEqual(data["suggestion_ids"], ["3", "5"])
        # the selection's own measurement, not the tuner's re-run of its best configuration
        self.assertEqual(data["runtime"], 4.0)
        self.assertEqual(data["speedup"], 2.5)
        self.assertEqual(data["baseline_runtime"], 10.0)
        self.assertEqual(data["efficiency"], 0.625)
        self.assertIs(data["applied"], False)
        self.assertIn("manage_patches", data["message"])

    def test_measuring_a_selection_keeps_the_result_of_the_last_search(self) -> None:
        self.__create_suggestions("3", "5")
        auto_tuner_dir = os.path.join(self.dot_dp, "auto_tuner")
        os.makedirs(auto_tuner_dir, exist_ok=True)
        results_json = os.path.join(auto_tuner_dir, "results.json")
        progress_jsonl = os.path.join(auto_tuner_dir, "progress.jsonl")
        search = {"tiny": {"applied_suggestions": ["1", "2"], "speedup": 3.0}}
        with open(results_json, "w") as f:
            json.dump(search, f)
        self.__write_progress_now([{"event": "result", "suggestions": [1, 2], "speedup": 3.0}])
        os.utime(progress_jsonl, (1000.0, 1000.0))
        with open(progress_jsonl) as f:
            search_progress = f.read()

        def tuner_writes_its_result() -> None:
            with open(results_json, "w") as f:
                json.dump({"tiny": {"applied_suggestions": ["3", "5"], "speedup": 0.5}}, f)
            with open(os.path.join(auto_tuner_dir, "measurements.json"), "w") as f:
                f.write("[]")

        self.__selection_progress([3, 5])
        data = self.__run_with_fake_tuner(_FakeProcess(), on_start=tuner_writes_its_result, suggestion_ids=["3", "5"])

        self.assertEqual(data["outcome"], "valid")
        self.assertEqual(data["runtime"], 4.0)
        with open(results_json) as f:
            self.assertEqual(json.load(f), search)
        with open(progress_jsonl) as f:
            self.assertEqual(f.read(), search_progress)
        self.assertEqual(os.path.getmtime(progress_jsonl), 1000.0)
        self.assertFalse(os.path.exists(os.path.join(auto_tuner_dir, "measurements.json")))

    def test_measuring_a_selection_keeps_the_last_search_also_when_running_the_tuner_raises(self) -> None:
        self.__create_suggestions("3", "5")
        statistics_svg = os.path.join(self.dot_dp, "dp_autotuner_statistics.svg")
        with open(statistics_svg, "w") as f:
            f.write("<svg>search</svg>")

        class _Broken(_FakeProcess):
            def wait(self, timeout: Optional[float] = None) -> int:
                raise RuntimeError("lost the tuner")

        def tuner_writes_its_graph() -> None:
            with open(statistics_svg, "w") as f:
                f.write("<svg>selection</svg>")

        data = self.__run_with_fake_tuner(_Broken(), on_start=tuner_writes_its_graph, suggestion_ids=["3", "5"])
        self.assertEqual(data["status"], "error")
        with open(statistics_svg) as f:
            self.assertEqual(f.read(), "<svg>search</svg>")

    def test_integer_and_duplicate_suggestion_ids_are_accepted(self) -> None:
        self.__create_suggestions("3", "5")
        self.__selection_progress([3, 5])
        data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=[3, "5", "3"])
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-s") + 1], "3,5")
        self.assertEqual(data["suggestion_ids"], ["3", "5"])

    def test_suggestion_ids_are_coerced_from_strings_and_integers(self) -> None:
        from mcp_server.argument_coercion import coerce_arguments, validation_error

        schema = run_auto_tuning.TOOL.inputSchema
        for sent, expected in (("3,5", ["3", "5"]), ("[3, 5]", [3, 5]), ("7", ["7"])):
            arguments, _ = coerce_arguments({"project_path": "/p", "config_name": "c", "suggestion_ids": sent}, schema)
            self.assertEqual(arguments["suggestion_ids"], expected)
            self.assertIsNone(validation_error("run_auto_tuning", arguments, schema))

    def test_unknown_suggestion_ids_are_rejected_before_anything_runs(self) -> None:
        self.__create_suggestions("3")
        data = self.__run_with_fake_tuner(_FakeProcess(), applied=["3"], suggestion_ids=["3", "42"])
        self.assertEqual(data["status"], "error")
        self.assertIn("42", data["message"])
        self.assertIn("get_parallelization_patches", data["message"])
        self.assertEqual(self._popen_cmd, [])
        self.assertEqual(self._applicator_calls, [])

    def test_malformed_or_empty_suggestion_ids_are_rejected(self) -> None:
        for suggestion_ids in ([], ["3a"], [True]):
            data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=suggestion_ids)
            self.assertEqual(data["status"], "error")
            self.assertIn("suggestion_ids", data["message"])
        self.assertEqual(self._popen_cmd, [])

    def test_suggestion_ids_and_algorithm_cannot_be_combined(self) -> None:
        self.__create_suggestions("3")
        data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=["3"], algorithm="greedy")
        self.assertEqual(data["status"], "error")
        self.assertIn("cannot be combined", data["message"])
        self.assertEqual(self._popen_cmd, [])

    def test_a_valid_selection_is_applied_when_asked(self) -> None:
        self.__create_suggestions("3", "5")
        self.__selection_progress([3, 5])
        data = self.__run_with_fake_tuner(
            _FakeProcess(),
            applied=["7"],
            suggestion_ids=["5", "3"],
            apply=True,
            application_result={"applied": ["5", "3"], "failed": [], "unknown": []},
        )
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["applied"], ["5", "3"])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--apply", "5", "3"]])

    def test_a_valid_but_slower_selection_is_applied_when_asked(self) -> None:
        # apply=true applies the caller's choice; the speedup is reported, not enforced
        self.__create_suggestions("3")
        self.__selection_progress([3], runtime=12.0, speedup=10.0 / 12.0)
        data = self.__run_with_fake_tuner(
            _FakeProcess(),
            suggestion_ids=["3"],
            apply=True,
            application_result={"applied": ["3"], "failed": [], "unknown": []},
        )
        self.assertEqual(data["outcome"], "valid")
        self.assertLess(data["speedup"], 1)
        self.assertEqual(data["applied"], ["3"])
        self.assertEqual(self._applicator_calls, [["--apply", "3"]])
        self.assertIn("not faster", data["message"])

    def test_an_invalid_selection_is_rejected_and_not_applied(self) -> None:
        self.__create_suggestions("3")
        self.__selection_progress([3], valid=False, runtime=0.5)
        data = self.__run_with_fake_tuner(_FakeProcess(), applied=["7"], suggestion_ids=["3"], apply=True)
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["outcome"], "invalid")
        self.assertIs(data["result_valid"], False)
        # a wrong program is fast for the wrong reason
        self.assertIsNone(data["speedup"])
        self.assertIs(data["applied"], False)
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])
        self.assertTrue(any("not applied" in warning for warning in data["warnings"]))
        self.assertIn("get_execution_results", data["diagnosis_hint"])

    def test_a_failing_selection_is_reported(self) -> None:
        self.__create_suggestions("3")
        self.__selection_progress([3], return_code=1, valid=False)
        data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=["3"])
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["outcome"], "failed")
        self.assertIsNone(data["result_valid"])
        self.assertEqual(data["return_code"], 1)

    def test_a_selection_whose_patches_do_not_apply_is_reported(self) -> None:
        self.__create_suggestions("3", "5")
        self.__selection_progress([3, 5], application_failed=True, failed_suggestions=[5], runtime=0.0)
        data = self.__run_with_fake_tuner(_FakeProcess(), suggestion_ids=["3", "5"])
        self.assertEqual(data["outcome"], "not_applied")
        self.assertEqual(data["not_applied"], ["5"])
        self.assertIsNone(data["runtime"])
        self.assertIsNone(data["speedup"])

    def test_a_timeout_before_the_selection_was_measured_is_an_error(self) -> None:
        self.__create_suggestions("3")
        self.__write_progress([{"event": "baseline", "runtime": 10.0, "valid": True}])
        data = self.__run_with_fake_tuner(
            _FakeProcess(timeout_on_wait=True), applied=["7"], suggestion_ids=["3"], timeout_seconds=1
        )
        self.assertEqual(data["status"], "error")
        self.assertIn("not measured", data["message"])
        self.assertEqual(self._applicator_calls, [["--clear"], ["--load"]])

    def test_a_timeout_after_the_selection_was_measured_keeps_the_measurement(self) -> None:
        self.__create_suggestions("3")
        self.__selection_progress([3])
        data = self.__run_with_fake_tuner(_FakeProcess(timeout_on_wait=True), suggestion_ids=["3"], timeout_seconds=1)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["runtime"], 4.0)
        self.assertIn("measurement above is complete", data["message"])

    def test_progress_file_of_an_earlier_run_is_not_reported(self) -> None:
        # a tuner that dies before it starts writing leaves the previous run's file in
        # place; reporting it would present an old selection as this run's result
        self.__write_progress_now(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True},
                {"event": "result", "suggestions": [4], "speedup": 3.0, "runtime": 3.3, "evaluated": 5},
            ]
        )
        data = self.__run_with_fake_tuner(_FakeProcess(returncode=1, output="ModuleNotFoundError\n"))
        self.assertEqual(data["status"], "error")
        self.assertIn("ModuleNotFoundError", data["message"])


if __name__ == "__main__":
    unittest.main()
