# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The color theme: System / Light / Dark from the "⋯" menu of the header bar, remembered between starts."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import theme, widgets
from discopop_library.ProjectManager.qt_gui.main_window import MainWindow
from discopop_library.ProjectManager.qt_gui.testing import make_arguments


def test_the_menu_switches_and_remembers_the_theme(qtbot: QtBot, tmp_path: Path, qapp: QApplication) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    system_dark = widgets.is_dark(qapp.palette())
    menu = window.config_list.menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()][-1] == "Theme"
    assert [a.text() for a in window.theme_menu.actions()] == ["System", "Light", "Dark"]
    assert window.theme_actions[theme.THEME_SYSTEM].isChecked()

    window.theme_actions[theme.THEME_DARK].trigger()
    assert widgets.is_dark(qapp.palette()) and window.theme_actions[theme.THEME_DARK].isChecked()
    assert widgets.chrome_color(qapp.palette()).name() in qapp.styleSheet()
    assert theme.saved_theme() == theme.THEME_DARK

    window.theme_actions[theme.THEME_LIGHT].trigger()
    assert not widgets.is_dark(qapp.palette()) and theme.saved_theme() == theme.THEME_LIGHT
    assert not window.theme_actions[theme.THEME_DARK].isChecked()

    window.theme_actions[theme.THEME_SYSTEM].trigger()
    assert widgets.is_dark(qapp.palette()) == system_dark and theme.saved_theme() == theme.THEME_SYSTEM


def test_the_saved_theme_is_applied_at_start(qapp: QApplication) -> None:
    theme.set_theme(qapp, theme.THEME_DARK)
    theme.apply_theme(qapp, theme.THEME_SYSTEM)
    theme.apply_saved_theme(qapp)
    assert theme.current_theme() == theme.THEME_DARK and widgets.is_dark(qapp.palette())


def test_an_unknown_saved_theme_falls_back_to_the_system(qapp: QApplication) -> None:
    settings = theme.settings_factory()
    settings.setValue("appearance/theme", "purple")
    settings.sync()
    assert theme.saved_theme() == theme.THEME_SYSTEM


def test_default_buttons_stand_out_from_the_window() -> None:
    for window_color, text_color in (("#efefef", "#000000"), ("#2b2b2b", "#e6e6e6")):
        palette = QPalette(QColor(window_color))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(text_color))
        background, border, _hover, _pressed = widgets.button_colors(palette)
        window = palette.color(QPalette.ColorRole.Window)
        # the border is clearly apart from the window, and the button is lifted from it
        assert abs(border.lightness() - window.lightness()) >= 50
        assert background.lightness() > window.lightness()
        assert f"border: 1px solid {border.name()}" in widgets.app_style_sheet(palette)
