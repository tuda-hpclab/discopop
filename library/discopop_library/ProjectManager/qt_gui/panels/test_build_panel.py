# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Build stage: it compiles without running, in the selected mode, and blocks the stages that run."""

from pathlib import Path
from typing import Any, List, Optional
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.panels.build_panel import BuildPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.project_state import ConfigChanged, ProjectState


class FakeTabs:
    def show_tab(self, name: str) -> None:
        pass

    def current_tab(self) -> str:
        return ""

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        pass

    def set_tab_title(self, name: str, title: str) -> None:
        pass


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> BuildPanel:
    arguments = make_arguments(tmp_path)
    configs = Path(arguments.project_config_dir)
    (configs / "tiny").mkdir()
    (configs / "tiny" / "compile.sh").write_text("true\n")
    (configs / "tiny" / "execute.sh").write_text("true\n")
    for mode in ("seq", "dp", "hd"):
        (configs / (mode + "_settings.json")).write_text("{}")
    status = StatusLine()
    qtbot.addWidget(status)
    created = BuildPanel(arguments, ProjectState(), status, FakeTabs())
    qtbot.addWidget(created)
    return created


def select(panel: BuildPanel, config: Optional[str] = "tiny") -> None:
    panel.project_state.current_config = config
    panel.project_state.publish(ConfigChanged(config))


def test_without_a_configuration_nothing_can_be_built(panel: BuildPanel) -> None:
    assert not panel.run_button.isEnabled() and not panel.rebuild_button.isEnabled()
    assert panel.header.chip.text() == "Cannot build"


def test_a_configuration_can_be_built_in_each_mode(panel: BuildPanel) -> None:
    select(panel)
    assert panel.run_button.isEnabled() and panel.rebuild_button.isEnabled()
    assert panel.build_label.text() == "No build yet."
    Path(panel.arguments.project_config_dir, "hd_settings.json").unlink()
    panel.mode_combo.setCurrentIndex(2)
    assert not panel.run_button.isEnabled()


def test_the_build_compiles_without_running(qtbot: QtBot, panel: BuildPanel) -> None:
    select(panel)
    seen: List[Any] = []
    states: List[bool] = []
    panel._run_state_changed = states.append

    def run(_arguments: Any, request: Any, _ctx: Any) -> bool:
        seen.append(request)
        return True

    with mock.patch("discopop_library.ProjectManager.qt_gui.panels.build_panel.run_preparation", run):
        panel.run_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
        panel.rebuild_button.click()
        qtbot.waitUntil(lambda: not panel.is_running(), timeout=20000)
    assert [(r.mode, r.build_policy, r.build_only, r.inplace) for r in seen] == [
        ("dp", "auto", True, False),
        ("dp", "rebuild", True, False),
    ]
    assert states == [True, False, True, False]
    assert panel.header.chip.text() == "Built"


def test_blocked_while_another_stage_runs(panel: BuildPanel) -> None:
    select(panel)
    panel.set_blocked(True)
    assert not panel.run_button.isEnabled()
    panel.set_blocked(False)
    assert panel.run_button.isEnabled()
