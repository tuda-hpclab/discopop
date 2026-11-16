# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from typing import List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.callpath_pruning_section import CallpathPruningSection
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import callpath_pruning
from discopop_library.ProjectManager.services.project_state import (
    CallpathPruningChanged,
    ConfigurationsChanged,
    HotspotsChanged,
    ProjectState,
)


@pytest.fixture
def section(qtbot: QtBot, tmp_path: Path) -> CallpathPruningSection:
    status = StatusLine()
    qtbot.addWidget(status)
    created = CallpathPruningSection(make_arguments(tmp_path), ProjectState(), status)
    qtbot.addWidget(created)
    return created


def write_hotspots(section: CallpathPruningSection) -> None:
    directory = Path(section.arguments.dot_dp) / "hotspot_detection"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Hotspots.json").write_text(json.dumps({"code_regions": [{"hotness": "YES"}]}))


def recorded(section: CallpathPruningSection, event_type: type) -> List[object]:
    events: List[object] = []
    section.project_state.subscribe(event_type, events.append)
    return events


def test_it_is_off_by_default_without_notice(section: CallpathPruningSection) -> None:
    assert not section.checkbox.isChecked()
    assert section.notice.isHidden()


def test_the_notice_appears_with_current_hotspots_while_pruning_is_off(section: CallpathPruningSection) -> None:
    write_hotspots(section)
    section.project_state.publish(HotspotsChanged())
    assert not section.notice.isHidden()
    text = section.notice.text_label.text()
    assert "not activated" in text and "GUI:" not in text  # it is shown at the setting


def test_activating_saves_the_setting_hides_the_notice_and_publishes_one_event(section: CallpathPruningSection) -> None:
    write_hotspots(section)
    section.refresh_notice()
    changes = recorded(section, CallpathPruningChanged)
    configurations = recorded(section, ConfigurationsChanged)
    section.depth_spin.setValue(5)  # only a finished entry is stored
    section.depth_spin.editingFinished.emit()
    section.unclassified.setCurrentText("prune")
    section.checkbox.setChecked(True)
    stored = callpath_pruning.load_callpath_pruning(section.arguments.project_dir)
    assert stored.enabled and stored.hot_depth == 5 and stored.unclassified == "prune"
    assert section.notice.isHidden()
    assert len(changes) == 3 and not configurations
    section.depth_spin.editingFinished.emit()  # nothing changed: nothing stored, nothing published
    assert len(changes) == 3


def test_the_depth_is_not_stored_with_every_key_stroke(section: CallpathPruningSection) -> None:
    section.depth_spin.setValue(7)
    assert callpath_pruning.load_callpath_pruning(section.arguments.project_dir).hot_depth == 2


def test_activating_without_hotspots_shows_the_missing_results(section: CallpathPruningSection) -> None:
    section.checkbox.setChecked(True)
    assert not section.notice.isHidden()
    assert "no current hotspot" in section.notice.text_label.text()


def test_the_setting_is_read_again_when_changed_outside_the_gui(section: CallpathPruningSection) -> None:
    callpath_pruning.save_callpath_pruning(
        section.arguments.project_dir, callpath_pruning.CallpathPruning(enabled=True, hot_depth=9, unclassified="prune")
    )
    changes = recorded(section, CallpathPruningChanged)
    section.reload()
    assert section.checkbox.isChecked() and section.depth_spin.value() == 9
    assert section.unclassified.currentText() == "prune"
    assert not changes  # showing it is no change


def test_the_hot_classes_are_stored_and_at_least_one_stays_checked(section: CallpathPruningSection) -> None:
    changes = recorded(section, CallpathPruningChanged)
    assert section.hotness_boxes["yes"].isChecked() and section.hotness_boxes["maybe"].isChecked()
    section.hotness_boxes["maybe"].setChecked(False)
    assert callpath_pruning.load_callpath_pruning(section.arguments.project_dir).hotness == "yes"
    assert len(changes) == 1
    section.hotness_boxes["yes"].setChecked(False)  # nothing would be hot: refused, the stored setting is shown
    assert callpath_pruning.load_callpath_pruning(section.arguments.project_dir).hotness == "yes"
    assert section.hotness_boxes["yes"].isChecked() and len(changes) == 1


def test_the_hot_classes_are_read_again_when_changed_outside_the_gui(section: CallpathPruningSection) -> None:
    callpath_pruning.save_callpath_pruning(
        section.arguments.project_dir, callpath_pruning.CallpathPruning(hotness="maybe")
    )
    section.reload()
    assert not section.hotness_boxes["yes"].isChecked() and section.hotness_boxes["maybe"].isChecked()
