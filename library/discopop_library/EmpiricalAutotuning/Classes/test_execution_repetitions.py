# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""How often the search measures a candidate, and what it remembers about it.

The auto-tuner's repetition count is deliberately separate from the one used for
the final measurements: the search performs one program execution per candidate,
so repeating every one of them multiplies the tuning time. These tests pin down
that the count reaches the timed run and only the timed run, and that the
individual measurements survive into the result the search logs.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.ProjectManager.configurations.repetitions import DEFAULT_TUNING_REPETITIONS
from discopop_library.EmpiricalAutotuning.Classes import CodeConfiguration as code_configuration_module
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult


class _NoValidation:
    """A validation phase that finds nothing to do; not what these tests are about."""

    applicable = False
    compile_required = False
    compile_successful = True
    validate_result = None

    def verdict(self, current: bool) -> bool:
        return current


class _RecordedCall:
    def __init__(self, script_path: str, repetitions: int) -> None:
        self.script_name = script_path.rsplit("/", 1)[-1]
        self.repetitions = repetitions


@pytest.fixture
def arguments(tmp_path: Any) -> AutotunerArguments:
    """An ``AutotunerArguments`` that skips its own filesystem validation.

    ``__post_init__`` insists on a fully populated ``.discopop`` directory, which
    has nothing to do with the decision under test.
    """
    (tmp_path / ".discopop").mkdir()
    args = AutotunerArguments.__new__(AutotunerArguments)
    args.log_level = "WARNING"
    args.write_log = False
    args.dot_dp_path = str(tmp_path / ".discopop")
    args.project_path = str(tmp_path)
    args.configuration = "tiny"
    args.skip_cleanup = True
    args.sanitize = False
    args.suggestions = None
    args.search_space = None
    args.allow_plots = False
    args.thread_count = 2
    args.hotspot_types = "yes"
    args.algorithm = 0
    args.compile_only = False
    args.execution_time_regex = None
    args.execution_repetitions = 3
    return args


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> List[_RecordedCall]:
    """Record how often each script would have been run, and fake success."""
    recorded: List[_RecordedCall] = []

    # The parameter names mirror the real execute_configuration exactly: the stub is
    # what the dispatch is measured through, so a divergence would let these tests
    # assert on a default the caller never passed. (monkeypatch has no autospec, so
    # keeping them aligned is what stands in for it here.)
    def fake_execute_configuration(
        arguments: Any,
        project_copy_root_path: str,
        config_path: str,
        settings_path: str,
        script_path: str,
        thread_count: int,
        timeout: Optional[float] = None,
        process_started_callback: Any = None,
        execution_time_regex: Optional[str] = None,
        measurement: Optional[Dict[str, Any]] = None,
        repetitions: int = 1,
        should_abort: Any = None,
    ) -> Tuple[int, float, str, str]:
        recorded.append(_RecordedCall(script_path, repetitions))
        if measurement is not None:
            measurement.update(
                {
                    "time": 4.1,
                    "wall_clock_time": 4.1,
                    "repetition_times": [4.1, 4.05, 6.8][:repetitions],
                }
            )
        return (0, 4.1, "", "")

    monkeypatch.setattr(code_configuration_module, "execute_configuration", fake_execute_configuration)
    monkeypatch.setattr(code_configuration_module, "resolve_compile_script_path", lambda *_: "/p/compile.sh")
    monkeypatch.setattr(code_configuration_module, "run_validation_phase", lambda *a, **k: _NoValidation())
    return recorded


def _configuration(tmp_path: Any) -> CodeConfiguration:
    return CodeConfiguration(str(tmp_path), str(tmp_path / ".discopop"), "par_settings.json")


def test_the_timed_run_is_repeated_as_often_as_asked(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    _configuration(tmp_path).execute_only(arguments, None, 2)
    executions = [call for call in calls if call.script_name == "execute.sh"]
    assert len(executions) == 1
    assert executions[0].repetitions == 3


def test_the_build_is_never_repeated(arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any) -> None:
    """compile.sh produces no measurement, so a median of it would mean nothing."""
    _configuration(tmp_path).compile_only(arguments, None, 2)
    builds = [call for call in calls if call.script_name == "compile.sh"]
    assert builds
    assert all(call.repetitions == 1 for call in builds)


def test_the_individual_measurements_reach_the_result(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    """The spread is what says whether the search could resolve a difference at all."""
    configuration = _configuration(tmp_path)
    configuration.execute_only(arguments, None, 2)
    assert configuration.execution_result is not None
    assert configuration.execution_result.repetition_runtimes == [4.1, 4.05, 6.8]
    assert configuration.execution_result.runtime == 4.1


def test_the_search_measures_each_candidate_once_by_default() -> None:
    """Unlike the measured runs: one execution per candidate makes it expensive."""
    assert AutotunerArguments.execution_repetitions == DEFAULT_TUNING_REPETITIONS == 1


def test_a_single_measurement_is_not_repeated(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    arguments.execution_repetitions = 1
    _configuration(tmp_path).execute_only(arguments, None, 2)
    executions = [call for call in calls if call.script_name == "execute.sh"]
    assert executions[0].repetitions == 1


def test_an_unrepeated_result_carries_no_spread() -> None:
    result = ExecutionResult(2.5, 0, True, True)
    assert result.repetition_runtimes == []
    assert "median of" not in str(result)


def test_a_repeated_result_states_what_its_time_rests_on() -> None:
    result = ExecutionResult(4.1, 0, True, True, repetition_runtimes=[4.1, 4.05, 6.8])
    assert "median of 3" in str(result)
    assert "4.05-6.8" in str(result)
