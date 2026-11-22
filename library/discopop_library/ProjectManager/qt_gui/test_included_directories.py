# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.included_directories import IncludedDirectoriesList
from discopop_library.ProjectManager.services.included_directories import load_included_directories


def test_a_hand_written_path_need_not_exist_and_can_be_removed(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    root, project_dir = tmp_path / "project", tmp_path / "project" / ".discopop" / "project"
    root.mkdir(parents=True)
    widget = IncludedDirectoriesList(str(root), str(project_dir))
    qtbot.addWidget(widget)
    missing = str(tmp_path / "shared" / "later")
    dialog_answers.answer("ask_string", missing, "relative/dir", str(root / "src"))
    widget.add_path_button.click()
    assert load_included_directories(str(project_dir)) == [missing]
    assert widget.list.count() == 1 and widget.list.currentRow() == 0
    # not accepted: relative, inside the project
    widget.add_path_button.click()
    widget.add_path_button.click()
    assert dialog_answers.titles("show_warning") == ["Cannot add the path"] * 2
    widget.remove_button.click()
    assert load_included_directories(str(project_dir)) == []
