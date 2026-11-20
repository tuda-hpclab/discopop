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

from discopop_library.ProjectManager.qt_gui.fingerprint_ignore_section import FingerprintIgnoreSection
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.fingerprint_ignore import add_patterns, load_fingerprint_ignore
from discopop_library.ProjectManager.services.project_state import ProjectState, ResultsChanged


@pytest.fixture
def section(qtbot: QtBot, tmp_path: Path) -> FingerprintIgnoreSection:
    status = StatusLine()
    qtbot.addWidget(status)
    created = FingerprintIgnoreSection(make_arguments(tmp_path), ProjectState(), status)
    qtbot.addWidget(created)
    return created


def test_saving_stores_the_patterns_and_tells_the_panels(section: FingerprintIgnoreSection) -> None:
    events: List[object] = []
    section.project_state.subscribe(ResultsChanged, events.append)
    section.editor.setPlainText("./dp_build/\n\n*.log\n")
    section.save_button.click()
    assert load_fingerprint_ignore(section.arguments.project_dir) == ["dp_build/", "*.log"]
    assert section.editor.toPlainText() == "dp_build/\n*.log"
    assert len(events) == 1


def test_an_invalid_pattern_is_not_saved(section: FingerprintIgnoreSection) -> None:
    section.editor.setPlainText("dp_build/\n../outside\n")
    section.save_button.click()
    assert load_fingerprint_ignore(section.arguments.project_dir) == []


def test_patterns_added_elsewhere_are_shown_unless_edits_are_pending(section: FingerprintIgnoreSection) -> None:
    add_patterns(section.arguments.project_dir, ["dp_build/"])
    section.project_state.publish(ResultsChanged())
    assert section.editor.toPlainText() == "dp_build/"
    section.editor.document().setModified(True)
    add_patterns(section.arguments.project_dir, ["out/"])
    section.project_state.publish(ResultsChanged())
    assert section.editor.toPlainText() == "dp_build/"
