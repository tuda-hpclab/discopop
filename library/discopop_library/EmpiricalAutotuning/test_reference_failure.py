# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The autotuner stops when its reference configuration (no suggestions applied) fails.

Every candidate is measured against the reference. A reference that did not build used to leave a placeholder
runtime of 0.1 s as the baseline and a 3 s timeout derived from it, and the search went on to report every candidate
as failed without saying why.
"""

import os
from typing import Any, List
from unittest import mock

import pytest

from discopop_library.EmpiricalAutotuning import Autotuner as autotuner_module
from discopop_library.EmpiricalAutotuning import __main__ as autotuner_main
from discopop_library.EmpiricalAutotuning.Autotuner import ReferenceConfigurationFailed, reference_failure_reason
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.output.progress import get_active_reporter, set_active_reporter


@pytest.mark.parametrize(
    "result, expected",
    [
        (ExecutionResult(1.0, 0, True, True), None),
        (ExecutionResult(0.1, 1, False, False, compilation_failed=True), "does not build"),
        (ExecutionResult(1.0, 3, False, True), "return code 3"),
        (ExecutionResult(1.0, 0, False, True), "validate.sh"),
    ],
)
def test_the_reason_names_what_failed(result: ExecutionResult, expected: Any) -> None:
    reason = reference_failure_reason(result)
    if expected is None:
        assert reason is None
    else:
        assert reason is not None and expected in reason


class _FailingReference:
    """Stands in for the reference ``CodeConfiguration``; its build fails."""

    created: List["_FailingReference"] = []

    def __init__(self, root_path: str, config_dot_dp_path: str, settings_name: str) -> None:
        self.root_path = root_path
        self.settings_name = settings_name
        self.execution_result: Any = None
        _FailingReference.created.append(self)

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        self.execution_result = ExecutionResult(0.1, 1, False, False, compilation_failed=True)

    def get_statistics_graph_label(self) -> str:
        return "reference"

    def get_statistics_graph_color(self) -> Any:
        return None


def _arguments(tmp_path: Any, compile_only: bool) -> Any:
    arguments = mock.Mock()
    arguments.project_path = str(tmp_path)
    arguments.dot_dp_path = str(tmp_path / ".discopop")
    arguments.configuration = "tiny"
    arguments.thread_count = 2
    arguments.compile_only = compile_only
    return arguments


def test_a_search_stops_when_the_reference_does_not_build(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "auto_tuner")
    monkeypatch.setattr(autotuner_module, "setup_auto_tuner", lambda _path: None)
    monkeypatch.setattr(autotuner_module, "CodeConfiguration", _FailingReference)
    # nothing after the reference may run: the hotspots are loaded right after it
    load_hotspots = mock.Mock(side_effect=AssertionError("the search went on"))
    monkeypatch.setattr(autotuner_module, "load_hotspots", load_hotspots)

    with pytest.raises(ReferenceConfigurationFailed, match="does not build.*tiny"):
        autotuner_module.run(_arguments(tmp_path, compile_only=False))

    assert get_active_reporter() is None
    assert not (tmp_path / "auto_tuner" / "results.json").exists()


def test_a_compile_only_run_goes_on_and_reports_the_reference_with_the_candidates(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / "auto_tuner")
    monkeypatch.setattr(autotuner_module, "setup_auto_tuner", lambda _path: None)
    monkeypatch.setattr(autotuner_module, "CodeConfiguration", _FailingReference)

    class _Reached(Exception):
        pass

    monkeypatch.setattr(autotuner_module, "StatisticsGraph", mock.Mock())
    monkeypatch.setattr(autotuner_module, "load_hotspots", mock.Mock(side_effect=_Reached))

    with pytest.raises(_Reached):
        autotuner_module.run(_arguments(tmp_path, compile_only=True))
    set_active_reporter(None)


def test_the_entry_point_reports_the_failure_and_exits_with_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    def failing(_arguments: Any) -> None:
        raise ReferenceConfigurationFailed("the reference does not build")

    with (
        mock.patch.object(autotuner_main, "parse_args"),
        mock.patch.object(autotuner_main, "setup_logger"),
        mock.patch.object(autotuner_main, "run", failing),
    ):
        with pytest.raises(SystemExit) as exit_info:
            autotuner_main.main()
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == "ERROR: the reference does not build\n"
