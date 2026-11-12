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
from PySide6.QtWidgets import QApplication

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
    QPalette.ColorRole.PlaceholderText: "#9a9a9a",
}
_DISABLED_TEXT = "#7a7a7a"

# the light theme: gray pages, off-white views and input fields, frames and hint texts dark enough to read (Fusion's
# standard palette has white views on an almost white window, with faint frames); the hint texts (captions, empty
# views, idle status lines) are drawn in the placeholder color
_LIGHT_COLORS: Dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.Window: "#e4e6e9",
    QPalette.ColorRole.WindowText: "#1b1d21",
    QPalette.ColorRole.Base: "#f7f8fa",
    QPalette.ColorRole.AlternateBase: "#eceef1",
    QPalette.ColorRole.Text: "#1b1d21",
    QPalette.ColorRole.Button: "#e3e5e8",
    QPalette.ColorRole.ButtonText: "#1b1d21",
    QPalette.ColorRole.BrightText: "#ffffff",
    QPalette.ColorRole.Highlight: "#2f6fdb",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.Link: "#1f5fc4",
    QPalette.ColorRole.Mid: "#a3a7ad",
    QPalette.ColorRole.Midlight: "#c6c9ce",
    QPalette.ColorRole.Dark: "#8a8e94",
    QPalette.ColorRole.Shadow: "#5a5d61",
    QPalette.ColorRole.Light: "#ffffff",
    QPalette.ColorRole.ToolTipBase: "#ffffe1",
    QPalette.ColorRole.ToolTipText: "#1b1d21",
    QPalette.ColorRole.PlaceholderText: "#62666d",
}
_LIGHT_DISABLED_TEXT = "#8c9096"


def _qsettings() -> QSettings:
    return QSettings("DiscoPoP", "ProjectManager")


# where the choice is stored; the tests replace it by settings in a temporary file
settings_factory: Callable[[], QSettings] = _qsettings

# the desktop's palette, remembered before the first theme replaced it
_system_palette: Optional[QPalette] = None
_current = THEME_SYSTEM


def _palette(colors: Dict[QPalette.ColorRole, str], disabled_text: str) -> QPalette:
    palette = QPalette()
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled_text))
    return palette


def dark_palette() -> QPalette:
    return _palette(_DARK_COLORS, _DISABLED_TEXT)


def light_palette() -> QPalette:
    return _palette(_LIGHT_COLORS, _LIGHT_DISABLED_TEXT)


def system_palette(app: QApplication) -> QPalette:
    global _system_palette
    if _system_palette is None:
        _system_palette = QPalette(app.palette())
    return QPalette(_system_palette)


def palette_for(app: QApplication, theme: str) -> QPalette:
    """The palette of ``theme``: Light is always the one of this application (a light desktop palette is often too
    faint); Dark keeps the desktop's palette when it already is dark."""
    system = system_palette(app)
    if theme == THEME_LIGHT:
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
