# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for --compile-only: build every candidate, run none of them.

The mode exists so a caller that only needs the compiler's verdict on a suggestion
(discopop_patch_repair) does not pay a full program run per invocation. The tests
below pin the three properties that makes it safe to rely on: the run script is
never invoked, the build is not bounded by a timeout derived from a runtime that
was never measured, and a successful build is not recorded as a fast run.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes import CodeConfiguration as code_configuration_module
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration


class _RecordedCall:
    """One ``execute_configuration`` invocation, reduced to what the tests assert on."""

    def __init__(self, script_path: str, timeout: Optional[float]) -> None:
        self.script_name = script_path.rsplit("/", 1)[-1]
        self.timeout = timeout


@pytest.fixture
def arguments(tmp_path: Any) -> AutotunerArguments:
    """An ``AutotunerArguments`` that skips its own filesystem validation.

    ``__post_init__`` insists on a fully populated ``.discopop`` directory, which has
    nothing to do with the branch under test. Building the instance without running it
    keeps the test to the one decision it is about.
    """
    # CodeConfiguration builds a ProjectManagerArguments internally, which exits the
    # process when the .discopop directory is missing
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
    return args


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> List[_RecordedCall]:
    """Record every script the configuration would have run, and fake success."""
    recorded: List[_RecordedCall] = []

    def fake_execute_configuration(
        _arguments: Any,
        _project_copy_root_path: str,
        _config_path: str,
        _settings_path: str,
        script_path: str,
        _thread_count: int,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Tuple[int, float, str, str]:
        recorded.append(_RecordedCall(script_path, timeout))
        return (0, 1.0, "", "")

    monkeypatch.setattr(code_configuration_module, "execute_configuration", fake_execute_configuration)
    monkeypatch.setattr(code_configuration_module, "resolve_compile_script_path", lambda *_: "/p/compile.sh")
    # validate.sh is a separate phase and must not be mistaken for the run
    monkeypatch.setattr(
        code_configuration_module,
        "run_validation_phase",
        lambda *a, **k: _NoValidation(),
    )
    return recorded


class _NoValidation:
    applicable = False
    compile_required = False
    compile_successful = True
    validate_result = None

    def verdict(self, current: bool) -> bool:
        return current


def _configuration(tmp_path: Any) -> CodeConfiguration:
    return CodeConfiguration(str(tmp_path), str(tmp_path / ".discopop"), "par_settings.json")


def test_compile_only_runs_the_build_and_nothing_else(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    arguments.compile_only = True
    config = _configuration(tmp_path)

    config.execute(arguments, timeout=30.0, thread_count=2)

    assert [call.script_name for call in calls] == ["compile.sh"]


def test_a_measuring_run_still_executes_the_program(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    # guards the default path against the compile-only branch swallowing it
    config = _configuration(tmp_path)

    config.execute(arguments, timeout=30.0, thread_count=2)

    assert [call.script_name for call in calls] == ["compile.sh", "execute.sh"]


def test_the_build_is_not_bounded_by_a_timeout_meant_for_runs(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    """The autotuner scales its timeout from the reference *runtime*.

    In compile-only mode no run was measured, so that timeout collapses to its 3s
    floor -- which would kill every real build. The build must therefore be unbounded.
    """
    arguments.compile_only = True
    config = _configuration(tmp_path)

    config.execute(arguments, timeout=3.0, thread_count=2)

    assert calls[0].timeout is None


def test_a_successful_build_is_not_recorded_as_a_fast_run(
    arguments: AutotunerArguments, calls: List[_RecordedCall], tmp_path: Any
) -> None:
    arguments.compile_only = True
    config = _configuration(tmp_path)

    config.execute(arguments, timeout=None, thread_count=2)

    result = config.execution_result
    assert result is not None
    assert result.return_code == 0
    # 0.0 here means "no run happened", which is only distinguishable via the flag
    assert result.compiled_only is True
    assert result.runtime == 0.0
    assert "compiled only" in str(result)
    assert "Compiled, not executed." in config.get_statistics_graph_label()


def test_a_failed_build_keeps_its_failure_result(
    arguments: AutotunerArguments, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    arguments.compile_only = True
    monkeypatch.setattr(code_configuration_module, "resolve_compile_script_path", lambda *_: "/p/compile.sh")
    monkeypatch.setattr(
        code_configuration_module,
        "execute_configuration",
        lambda *a, **k: (1, 0.0, "", "error: expected ';'"),
    )
    config = _configuration(tmp_path)

    config.execute(arguments, timeout=None, thread_count=2)

    result = config.execution_result
    assert result is not None
    assert result.return_code == 1
    assert result.result_valid is False
    # not flagged as compiled: the build is exactly what did not happen
    assert result.compiled_only is False
