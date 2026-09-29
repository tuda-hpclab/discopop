# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Styling configuration for the *custom* (canvas-drawn) GUI components.

This module is the single place to tweak the appearance of widgets that ttk
cannot style directly -- currently the rounded :class:`RoundedButton`
(``rounded_button.py``). Standard ttk widgets are themed in
``ConfigManagerApp._setup_styles`` and the shared color/font tokens live in
``widgets.py``; this file is intentionally kept dependency-free (it imports
nothing from the rest of the GUI) so it can act as the low-level style
definition that both the widgets and the app build on top of.

To restyle the buttons, edit the values in :data:`BUTTON_STYLES`. To add a new
custom element later, define an analogous frozen dataclass plus a
``{variant: style}`` registry in the "Future custom elements" section at the
bottom, following the button example.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, Tuple, Union

# ---------------------------------------------------------------------------
# Shared color tokens for the custom widgets
# ---------------------------------------------------------------------------
# These mirror the semantic status colors used elsewhere in the GUI
# (see widgets.STATUS_*) so the custom buttons stay visually
# consistent with the rest of the light theme. They are duplicated here rather
# than imported to keep this module free of GUI dependencies.
_TEXT_ON_COLOR = "white"
_DISABLED_BG = "#d0d0d0"
_DISABLED_FG = "#7a7a7a"
_FOCUS_RING = "#1e1e2e"  # dark ring, readable on every colored variant

# Default proportional UI font for button labels. Use the named default font
# directly (rather than a (family, size) tuple) so the labels match the size of
# the rest of the GUI / the previous ttk buttons on every display, including
# HiDPI ones. A font spec may be a named-font string, a (family, size) tuple or
# a (family, size, style) tuple.
_FontSpec = Union[str, Tuple[Any, ...]]
_BUTTON_FONT: _FontSpec = "TkDefaultFont"


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ButtonStyle:
    """Visual definition of a single rounded-button variant.

    All colors are Tk color strings (``"#rrggbb"`` or a named color). Geometry
    values are in pixels. Instances are immutable; use :meth:`with_overrides`
    (``dataclasses.replace``) to derive a tweaked copy.
    """

    bg: str  # resting background fill
    hover_bg: str  # background while the pointer is over the button
    fg: str = _TEXT_ON_COLOR  # label color
    disabled_bg: str = _DISABLED_BG
    disabled_fg: str = _DISABLED_FG
    focus_color: str = _FOCUS_RING  # keyboard-focus ring color
    radius: int = 16  # corner radius
    pad_x: int = 14  # horizontal text padding
    pad_y: int = 6  # vertical text padding
    font: _FontSpec = _BUTTON_FONT

    def with_overrides(self, **changes: object) -> "ButtonStyle":
        """Return a copy of this style with the given fields replaced."""
        return replace(self, **changes)  # type: ignore[arg-type]


# The registry of named button variants. Call sites select a variant by name
# (see widgets.create_button / primary_button / danger_button / success_button).
# Edit the colors/geometry here to restyle every button of that variant at once.
# Nord palette (https://www.nordtheme.com/): a muted, arctic color scheme.
# "Polar Night" for the neutral action, "Frost" blue for the primary, and the
# softer "Aurora" green/red for success/danger. The green fill is light enough
# that it uses dark ("#2e3440", Nord's darkest) text instead of white.
BUTTON_STYLES: Dict[str, ButtonStyle] = {
    # Neutral / secondary actions (Cancel, Back, Help, Close, ...).
    "default": ButtonStyle(bg="#4c566a", hover_bg="#434c5e"),
    # Primary / affirmative actions (Run, Save, Next, Apply, ...).
    "primary": ButtonStyle(bg="#5e81ac", hover_bg="#4c6f9c"),
    # Successful / completed state (green) -- dark text on the soft green fill.
    "success": ButtonStyle(bg="#a3be8c", hover_bg="#8faa78", fg="#2e3440"),
    # Destructive or interrupting actions (Reset, Delete, Stop).
    "danger": ButtonStyle(bg="#bf616a", hover_bg="#a5545c"),
}

DEFAULT_VARIANT = "default"


def get_button_style(variant: str = DEFAULT_VARIANT) -> ButtonStyle:
    """Look up a :class:`ButtonStyle` by variant name.

    Unknown variant names fall back to the ``default`` variant so a typo at a
    call site degrades gracefully instead of raising.
    """
    return BUTTON_STYLES.get(variant, BUTTON_STYLES[DEFAULT_VARIANT])


# ---------------------------------------------------------------------------
# Future custom elements
# ---------------------------------------------------------------------------
# When adding another hand-drawn widget (e.g. a rounded card, a toggle switch,
# a badge), define its style here following the button example above:
#
#   @dataclass(frozen=True)
#   class CardStyle:
#       bg: str
#       border: str
#       radius: int = 10
#
#   CARD_STYLES: Dict[str, CardStyle] = {"default": CardStyle(bg="#ffffff", border="#e0e0e0")}
#
# Keeping every custom-widget style in this one module means the whole
# non-ttk look of the GUI can be adjusted from a single place.
