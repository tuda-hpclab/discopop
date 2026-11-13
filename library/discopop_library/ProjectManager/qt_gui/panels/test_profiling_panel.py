# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Profiling stage: a dp run in place, its preconditions and the profiling data it leaves."""

import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.configurations.project_environment import (
    ProjectDirectories,
    record_instrumented_directories,
)
from discopop_library.ProjectManager.services.excluded_directories import save_excluded_directories
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.panels.profiling_panel import ProfilingPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.tabs import TAB_SETUP
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ProjectDirectoriesChanged,
    ProjectState,
    ResultsChanged,
)

ExecuteResult = Optional[Tuple[int, float, str, str]]


class FakeTabs:
    def __init__(self) -> None:
        self.shown: List[str] = []

    def show_tab(self, name: str) -> None:
        self.shown.append(name)

    def current_tab(self) -> str:
        return ""

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        pass

    def set_tab_title(self, name: str, title: str) -> None:
        pass


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> ProfilingPanel:
    arguments = make_arguments(tmp_path)
    configs = Path(arguments.project_config_dir)
    (configs / "tiny").mkdir()
    (configs / "tiny" / "compile.sh").write_text("true\n")
    (configs / "tiny" / "execute.sh").write_text("true\n")
    (configs / "seq_settings.json").write_text("{}")
    (configs / "dp_settings.json").write_text("{}")
    status = StatusLine()
    qtbot.addWidget(status)
    created = ProfilingPanel(arguments, ProjectState(), status, FakeTabs())
    qtbot.addWidget(created)
    return created


def select(panel: ProfilingPanel, config: Optional[str] = "tiny") -> None:
    panel.project_state.current_config = config
    panel.project_state.publish(ConfigChanged(config))


def test_without_a_configuration_nothing_can_be_profiled(panel: ProfilingPanel) -> None:
    assert not panel.run_button.isEnabled()
    assert panel.header.chip.text() == "Cannot profile" and panel.configuration_label.text() == "—"
    select(panel)
    assert panel.run_button.isEnabled() and panel.header.chip.text() == ""
    assert panel.configuration_label.text() == "tiny" and panel.data_label.text() == "No profiling data yet."


def test_missing_dp_settings_point_to_the_setup(panel: ProfilingPanel) -> None:
    Path(panel.arguments.project_config_dir, "dp_settings.json").unlink()
    select(panel)
    assert not panel.run_button.isEnabled() and "dp_settings.json" in panel.header.chip.detail_label.text()
    assert not panel.goto_setup_button.isHidden()
    panel.goto_setup_button.click()
    assert isinstance(panel.tabs, FakeTabs) and panel.tabs.shown == [TAB_SETUP]


def test_existing_profiling_data_is_described(panel: ProfilingPanel) -> None:
    profiler = Path(panel.arguments.dot_dp, "profiler")
    profiler.mkdir(parents=True)
    (profiler / "Data.xml").write_text("")
    panel.project_state.publish(ResultsChanged())
    text = panel.data_label.text()
    assert text[:4].isdigit() and "missing: dynamic_dependencies.txt" in text


def test_blocked_while_execute_runs(panel: ProfilingPanel) -> None:
    select(panel)
    panel.set_blocked(True)
    assert not panel.run_button.isEnabled() and panel.header.chip.text() == "Execute is running"
    panel.set_blocked(False)
    assert panel.run_button.isEnabled() and panel.header.chip.text() == ""


def test_profiling_runs_dp_in_place(qtbot: QtBot, panel: ProfilingPanel) -> None:
    select(panel)
    results: List[ExecuteResult] = [(0, 0.5, "", ""), (0, 1.0, "", "")]
    published: List[str] = []
    running: List[bool] = []
    panel._run_state_changed = running.append
    panel.project_state.subscribe(ResultsChanged, lambda _e: published.append("results"))
    calls: List[Tuple[Any, ...]] = []

    def fake(*args: Any, **_kwargs: Any) -> ExecuteResult:
        calls.append(args)
        return results.pop(0)

    with mock.patch.object(execution_run, "execute_configuration", fake):
        with qtbot.waitSignal(panel.output_requested, timeout=1000):
            panel.run_button.click()
        assert panel.header.chip.text() == "Profiling" and panel.run_button.is_running()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    output = panel.console.text()
    assert "Compiling in 'dp' mode with inplace execution..." in output
    assert output.rstrip().endswith("=== Pattern detection preparation complete ===")
    assert calls[0][1] == panel.arguments.project_root and calls[0][3].endswith("dp_settings.json")
    assert calls[0][0].execute_inplace is True and calls[0][0].log_level == "INFO"
    assert panel.run_button.text() == "Profile for Pattern Detection" and panel.run_button.isEnabled()
    assert panel.status.text() == "Ready" and panel.header.chip.text() == "Profiled"
    assert published == ["results"] and running == [True, False]


def test_the_timeouts_reach_the_work(qtbot: QtBot, panel: ProfilingPanel) -> None:
    select(panel)
    panel.timeout_compilation_spin.setValue(11)
    panel.timeout_execution_spin.setValue(22)
    panel.timeout_validation_spin.setValue(33)
    seen: List[Any] = []

    def run(_arguments: Any, request: Any, _ctx: Any) -> bool:
        seen.append(request)
        return True

    with mock.patch("discopop_library.ProjectManager.qt_gui.panels.profiling_panel.run_preparation", run):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert (seen[0].timeout_compilation, seen[0].timeout_execution, seen[0].timeout_validation) == (11, 22, 33)
    assert seen[0].mode == "dp" and seen[0].configuration == "tiny"


def test_a_failing_profiling_run_is_reported(qtbot: QtBot, panel: ProfilingPanel) -> None:
    select(panel)
    with mock.patch.object(execution_run, "execute_configuration", lambda *a, **k: (1, 0.1, "", "")):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert "Compilation failed (return code: 1)" in panel.console.text()
    assert "=== Pattern detection preparation failed ===" in panel.console.text()
    assert panel.status.text() == "Pattern detection preparation failed"
    assert panel.status.color == widgets.STATUS_FAIL
    assert panel.run_button.isEnabled() and panel.header.chip.text() == "Failed"


def test_profiling_can_be_stopped(qtbot: QtBot, panel: ProfilingPanel) -> None:
    select(panel)
    started = threading.Event()
    release = threading.Event()

    def blocking(*_args: Any, **_kwargs: Any) -> ExecuteResult:
        started.set()
        release.wait(20)
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", blocking):
        panel.run_button.click()
        assert started.wait(20)
        panel.run_button.click()
        assert panel.status.text() == "Stopping profiling..."
        release.set()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert "preparation stopped by user" in panel.console.text() and panel.header.chip.text() == "Stopped"
    assert panel.status.text() == "Ready"


def test_data_profiled_with_other_directories_is_warned_about(panel: ProfilingPanel) -> None:
    select(panel)
    record_instrumented_directories(panel.arguments.dot_dp, "dp", ProjectDirectories(excluded=("src",)))
    save_excluded_directories(panel.arguments.project_dir, ["src"])
    panel.project_state.publish(ProjectDirectoriesChanged())
    assert panel.header.chip.text() == ""
    save_excluded_directories(panel.arguments.project_dir, ["lib"])
    panel.project_state.publish(ProjectDirectoriesChanged())
    chip = panel.header.chip
    assert chip.level == widgets.CHIP_WARN and chip.text() == "Project directories changed"
    assert "src" in chip.detail() and "lib" in chip.detail()
    assert panel.run_button.isEnabled()  # profiling again is the fix
