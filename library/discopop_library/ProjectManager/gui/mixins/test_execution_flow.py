# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Drives the execution panel's run logic headlessly: widgets are mocks, ``after`` is pumped by the test.

There is no GUI test infrastructure (no display in CI); this checks that the worker/handler split of the panel works
together: the worker reports only through events, and all widget updates happen in the handler on the calling thread.
"""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, List, Optional, Tuple
from unittest import mock

import pytest

from discopop_library.ProjectManager.gui.mixins import execution as execution_module
from discopop_library.ProjectManager.gui.mixins.execution import ExecutionMixin
from discopop_library.ProjectManager.services.project_state import ProjectState, ResultsChanged


class _Var:
    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


class _FakeApp(ExecutionMixin):
    """The execution mixin on top of mock widgets."""

    def __init__(self, project_root: Path) -> None:
        self.queued: List[Callable[[], None]] = []
        self.widget_threads: List[int] = []
        # the mocks live in ``m`` (typed Any); the mixin sees them as its widgets and variables
        self.m = SimpleNamespace(
            status_label=mock.MagicMock(),
            run_button=mock.MagicMock(),
            prepare_pattern_detection_button=mock.MagicMock(),
            generate_report_button=mock.MagicMock(),
            view_report_button=mock.MagicMock(),
            stop_execution_button=mock.MagicMock(),
            output_text=mock.MagicMock(),
            refresh_config_list=mock.MagicMock(),
            update_report_display=mock.MagicMock(),
        )
        for widget in (self.m.status_label, self.m.run_button, self.m.generate_report_button, self.m.output_text):
            widget.config.side_effect = self._record_widget_use
        attributes = dict(
            arguments=SimpleNamespace(
                project_root=str(project_root),
                project_config_dir=str(project_root / ".discopop" / "project" / "configs"),
                dot_dp=str(project_root / ".discopop"),
                execution_time_regex=None,
                project_dir=str(project_root / ".discopop" / "project"),
            ),
            current_config="tiny",
            mode_vars={"seq": _Var(True), "dp": _Var(False)},
            inplace_var=_Var(True),
            skip_cleanup_var=_Var(False),
            thread_var=_Var(2),
            label_prefix_var=_Var(""),
            timeout_execution_var=_Var(10),
            timeout_compilation_var=_Var(10),
            timeout_validation_var=_Var(10),
            execution_repetitions_var=_Var(1),
            log_level_var=_Var("INFO"),
            suggestions_mode_var=_Var("none"),
            status_label=self.m.status_label,
            run_button=self.m.run_button,
            prepare_pattern_detection_button=self.m.prepare_pattern_detection_button,
            generate_report_button=self.m.generate_report_button,
            view_report_button=self.m.view_report_button,
            stop_execution_button=self.m.stop_execution_button,
            output_text=self.m.output_text,
            _refresh_config_list=self.m.refresh_config_list,
            _update_pattern_detection_ui=mock.MagicMock(),
            _update_execute_modes=mock.MagicMock(),
            _set_status=mock.MagicMock(),
        )
        for name, value in attributes.items():
            setattr(self, name, value)
        self.project_state = ProjectState()
        self.project_state.subscribe(ResultsChanged, lambda _e: self.m.update_report_display())
        self.config_dir = attributes["arguments"].project_config_dir

    def _record_widget_use(self, **_kwargs: Any) -> None:
        self.widget_threads.append(threading.get_ident())

    def after(self, _delay: int, func: Callable[[], None]) -> None:
        self.queued.append(func)

    def pump(self, until: Callable[[], bool], timeout: float = 20) -> None:
        deadline = time.time() + timeout
        while not until():
            assert time.time() < deadline, "timed out"
            pending, self.queued = self.queued, []  # callbacks that re-schedule themselves run once per round
            for callback in pending:
                callback()
            time.sleep(0.01)


def _output(app: _FakeApp) -> str:
    return "".join(call.args[1] for call in app.m.output_text.insert.call_args_list)


@pytest.fixture
def app(tmp_path: Path) -> _FakeApp:
    (tmp_path / ".discopop" / "project" / "configs" / "tiny").mkdir(parents=True)
    return _FakeApp(tmp_path)


def _run(app: _FakeApp, results: List[Optional[Tuple[int, float, str, str]]]) -> List[Tuple[Any, ...]]:
    calls: List[Tuple[Any, ...]] = []

    def fake_execute_configuration(*args: Any, **kwargs: Any) -> Optional[Tuple[int, float, str, str]]:
        calls.append(args)
        callback = kwargs.get("process_started_callback")
        assert callback is not None  # the stop button depends on it
        return results.pop(0)

    with mock.patch.object(execution_module, "execute_configuration", fake_execute_configuration):
        app._run_execution()
        app.pump(lambda: app.m.run_button.config.call_args_list[-1] == mock.call(state="normal", text="Run"))
    return calls


def test_a_successful_run_is_reported_on_the_main_thread(app: _FakeApp) -> None:
    calls = _run(app, [(0, 0.5, "compiled", ""), (0, 1.25, "result", "")])
    assert len(calls) == 2  # compile, then execute
    output = _output(app)
    assert "=== SEQ mode ===" in output
    assert "Compilation succeeded (0.50s)" in output
    assert "stdout: compiled" in output
    assert "Execution succeeded (1.25s)" in output
    assert "stdout: result" in output
    assert output.rstrip().endswith("=== Execution complete ===")
    # widgets are only touched from the thread that pumps `after`, never from the worker
    assert set(app.widget_threads) == {threading.get_ident()}
    app.m.status_label.config.assert_called_with(text="Ready", foreground=mock.ANY)
    app.m.refresh_config_list.assert_called_once()
    app.m.update_report_display.assert_called_once()
    app.m.stop_execution_button.config.assert_called_with(state="disabled")
    assert app._execution_job is None


def test_a_failing_compilation_skips_the_execution(app: _FakeApp) -> None:
    calls = _run(app, [(2, 0.1, "", "error")])
    assert len(calls) == 1
    assert "Compilation failed (return code: 2)" in _output(app)
    assert "Execution succeeded" not in _output(app)


def test_a_crash_of_the_worker_does_not_leave_the_buttons_disabled(app: _FakeApp) -> None:
    def crashing(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("boom")

    with mock.patch.object(execution_module, "execute_configuration", crashing):
        app._run_execution()
        app.pump(lambda: app.m.run_button.config.call_args_list[-1] == mock.call(state="normal", text="Run"))
    assert "Error: boom" in _output(app)


def test_the_stop_button_cancels_the_run(app: _FakeApp) -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking(*args: Any, **kwargs: Any) -> Tuple[int, float, str, str]:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    app.mode_vars["dp"].set(True)  # type: ignore[attr-defined]  # two modes: the second one must not start after the stop
    with mock.patch.object(execution_module, "execute_configuration", blocking):
        app._run_execution()
        assert started.wait(20)
        app._stop_execution()
        release.set()
        app.pump(lambda: app._execution_job is None)
    output = _output(app)
    assert "=== SEQ mode ===" in output
    assert "=== DP mode ===" not in output
