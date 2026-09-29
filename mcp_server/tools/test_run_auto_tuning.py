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
from typing import Any, Optional
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
        **overrides: Any,
    ) -> Any:
        def start(*args: Any, **_kwargs: Any) -> _FakeProcess:
            self._popen_cmd = list(args[0]) if args else []
            if self._pending_progress is not None:
                self.__write_progress_now(self._pending_progress)
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
        self.assertEqual(data["algorithm"], 6)
        self.assertIn("hotspot results are available", data["algorithm_selection"])
        self.assertIn("-A", self._popen_cmd)
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "6")

    def test_greedy_search_is_the_fallback_without_hotspot_results(self) -> None:
        os.remove(os.path.join(self.dot_dp, "hotspot_detection", "Hotspots.json"))
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["algorithm"], 4)
        self.assertIn("no hotspot detection results", data["algorithm_selection"])
        self.assertEqual(self._popen_cmd[self._popen_cmd.index("-A") + 1], "4")

    def test_greedy_search_is_the_fallback_when_no_loop_is_hot(self) -> None:
        # hotspot results that classify only functions leave the hotspot-guided search
        # with nothing to descend into
        self.__write_hotspots(node_type="FUNCTION")
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess())
        self.assertEqual(data["algorithm"], 4)
        self.assertIn("no hotspot detection results", data["algorithm_selection"])

    def test_explicit_algorithm_6_without_hotspots_is_refused(self) -> None:
        os.remove(os.path.join(self.dot_dp, "hotspot_detection", "Hotspots.json"))
        data = self.__handle(algorithm=6)
        self.assertEqual(data["status"], "error")
        self.assertIn("hotspot", data["message"])
        self.assertIn("hotspot_config_names", data["message"])

    def test_explicit_algorithm_6_without_hot_loops_is_refused(self) -> None:
        self.__write_hotspots(node_type="FUNCTION")
        data = self.__handle(algorithm=6)
        self.assertEqual(data["status"], "error")
        self.assertIn("hot loops", data["message"])

    def test_explicit_algorithm_is_not_replaced(self) -> None:
        self.__completed_run_progress()
        data = self.__run_with_fake_tuner(_FakeProcess(), algorithm=5)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["algorithm"], 5)
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
        unrelated = os.path.join(self._tmp_dir.name, "some_other_directory")
        os.makedirs(leftover)
        os.makedirs(unrelated)
        self.__write_progress([{"event": "baseline", "runtime": 10.0, "valid": True}])

        data = self.__run_with_fake_tuner(_FakeProcess(timeout_on_wait=True), timeout_seconds=1)

        self.assertEqual(data["status"], "timeout")
        self.assertFalse(os.path.exists(leftover))
        self.assertTrue(os.path.exists(unrelated))
        self.assertEqual(data["removed_project_copies"], ["tiny_par_settings.json_project_3"])

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
