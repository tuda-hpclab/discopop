# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.build_thread_count_section import BuildThreadCountSection
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import build_thread_count


@pytest.fixture
def section(qtbot: QtBot, tmp_path: Path) -> BuildThreadCountSection:
    status = StatusLine()
    qtbot.addWidget(status)
    created = BuildThreadCountSection(make_arguments(tmp_path), status)
    qtbot.addWidget(created)
    return created


def test_it_is_off_by_default_without_notice(section: BuildThreadCountSection) -> None:
    assert not section.checkbox.isChecked()
    assert section.notice.isHidden()


def test_toggling_saves_the_setting_at_once(section: BuildThreadCountSection) -> None:
    section.checkbox.setChecked(True)
    assert build_thread_count.load_build_thread_count(section.arguments.project_dir).pass_to_builds
    section.checkbox.setChecked(False)
    assert not build_thread_count.load_build_thread_count(section.arguments.project_dir).pass_to_builds


def test_reload_shows_a_change_made_outside_without_storing_it_again(section: BuildThreadCountSection) -> None:
    build_thread_count.save_build_thread_count(
        section.arguments.project_dir, build_thread_count.BuildThreadCount(pass_to_builds=True)
    )
    path = Path(build_thread_count.build_thread_count_path(section.arguments.project_dir))
    mtime = path.stat().st_mtime_ns
    section.reload()
    assert section.checkbox.isChecked()
    assert path.stat().st_mtime_ns == mtime


def test_the_command_line_option_is_announced(qtbot: QtBot, tmp_path: Path) -> None:
    arguments = make_arguments(tmp_path)
    arguments.build_thread_count = True
    status = StatusLine()
    qtbot.addWidget(status)
    created = BuildThreadCountSection(arguments, status)
    qtbot.addWidget(created)
    assert not created.notice.isHidden()
    assert "do not get" not in created.notice.text_label.text()
