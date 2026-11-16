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

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.help_dialogs import HelpDialog
from discopop_library.ProjectManager.qt_gui.panels.build_panel import BuildPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import callpath_pruning
from discopop_library.ProjectManager.services.project_state import CallpathPruningChanged, ConfigChanged, ProjectState


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
    # the chip no longer says "Cannot build" (it did while no configuration was selected)
    assert panel.header.chip.text() == "Ready to build"
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


def _add_configuration(panel: BuildPanel, name: str) -> None:
    configs = Path(panel.arguments.project_config_dir)
    (configs / name).mkdir(exist_ok=True)
    (configs / name / "execute.sh").write_text("true\n")


def test_a_configuration_can_be_released_into_the_build_of_another(
    qtbot: QtBot, panel: BuildPanel, dialog_answers: Any
) -> None:
    from discopop_library.ProjectManager.configurations.build_sharing import build_owner_of, members_of

    _add_configuration(panel, "big")
    select(panel, "tiny")
    section = panel.shared_build
    assert section.members_list.count() == 1 and section.checked_members() == []

    section.members_list.item(0).setCheckState(Qt.CheckState.Checked)
    config_dir = panel.arguments.project_config_dir
    qtbot.waitUntil(lambda: members_of(config_dir, "tiny") == ["big"])
    assert section.checked_members() == ["big"]
    assert not section.owner_combo.isEnabled()

    # the member sees its owner and cannot own builds
    select(panel, "big")
    assert build_owner_of(config_dir, "big") == "tiny"
    assert section.owner_combo.currentData() == "tiny"
    assert not section.members_list.isVisibleTo(panel)
    assert "builds from tiny" in panel.configuration_label.text()

    section.owner_combo.setCurrentIndex(0)
    section._owner_chosen(0)
    qtbot.waitUntil(lambda: build_owner_of(config_dir, "big") == "big")


def test_sharing_that_is_not_possible_is_explained(panel: BuildPanel, dialog_answers: Any) -> None:
    _add_configuration(panel, "big")
    configs = Path(panel.arguments.project_config_dir)
    (configs / "big" / "compile.sh").write_text("true\n")
    select(panel, "tiny")
    item = panel.shared_build.members_list.item(0)
    # a configuration with a compile script of its own is shown disabled, with the reason
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert "compile.sh" in item.toolTip()


def test_the_chip_warns_in_dp_mode_when_pruning_is_possible_but_off(panel: BuildPanel) -> None:
    hotspots = Path(panel.arguments.dot_dp) / "hotspot_detection"
    hotspots.mkdir(parents=True)
    (hotspots / "Hotspots.json").write_text(json.dumps({"code_regions": [{"hotness": "YES"}]}))
    select(panel)
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("dp"))
    panel.refresh()
    assert panel.header.chip.level == widgets.CHIP_WARN and panel.header.chip.text() == "Call path pruning is off"
    # other modes do not prune
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("seq"))
    panel.refresh()
    assert panel.header.chip.level != widgets.CHIP_WARN
    # activated: nothing to warn about
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("dp"))
    callpath_pruning.save_callpath_pruning(panel.arguments.project_dir, callpath_pruning.CallpathPruning(enabled=True))
    panel.project_state.publish(CallpathPruningChanged())
    assert panel.header.chip.text() != "Call path pruning is off"


def header_button_texts(panel: BuildPanel) -> List[str]:
    return [button.text() for button in panel.header.findChildren(QPushButton)]


def test_the_pruning_section_follows_the_shared_build_section(panel: BuildPanel) -> None:
    sections = [
        panel.findChildren(type(panel.shared_build))[0],
        panel.callpath_pruning,
        panel.builds,
    ]
    parent = panel.shared_build.parentWidget()
    assert parent is not None
    layout = parent.layout()
    assert layout is not None
    indices = [layout.indexOf(section) for section in sections]
    assert indices == sorted(indices) and indices[1] == indices[0] + 1


def test_the_explanation_is_behind_a_help_button_not_on_the_page(panel: BuildPanel, qtbot: QtBot) -> None:
    assert "Help" in header_button_texts(panel)
    page_texts = [label.text() for label in panel.findChildren(QLabel)]
    assert not any(text.startswith("Compiles the selected configuration") for text in page_texts)
    assert not any(
        box.title_label is not None and box.title_label.text() == "What happens" for box in sections_of(panel)
    )
    help_button = next(button for button in panel.header.findChildren(QPushButton) if button.text() == "Help")
    help_button.click()
    dialogs = [child for child in panel.children() if isinstance(child, HelpDialog)]
    assert len(dialogs) == 1 and "Nothing is run" in dialogs[0].text.toPlainText()
    qtbot.addWidget(dialogs[0])


def sections_of(panel: BuildPanel) -> List[widgets.FormSection]:
    return panel.findChildren(widgets.FormSection)
