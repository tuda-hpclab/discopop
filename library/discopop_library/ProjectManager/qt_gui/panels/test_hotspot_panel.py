# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple
from unittest import mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import KIND_LOOP, MeasurementRun
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.panels import hotspot_panel
from discopop_library.ProjectManager.qt_gui.panels.hotspot_panel import HotspotPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import hotspot_session
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession
from discopop_library.ProjectManager.services.jobs import WorkContext
from discopop_library.ProjectManager.plots.hotspot_data import MeasurementLog
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    HotspotsChanged,
    ProjectState,
)

CS_ID = "1 loop 10 1\n2 func 20 1 compute\n3 loop 30 1\n"


class Env:
    """The panel plus the project directory and what the faked build / run / analysis did."""

    def __init__(self, panel: HotspotPanel, tmp_path: Path) -> None:
        self.panel = panel
        self.root = tmp_path
        self.dot_dp = Path(panel.arguments.dot_dp)
        self.source = tmp_path / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.published: List[HotspotsChanged] = []
        panel.project_state.subscribe(HotspotsChanged, self.published.append)
        self.executed: List[Tuple[str, Any]] = []  # (script name, timeout)
        self.next_result = 0
        self.exit_code = 0
        self.compile_exit_code = 0
        self.gate: Optional[threading.Event] = None
        self.threads: List[bool] = []
        self.executed_configs: List[str] = []  # the configuration of every execute.sh run
        self.failing_configs: List[str] = []  # their execute.sh fails
        self.compiled_scripts: List[str] = []  # the compile script of every build
        self.failing_compile_configs: List[str] = []  # their build fails
        self.gated_configs: Optional[List[str]] = None  # the gate holds only these (None: all)

    def add_configuration(self, name: str = "tiny") -> None:
        (self.root / ".discopop" / "project" / "configs" / name).mkdir(parents=True, exist_ok=True)
        (self.root / ".discopop" / "project" / "configs" / "hd_settings.json").write_text("{}")

    def select(self, name: Optional[str]) -> None:
        self.panel.project_state.current_config = name
        self.panel.project_state.publish(ConfigChanged(name))

    def write_results(self, runtimes: Tuple[float, ...] = (1.0, 3.0)) -> None:
        """An analysis of two regions of ``main.cpp`` (as discopop_hotspot_analyzer writes it)."""
        merged = self.dot_dp / "hotspot_detection" / "merged"
        merged.mkdir(parents=True, exist_ok=True)
        (self.dot_dp / "FileMapping.txt").write_text(f"1\t{self.source}\n")
        (merged / "cs_id.txt").write_text(CS_ID)
        regions = [
            {"csid": 1, "typ": "loop", "name": "", "avr": 3.0, "minVal": 1.0, "maxVal": 5.0, "ratio": 0.9},
            {"csid": 2, "typ": "func", "name": "compute", "avr": 1.0, "minVal": 0.5, "maxVal": 1.5, "ratio": 0.3},
            {"csid": 3, "typ": "loop", "name": "", "avr": 0.1, "minVal": 0.1, "maxVal": 0.1, "ratio": 0.5},
        ]
        for region, hotness in zip(regions, ("YES", "MAYBE", "NO")):
            region.update({"hotness": hotness, "runtimes": list(runtimes)})
        (self.dot_dp / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))

    def fake_execute(
        self, arguments: Any, root: str, config_path: str, settings: str, script: str, *args: Any, **kw: Any
    ) -> Any:
        name = Path(script).name
        self.executed.append((name, args[1]))
        self.threads.append(threading.current_thread() is threading.main_thread())
        private = self.dot_dp / "hotspot_detection" / "private"
        private.mkdir(parents=True, exist_ok=True)
        if name == "compile.sh":
            self.compiled_scripts.append(script)
            if Path(config_path).name in self.failing_compile_configs:
                return (2, 0.1, "", "")
            if self.compile_exit_code != 0:
                return (self.compile_exit_code, 0.1, "", "")
            (private / "cs_id.txt").write_text(CS_ID)
            (self.dot_dp / "FileMapping.txt").write_text(f"1\t{self.source}\n")
            return (0, 0.1, "", "")
        else:
            config = Path(config_path).name
            self.executed_configs.append(config)
            if self.gate is not None and (self.gated_configs is None or config in self.gated_configs):
                self.gate.wait(5)
            if config in self.failing_configs:
                return (3, 0.25, "", "broken input")
            if self.exit_code == 0:
                (private / f"hotspot_result_{self.next_result}.txt").write_text("1 2.0\n2 0.5\n3 0\n")
                self.next_result += 1
        return (self.exit_code, 0.25, "", "")

    def fake_analyzer(self, ctx: WorkContext) -> bool:
        ctx.status("⏳ Analyzing...")
        ctx.output("analyzed\n")
        self.write_results()
        return True


