# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The drag handle below boxes that the user can make taller."""

import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QListWidget

from discopop_library.ProjectManager.qt_gui import widgets

pytestmark = pytest.mark.qt


def test_minimum_mode_keeps_the_box_growable(qtbot: QtBot) -> None:
    box = QListWidget()
    container = widgets.resizable(box, 100, minimum=50)
    qtbot.addWidget(container)
    assert box.minimumHeight() == 100
    assert box.maximumHeight() > 10_000
    handle = container.resize_handle
    handle.set_target_height(220)
    assert box.minimumHeight() == 220
    handle.set_target_height(10)
    assert box.minimumHeight() == 50


def test_fixed_mode_sets_the_exact_height(qtbot: QtBot) -> None:
    box = QListWidget()
    container = widgets.resizable(box, 90, minimum=40, fixed=True)
    qtbot.addWidget(container)
    assert (box.minimumHeight(), box.maximumHeight()) == (90, 90)
    container.resize_handle.set_target_height(150)
    assert (box.minimumHeight(), box.maximumHeight()) == (150, 150)


def test_reset_returns_to_the_initial_height(qtbot: QtBot) -> None:
    box = QListWidget()
    container = widgets.resizable(box, 100, minimum=50)
    qtbot.addWidget(container)
    container.resize_handle.set_target_height(300)
    container.resize_handle.reset()
    assert box.minimumHeight() == 100
