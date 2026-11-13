# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The color theme: System / Light / Dark from the menu at the bottom of the sidebar, remembered between starts."""

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
    assert window.theme_button.menu() is window.theme_menu and "Theme" not in window.config_list.menu_actions()
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


def test_the_clear_button_of_the_output_pane_is_framed(qtbot: QtBot) -> None:
    from discopop_library.ProjectManager.qt_gui.output_pane import OutputPane

    pane = OutputPane()
    qtbot.addWidget(pane)
    # a flat button has no frame and read as a label
    assert pane.clear_button.objectName() == widgets.COMPACT_NAME != widgets.FLAT_NAME
    assert f"QPushButton#{widgets.COMPACT_NAME} {{ padding:" in widgets.app_style_sheet(QPalette(QColor("#efefef")))


def test_the_light_theme_has_no_white_views_and_readable_hints(qapp: QApplication) -> None:
    palette = theme.palette_for(qapp, theme.THEME_LIGHT)
    window = palette.color(QPalette.ColorRole.Window)
    card = widgets.card_color(palette)
    hint = palette.color(QPalette.ColorRole.PlaceholderText)
    assert not widgets.is_dark(palette)
    # views, cards and the page are off-white, a card stands apart from the page
    assert QColor("#ffffff") not in (window, card, palette.color(QPalette.ColorRole.Base))
    assert card.lightness() > window.lightness()
    # hint texts read on the page and on a card (WCAG AA for normal text)
    assert widgets.contrast_ratio(hint, window) >= 4.5 and widgets.contrast_ratio(hint, card) >= 4.5


def test_idle_labels_take_the_hint_color_of_the_palette(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLabel

    label = QLabel("Ready")
    qtbot.addWidget(label)
    widgets.set_label_color(label, widgets.STATUS_IDLE)
    assert label.styleSheet() == f"color: {widgets.HINT_COLOR};"


def test_a_checked_box_is_filled_in_the_accent(qtbot: QtBot, qapp: QApplication) -> None:
    from PySide6.QtWidgets import QCheckBox

    from discopop_library.ProjectManager.qt_gui.app import create_application

    create_application()
    theme.apply_theme(qapp, theme.THEME_LIGHT)
    box = QCheckBox("x")
    qtbot.addWidget(box)
    box.setChecked(True)
    box.show()
    image = box.grab().toImage()
    colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}
    assert widgets.ACCENT in colors


def test_the_arrows_of_spin_and_combo_boxes_are_images(qapp: QApplication) -> None:
    from pathlib import Path as FilePath

    import re

    path = widgets.arrow_image("down", "#123456")
    assert FilePath(path).read_text().count("#123456") == 1
    # the style sheet names an arrow image that exists
    match = re.search(
        r"QComboBox::down-arrow \{ image: url\('([^']+)'\)", widgets.app_style_sheet(theme.light_palette())
    )
    assert match is not None and FilePath(match.group(1)).is_file()


def test_accent_text_and_marks_read_on_any_highlight() -> None:
    # e.g. a desktop palette with a light blue (KDE Breeze) or a pastel highlight
    for highlight in ("#3daee9", "#ffe082", widgets.ACCENT):
        palette = theme.light_palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
        text = widgets.accent_text_color(palette)
        assert widgets.contrast_ratio(text, widgets.selection_color(palette)) >= 4.5
        mark = widgets.mark_color(QColor(highlight))
        assert widgets.contrast_ratio(mark, QColor(highlight)) >= 3