@pytest.fixture
def env(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    status = StatusLine()
    qtbot.addWidget(status)
    panel = HotspotPanel(make_arguments(tmp_path), ProjectState(), status, lambda: (11.0, 22.0, 33.0))
    qtbot.addWidget(panel)
    created = Env(panel, tmp_path)
    monkeypatch.setattr(hotspot_session, "execute_configuration", created.fake_execute)
    monkeypatch.setattr(HotspotSession, "invoke_analyzer", lambda self, ctx: created.fake_analyzer(ctx))
    return created


def cell(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    assert item is not None
    return item.text()


def wait_idle(qtbot: QtBot, panel: HotspotPanel) -> None:
    qtbot.waitUntil(lambda: not panel.running, timeout=10000)


def test_the_tab_starts_without_results_and_a_configuration(env: Env) -> None:
    panel = env.panel
    tabs = [panel.notebook.tabText(i) for i in range(panel.notebook.count())]
    assert tabs == ["Regions", "Runs", "Quadrant 1"]
    assert panel.header.chip.text() == "No configuration selected"
    assert not any(
        item.isEnabled()
        for item in (panel.run_button, panel.reinstrument_action, panel.analyze_action, panel.clear_action)
    )
    assert panel.facts_label.text() == "Accumulated runs: 0 · Code regions: no analysis results yet"
    assert panel.regions_stack.currentIndex() == 0
    assert panel.regions_empty_label.text() == "No measurement yet — press Run Measurement."
    assert panel.runs_stack.currentIndex() == 0
    assert panel.output.parent() is panel and panel.output_console() is panel.output
    assert panel.output_title == "Hotspots"
    assert panel.regions_table.rowCount() == 0 and panel.runs_table.rowCount() == 0


def configs_in_list(panel: HotspotPanel) -> List[Tuple[str, bool, str]]:
    items = [panel.config_list.topLevelItem(row) for row in range(panel.config_list.topLevelItemCount())]
    return [(i.text(0), i.checkState(0) == Qt.CheckState.Checked, i.text(1)) for i in items if i is not None]


def test_checking_a_configuration_enables_running(env: Env) -> None:
    env.add_configuration()
    env.panel.project_state.publish(ConfigurationsChanged())
    # nothing is selected in the header bar: nothing is checked
    assert configs_in_list(env.panel) == [("tiny", False, "not measured")]
    assert not env.panel.run_button.isEnabled() and env.panel.header.chip.text() == "No configuration selected"
    item = env.panel.config_list.topLevelItem(0)
    assert item is not None
    item.setCheckState(0, Qt.CheckState.Checked)
    assert env.panel.header.chip.text() == "No measurement yet"
    assert env.panel.run_button.isEnabled() and env.panel.reinstrument_action.isEnabled()
    assert env.panel.run_button.text() == "Run Measurement"
    assert not env.panel.analyze_action.isEnabled() and not env.panel.clear_action.isEnabled()
    env.panel.select_none_button.click()
    assert env.panel.selected_configs() == [] and not env.panel.reinstrument_action.isEnabled()
    env.panel.select_all_button.click()
    assert env.panel.run_button.isEnabled()


def test_by_default_the_configuration_of_the_header_bar_is_checked(env: Env) -> None:
    for name in ("big", "small"):
        env.add_configuration(name)
    env.select("small")
    assert configs_in_list(env.panel) == [("big", False, "not measured"), ("small", True, "not measured")]
    assert env.panel.run_button.text() == "Run Measurement"
    # until the user changes a check box, the list follows the header bar
    env.select("big")
    assert env.panel.selected_configs() == ["big"]
    env.panel.select_all_button.click()
    assert env.panel.run_button.text() == "Run Measurements"
    # afterwards the choice stays, and a new configuration starts unchecked
    env.select("small")
    env.add_configuration("new")
    env.panel.project_state.publish(ConfigurationsChanged())
    assert env.panel.selected_configs() == ["big", "small"]


def test_several_configurations_are_measured_one_after_another(qtbot: QtBot, env: Env) -> None:
    for name in ("big", "small", "unused"):
        env.add_configuration(name)
    env.panel.set_selected_configs(["big", "small"])
    env.panel.run_button.click()
    assert [state for _name, _checked, state in configs_in_list(env.panel)][:2] == ["queued", "queued"]
    wait_idle(qtbot, env.panel)
    # one build serves both (the same compile.sh), each is executed, the runs are analyzed once
    assert [name for name, _timeout in env.executed] == ["compile.sh", "execute.sh", "execute.sh"]
    assert env.executed_configs == ["big", "small"]
    out = env.panel.output.text()
    assert "=== big (1/2) ===" in out and "=== small (2/2) ===" in out and out.count("analyzed") == 1
    assert configs_in_list(env.panel) == [
        ("big", True, "✓ 1 run"),
        ("small", True, "✓ 1 run"),
        ("unused", False, "not measured"),
    ]
    assert [cell(env.panel.runs_table, row, 1) for row in range(2)] == ["big", "small"]
    assert env.panel.status.text() == "Hotspot measurement completed (2 measured)"
    assert len(env.published) == 1


def test_a_failing_configuration_does_not_stop_the_batch(qtbot: QtBot, env: Env) -> None:
    for name in ("big", "small"):
        env.add_configuration(name)
    env.failing_configs = ["big"]
    env.panel.select_all_button.click()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert env.executed_configs == ["big", "small"] and "analyzed" in env.panel.output.text()
    assert configs_in_list(env.panel) == [
        ("big", True, "✗ failed: execution failed (return code 3)"),
        ("small", True, "✓ 1 run"),
    ]
    assert env.panel.status.text() == "Hotspot measurement failed (1 measured, 1 failed ✗)"
    assert env.panel.status.color == widgets.STATUS_FAIL


def test_stop_ends_the_batch(qtbot: QtBot, env: Env) -> None:
    for name in ("big", "small"):
        env.add_configuration(name)
    env.panel.select_all_button.click()
    env.gate = threading.Event()
    env.panel.run_button.click()
    qtbot.waitUntil(lambda: env.executed_configs == ["big"], timeout=10000)
    qtbot.waitUntil(lambda: env.panel.header.chip.text() == "Measuring 1 of 2: big", timeout=10000)
    assert configs_in_list(env.panel)[0][2] == "⏳ measuring…: 1/2"
    assert not env.panel.select_all_button.isEnabled()
    env.panel.run_button.click()
    env.gate.set()
    wait_idle(qtbot, env.panel)
    assert env.executed_configs == ["big"] and "analyzed" not in env.panel.output.text()
    assert [state for _name, _checked, state in configs_in_list(env.panel)] == ["stopped", "stopped"]
    assert env.panel.status.text() == "Hotspot measurement stopped (2 stopped)"


def test_results_fill_the_tables_and_the_summary(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    panel = env.panel
    assert panel.facts_label.text() == "Accumulated runs: 0 · Code regions: 3 (YES 1 / MAYBE 1 / NO 1)"
    assert panel.regions_table.rowCount() == 3 and panel.regions_stack.currentIndex() == 1
    first = [panel.regions_table.item(0, column).text() for column in range(10)]  # type: ignore[union-attr]
    assert first[:4] == ["● YES", KIND_LOOP, "main.cpp:10", "—"] and first[4] == "3.00 s" and first[9] == "2"
    assert first[8] == "0.900" and first[6] == "1.00 s"
    avg = panel.regions_table.item(0, 4)
    assert avg is not None and avg.textAlignment() & Qt.AlignmentFlag.AlignRight
    assert panel.clear_action.isEnabled()
    assert panel.regions_empty_label.text() == "No measurement yet — press Run Measurement."


def test_results_without_an_analysis_say_so(env: Env) -> None:
    env.panel.runs = [MeasurementRun(0, "c")]
    env.panel._populate_regions_table()
    assert env.panel.regions_stack.currentIndex() == 0 and "Re-run Analysis" in env.panel.regions_empty_label.text()


def test_filters_and_sorting_of_the_regions_table(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    panel = env.panel

    def column(index: int) -> List[str]:
        return [panel.regions_table.item(row, index).text() for row in range(panel.regions_table.rowCount())]  # type: ignore[union-attr]

    panel.hotness_checks["NO"].setChecked(False)
    assert column(0) == ["● YES", "● MAYBE"]
    panel.kind_combo.setCurrentText(KIND_LOOP)
    assert column(0) == ["● YES"]
    panel.kind_combo.setCurrentText("all")
    panel.hotness_checks["NO"].setChecked(True)
    panel._sort_regions_by_section(4)  # Avg (s): descending first
    assert column(4) == ["3.00 s", "1.00 s", "100 ms"]
    panel._sort_regions_by_section(4)
    assert column(4) == ["100 ms", "1.00 s", "3.00 s"]
    panel._sort_regions_by_section(3)  # Name
    assert column(3) == ["compute", "—", "—"]


def test_a_clicked_row_shows_in_the_detail_bar_and_opens_in_vscode(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    panel = env.panel
    assert not panel.regions_detail._actions[0][0].isEnabled()
    panel.regions_table.selectRow(1)
    assert ("Name", "compute") in panel.regions_detail.fields and ("Hotness", "MAYBE") in panel.regions_detail.fields
    assert panel.regions_detail._actions[0][0].isEnabled()
    with (
        mock.patch.object(hotspot_panel, "find_code_executable", return_value="code"),
        mock.patch.object(hotspot_panel, "open_file_at") as open_file_at,
    ):
        panel.regions_detail._actions[0][0].click()
    open_file_at.assert_called_once_with("code", str(env.source), 20)


def test_vscode_problems_are_reported(env: Env, dialog_answers: DialogRecorder) -> None:
    env.write_results()
    env.panel.refresh_results()
    region = env.panel.regions[0]
    with mock.patch.object(hotspot_panel, "find_code_executable", return_value=None):
        env.panel._open_region_in_vscode(region)
    env.source.unlink()
    with mock.patch.object(hotspot_panel, "find_code_executable", return_value="code"):
        env.panel._open_region_in_vscode(region)
    with (
        mock.patch.object(hotspot_panel, "find_code_executable", return_value="code"),
        mock.patch.object(hotspot_panel, "open_file_at", side_effect=OSError("boom")),
    ):
        env.source.write_text("")
        env.panel._open_region_in_vscode(region)
    assert dialog_answers.titles() == ["VSCode Not Found", "File Not Found", "Failed to open VSCode"]
    env.panel._open_region_in_vscode(None)  # nothing selected: no dialog
    assert len(dialog_answers.calls) == 3


def test_chart_tabs_are_added_rendered_and_closed(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    panel = env.panel
    bars = panel.add_plot("bars")
    assert panel.notebook.tabText(3) == "Bars 2" and panel.notebook.currentWidget() is bars.widget
    assert bars.top_n is not None
    bars.top_n.setCurrentText("10")  # re-renders without an error
    profile = panel.add_plot("profile")
    assert profile.region_combo is not None and profile.region_combo.count() == 3
    assert profile.region_combo.currentText().startswith("main.cpp:10")
    profile.region_combo.setCurrentIndex(1)
    assert profile.region_combo.currentIndex() == 1
    panel.refresh_results()  # keeps the picked region
    assert profile.region_combo.currentIndex() == 1
    panel.notebook.tabCloseRequested.emit(3)
    assert len(panel.plot_tabs) == 2
    for fixed in (0, 1):
        panel.notebook.tabCloseRequested.emit(fixed)
    assert panel.notebook.count() == 4 and panel.notebook.tabText(0) == "Regions"
    panel._close_tab_widget(profile.widget)
    assert len(panel.plot_tabs) == 1 and panel.notebook.currentIndex() == 0


def test_a_clicked_chart_region_shows_in_its_detail_bar(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    tab = env.panel.plot_tabs[0]
    assert not tab.detail._actions[0][0].isEnabled()
    env.panel._on_plot_region_selected(tab, env.panel.regions[0])
    assert ("Hotness", "YES") in tab.detail.fields and tab.detail._actions[0][0].isEnabled()
    env.panel.refresh_results()  # the selection belongs to the old analysis
    assert tab.selection is None and tab.detail.fields == []


def test_a_measurement_instruments_runs_and_analyzes(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    panel = env.panel
    panel.repetitions.setValue(2)
    completed_on: List[bool] = []
    original = panel._on_work_complete

    def complete(success: bool, cancelled: bool) -> None:
        completed_on.append(threading.current_thread() is threading.main_thread())
        original(success, cancelled)

    panel._on_work_complete = complete  # type: ignore[method-assign]
    panel.run_button.click()
    assert panel.running and panel.run_button.is_running() and panel.run_button.isEnabled()
    assert panel.run_button.text() == "■ Stop" and not panel.reinstrument_action.isEnabled()
    assert panel.header.chip.text() == "Measurement running" and not panel.run_button.can_run()
    assert panel.status.text() == "⏳ Hotspot measurement in progress..."
    wait_idle(qtbot, panel)
    assert completed_on == [True]  # the handler ran on the main thread

    # compile.sh once, execute.sh per repetition, with the timeouts of the Execute tab
    assert env.executed == [("compile.sh", 22.0), ("execute.sh", 11.0), ("execute.sh", 11.0)]
    assert panel.runs_table.rowCount() == 2
    assert [cell(panel.runs_table, 0, column) for column in (0, 1, 3, 4, 5)] == [
        "0",
        "tiny",
        "0.250",
        "✓ ok",
        "2",
    ]
    assert panel.facts_label.text().startswith("Accumulated runs: 2 ·")
    assert panel.header.chip.text() == "Up to date"
    assert panel.regions_table.rowCount() == 3
    out = panel.output.text()
    assert "Compiling 'tiny' in 'hd' mode (inplace)..." in out and "Executing 'tiny' (2/2)..." in out
    assert "Recorded run 1." in out and "analyzed" in out
    assert len(env.published) == 1
    assert panel.status.text() == "Hotspot measurement completed" and panel.status.color == widgets.STATUS_OK
    assert panel.run_button.text() == "Run Measurement" and panel.run_button.isEnabled()
    assert not panel.run_button.is_running() and panel.analyze_action.isEnabled()
    assert all(env.threads[:1]) is False  # the work ran off the main thread
    log = hotspot_data.deserialize_log(json.loads(Path(hotspot_data.sidecar_path(panel.arguments.dot_dp)).read_text()))
    assert len(log.runs) == 2 and log.compile_script is not None


def test_a_current_build_is_not_compiled_again_and_reinstrument_does_not_run(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert env.panel.header.chip.text() == "Only one run"
    env.executed.clear()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert [name for name, _ in env.executed] == ["execute.sh"]
    env.executed.clear()
    env.panel.reinstrument_action.trigger()
    wait_idle(qtbot, env.panel)
    assert [name for name, _ in env.executed] == ["compile.sh"]
    assert "Keeping the 2 accumulated run(s)" in env.panel.output.text()
    assert len(env.published) == 3


def test_a_failing_run_is_reported(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.compile_exit_code = 3
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert "Instrumentation failed (return code: 3)" in env.panel.output.text()
    assert env.executed == [("compile.sh", 22.0)] and len(env.published) == 1
    # the build is not current after a failed instrumentation, so the next try compiles again; only execute fails
    env.compile_exit_code = 0
    env.exit_code = 3
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert "Execution failed (return code: 3)" in env.panel.output.text()
    assert env.panel.status.text() == "Hotspot measurement failed" and env.panel.status.color == widgets.STATUS_FAIL
    assert env.panel.run_button.isEnabled() and len(env.published) == 2


def test_a_crashing_worker_does_not_leave_the_tab_stuck(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    with mock.patch.object(HotspotSession, "run_batch", side_effect=RuntimeError("kaboom")):
        env.panel.run_button.click()
        wait_idle(qtbot, env.panel)
    assert "Error: kaboom" in env.panel.output.text()
    assert env.panel.status.text() == "Hotspot measurement failed" and env.panel.run_button.isEnabled()


def test_missing_hd_settings_stop_the_measurement(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    (env.root / ".discopop" / "project" / "configs" / "hd_settings.json").unlink()
    env.select("tiny")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert "hd_settings.json not found" in env.panel.output.text() and env.executed == []


def test_stop_cancels_the_measurement(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.gate = threading.Event()
    env.panel.repetitions.setValue(3)
    env.panel.run_button.click()
    qtbot.waitUntil(lambda: ("execute.sh", 11.0) in env.executed, timeout=10000)
    env.panel.run_button.click()
    assert not env.panel.run_button.isEnabled() and env.panel.run_button.text() == "Stopping…"
    assert (
        env.panel.status.text() == "Stopping hotspot measurement..." and env.panel.status.color == widgets.STATUS_STOP
    )
    env.gate.set()
    wait_idle(qtbot, env.panel)
    assert "Stopped by user." in env.panel.output.text()
    assert env.panel.status.text() == "Hotspot measurement stopped" and env.panel.status.color == widgets.STATUS_STOP
    assert len(env.published) == 1


def test_closing_cancels_a_running_measurement(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.gate = threading.Event()
    env.panel.repetitions.setValue(2)
    env.panel.run_button.click()
    qtbot.waitUntil(lambda: ("execute.sh", 11.0) in env.executed, timeout=10000)
    env.panel.cancel_jobs()
    env.gate.set()
    wait_idle(qtbot, env.panel)
    assert "Stopped by user." in env.panel.output.text()
    env.panel.cancel_jobs()  # nothing running: no error


def test_rerun_analysis_needs_runs_and_does_not_execute(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    env.executed.clear()
    env.published.clear()
    env.panel.output.set_text("old output")
    env.panel.analyze_action.trigger()
    assert env.panel.running and env.panel.run_button.is_running() and env.panel.output.text() == ""
    assert env.panel.status.text() == "⏳ Hotspot analysis in progress..."
    wait_idle(qtbot, env.panel)
    assert env.executed == [] and "analyzed" in env.panel.output.text() and len(env.published) == 1


def test_starting_twice_or_without_a_configuration_is_refused(
    qtbot: QtBot, env: Env, dialog_answers: DialogRecorder
) -> None:
    env.panel.run_measurement()
    assert dialog_answers.titles("show_warning") == ["No Configuration Selected"]
    env.add_configuration()
    env.select("tiny")
    env.gate = threading.Event()
    env.panel.run_button.click()
    env.panel.run_measurement()
    env.panel.rerun_analysis()
    env.panel.clear_measurements()
    assert dialog_answers.titles("show_error") == ["Already Running", "Already Running", "Measurement Running"]
    env.gate.set()
    wait_idle(qtbot, env.panel)


def test_clearing_asks_first_removes_the_data_and_publishes(
    qtbot: QtBot, env: Env, dialog_answers: DialogRecorder
) -> None:
    env.add_configuration()
    env.select("tiny")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    env.published.clear()
    dialog_answers.answer("ask_yes_no", False, True)
    env.panel.clear_action.trigger()
    assert env.panel.regions_table.rowCount() == 3 and env.published == []
    assert "(1 run(s))" in dialog_answers.messages("ask_yes_no")[0]
    env.panel.clear_action.trigger()
    assert env.panel.regions_table.rowCount() == 0 and env.panel.runs_table.rowCount() == 0
    assert not (env.dot_dp / "hotspot_detection").exists() and (env.dot_dp / "FileMapping.txt").exists()
    assert len(env.published) == 1 and env.panel.output.text() == ""
    assert env.panel.status.text() == "Hotspot measurements cleared"
    assert not env.panel.clear_action.isEnabled() and not env.panel.analyze_action.isEnabled()
    assert env.panel.regions_stack.currentIndex() == 0


def test_one_accumulated_run_warns_about_the_ratio(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    chip = env.panel.header.chip
    assert chip.level == widgets.CHIP_WARN and chip.text() == "Only one run"
    assert "every ratio is 0.5" in chip.detail()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert chip.level == widgets.CHIP_OK and chip.text() == "Up to date" and chip.detail() == ""


def test_starting_a_job_opens_the_output_pane(qtbot: QtBot, env: Env) -> None:
    env.add_configuration()
    env.select("tiny")
    with qtbot.waitSignal(env.panel.output_requested):
        env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    with qtbot.waitSignal(env.panel.output_requested):
        env.panel.reinstrument_action.trigger()
    wait_idle(qtbot, env.panel)
    with qtbot.waitSignal(env.panel.output_requested):
        env.panel.analyze_action.trigger()
    wait_idle(qtbot, env.panel)


def test_the_detail_bar_shows_no_stale_placeholder_before_the_event_loop_runs(env: Env) -> None:
    env.write_results()
    env.panel.refresh_results()
    env.panel.show()
    bar = env.panel.regions_detail
    item = bar._body_layout.itemAt(0)
    assert item is not None
    placeholder = item.widget()
    assert placeholder is not None
    bar.show_fields([("Kind", "LOOP")])
    assert placeholder.isHidden()  # deleteLater has not run yet


def test_a_configuration_with_its_own_compile_script_is_instrumented_again(qtbot: QtBot, env: Env) -> None:
    for name in ("a", "b", "c"):
        env.add_configuration(name)
    configs = env.root / ".discopop" / "project" / "configs"
    (configs / "compile.sh").write_text("$CXX main.cpp\n")
    (configs / "b" / "compile.sh").write_text("$CXX -DBIG main.cpp\n")
    env.panel.select_all_button.click()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    # a: shared script; b: its own; c: the shared one again
    assert env.compiled_scripts == [
        str(configs / "compile.sh"),
        str(configs / "b" / "compile.sh"),
        str(configs / "compile.sh"),
    ]
    assert env.executed_configs == ["a", "b", "c"]


def test_a_failed_instrumentation_is_not_reused_by_the_next_configuration(qtbot: QtBot, env: Env) -> None:
    for name in ("a", "b"):
        env.add_configuration(name)
    env.panel.select_all_button.click()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    # the build is current now; a failing rebuild of a must not let b run on what it left behind
    env.compiled_scripts.clear()
    env.executed_configs.clear()
    env.failing_compile_configs = ["a"]
    env.panel.reinstrument_action.setEnabled(True)
    env.panel.session.save_log(replace_compile_script(env.panel.session.load_log(), "/elsewhere/compile.sh"))
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert len(env.compiled_scripts) == 2 and env.executed_configs == ["b"]
    assert configs_in_list(env.panel)[0][2] == "✗ failed: instrumentation failed (return code 2)"


def test_nothing_measured_skips_the_analysis(qtbot: QtBot, env: Env) -> None:
    for name in ("big", "small"):
        env.add_configuration(name)
    env.failing_configs = ["big", "small"]
    env.panel.select_all_button.click()
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert "the analysis is skipped" in env.panel.output.text() and "analyzed" not in env.panel.output.text()
    assert env.panel.status.text() == "Hotspot measurement failed (2 failed ✗)"


def test_a_stop_after_a_measured_configuration_keeps_its_runs(qtbot: QtBot, env: Env) -> None:
    for name in ("big", "small"):
        env.add_configuration(name)
    env.panel.select_all_button.click()
    env.gate = threading.Event()
    env.gated_configs = ["small"]
    env.panel.run_button.click()
    qtbot.waitUntil(lambda: env.executed_configs == ["big", "small"], timeout=10000)
    env.panel.run_button.click()
    env.gate.set()
    wait_idle(qtbot, env.panel)
    assert "use Re-run Analysis" in env.panel.output.text() and "analyzed" not in env.panel.output.text()
    assert [state for _name, _checked, state in configs_in_list(env.panel)] == ["✓ 1 run", "stopped"]
    assert env.panel.analyze_action.isEnabled()


def test_the_list_follows_clearing_and_ignores_changes_while_running(
    qtbot: QtBot, env: Env, dialog_answers: DialogRecorder
) -> None:
    env.add_configuration("big")
    env.select("big")
    env.panel.run_button.click()
    wait_idle(qtbot, env.panel)
    assert configs_in_list(env.panel) == [("big", True, "✓ 1 run")]
    dialog_answers.answer("ask_yes_no", True)
    env.panel.clear_measurements()
    assert configs_in_list(env.panel) == [("big", True, "not measured")]

    env.gate = threading.Event()
    env.panel.run_button.click()
    qtbot.waitUntil(lambda: env.executed_configs[-1:] == ["big"] and env.panel.running, timeout=10000)
    env.add_configuration("new")
    env.panel.project_state.publish(ConfigurationsChanged())
    assert [name for name, _checked, _state in configs_in_list(env.panel)] == ["big"]
    env.gate.set()
    wait_idle(qtbot, env.panel)
    # rebuilt once the batch ended (the header bar still selects big)
    assert [(name, checked) for name, checked, _state in configs_in_list(env.panel)] == [("big", True), ("new", False)]


def replace_compile_script(log: MeasurementLog, script: str) -> MeasurementLog:
    log.compile_script = script
    return log
