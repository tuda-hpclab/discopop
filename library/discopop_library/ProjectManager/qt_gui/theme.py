# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The color theme of the Qt GUI: the desktop's palette (System), or a light or dark one chosen by the user.

The style sheet of the application is derived from the palette (:func:`widgets.app_style_sheet`), and the widgets
that draw themselves (the workflow sidebar) read the palette when they paint, so switching the palette and the style
sheet switches the whole window; the charts stay light. The choice is kept in the user's Qt settings.
"""

from typing import Callable, Dict, Optional

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from discopop_library.ProjectManager.qt_gui import widgets

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)
THEME_TITLES = {THEME_SYSTEM: "System", THEME_LIGHT: "Light", THEME_DARK: "Dark"}

_SETTINGS_KEY = "appearance/theme"

_DARK_COLORS: Dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.Window: "#2b2b2b",
    QPalette.ColorRole.WindowText: "#e6e6e6",
    QPalette.ColorRole.Base: "#1f1f1f",
    QPalette.ColorRole.AlternateBase: "#262626",
    QPalette.ColorRole.Text: "#e6e6e6",
    QPalette.ColorRole.Button: "#353535",
    QPalette.ColorRole.ButtonText: "#e6e6e6",
    QPalette.ColorRole.BrightText: "#ffffff",
    QPalette.ColorRole.Highlight: "#2f6fdb",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.Link: "#6ea8ff",
    QPalette.ColorRole.Mid: "#5a5a5a",
    QPalette.ColorRole.Midlight: "#444444",
    QPalette.ColorRole.Dark: "#1a1a1a",
    QPalette.ColorRole.Shadow: "#101010",
    QPalette.ColorRole.Light: "#505050",
    QPalette.ColorRole.ToolTipBase: "#353535",
    QPalette.ColorRole.ToolTipText: "#e6e6e6",
    QPalette.ColorRole.PlaceholderText: "#8a8a8a",
}
_DISABLED_TEXT = "#7a7a7a"


def _qsettings() -> QSettings:
    return QSettings("DiscoPoP", "ProjectManager")


# where the choice is stored; the tests replace it by settings in a temporary file
settings_factory: Callable[[], QSettings] = _qsettings

# the desktop's palette, remembered before the first theme replaced it
_system_palette: Optional[QPalette] = None
_current = THEME_SYSTEM


def dark_palette() -> QPalette:
    palette = QPalette()
    for role, color in _DARK_COLORS.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(_DISABLED_TEXT))
    return palette


def light_palette() -> QPalette:
    style = QStyleFactory.create("Fusion")
    return style.standardPalette() if style is not None else QPalette(QColor("#efefef"))


def system_palette(app: QApplication) -> QPalette:
    global _system_palette
    if _system_palette is None:
        _system_palette = QPalette(app.palette())
    return QPalette(_system_palette)


def palette_for(app: QApplication, theme: str) -> QPalette:
    """The palette of ``theme``; Light and Dark keep the desktop's palette when it already is light resp. dark."""
    system = system_palette(app)
    if theme == THEME_LIGHT and widgets.is_dark(system):
        return light_palette()
    if theme == THEME_DARK and not widgets.is_dark(system):
        return dark_palette()
    return system


def current_theme() -> str:
    return _current


def apply_theme(app: QApplication, theme: str) -> None:
    """Switch the palette and the style sheet derived from it."""
    global _current
    if theme not in THEMES:
        theme = THEME_SYSTEM
    palette = palette_for(app, theme)
    app.setPalette(palette)
    app.setStyleSheet(widgets.app_style_sheet(palette))
    _current = theme


def saved_theme() -> str:
    value = settings_factory().value(_SETTINGS_KEY, THEME_SYSTEM)
    return value if isinstance(value, str) and value in THEMES else THEME_SYSTEM


def set_theme(app: QApplication, theme: str) -> None:
    """Apply ``theme`` and remember it for the next start."""
    apply_theme(app, theme)
    settings = settings_factory()
    settings.setValue(_SETTINGS_KEY, current_theme())
    settings.sync()


def apply_saved_theme(app: QApplication) -> None:
    apply_theme(app, saved_theme())
