# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path
from typing import List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import openmp_section
from discopop_library.ProjectManager.qt_gui.openmp_section import OpenMPSection
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import openmp_handling
from discopop_library.ProjectManager.services.project_state import ProjectDirectoriesChanged, ProjectState


@pytest.fixture
def section(qtbot: QtBot, tmp_path: Path) -> OpenMPSection:
    status = StatusLine()
    qtbot.addWidget(status)
    created = OpenMPSection(make_arguments(tmp_path), ProjectState(), status)
    qtbot.addWidget(created)
    return created


def recorded(section: OpenMPSection) -> List[object]:
    events: List[object] = []
    section.project_state.subscribe(ProjectDirectoriesChanged, events.append)
    return events


def test_the_warning_of_a_build_names_this_setting() -> None:
    # the build warnings say where the setting is: the card and the check box must carry those names
    assert openmp_section.TITLE in openmp_handling.GUI_LOCATION
    assert openmp_section.TEXT in openmp_handling.GUI_LOCATION
    assert "Project Setup" in openmp_handling.GUI_LOCATION


def test_the_flags_are_kept_by_default(section: OpenMPSection) -> None:
    assert not section.checkbox.isChecked()
    assert section.notice.isHidden()


def test_checking_it_stores_the_setting_and_publishes_the_change(section: OpenMPSection) -> None:
    changes = recorded(section)
    section.checkbox.setChecked(True)
    assert openmp_handling.load_openmp_handling(section.arguments.project_dir).strip is True
    assert len(changes) == 1
    section.checkbox.setChecked(False)
    assert openmp_handling.load_openmp_handling(section.arguments.project_dir).strip is False
    assert len(changes) == 2


def test_the_setting_is_read_again_when_changed_outside_the_gui(section: OpenMPSection) -> None:
    openmp_handling.save_openmp_handling(section.arguments.project_dir, openmp_handling.OpenMPHandling(strip=True))
    changes = recorded(section)
    section.reload()
    assert section.checkbox.isChecked()
    assert not changes  # showing it is no change


def test_the_command_line_option_is_named_while_it_overrides_the_setting(qtbot: QtBot, tmp_path: Path) -> None:
    status = StatusLine()
    qtbot.addWidget(status)
    arguments = make_arguments(tmp_path)
    arguments.strip_openmp = True
    created = OpenMPSection(arguments, ProjectState(), status)
    qtbot.addWidget(created)
    assert not created.notice.isHidden()
    assert "--strip-openmp" in created.notice.text_label.text() and "remove" in created.notice.text_label.text()
