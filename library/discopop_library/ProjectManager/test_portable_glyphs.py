# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The texts of the GUIs use only symbols that every host can draw.

The GUI draws its text with the fonts of the host it runs on, which over X forwarding is the remote host. Emoji (a
lock, an hourglass), full-width forms and rare math symbols are only drawn there if an emoji or CJK font is
installed, otherwise they show as empty boxes. The characters allowed below are all in DejaVu Sans, the fallback
font of most Linux installations, and in the system fonts of macOS and Windows. A symbol that is not in that font
is drawn with QPainter instead (as the badges of the workflow sidebar).
"""

import tokenize
from pathlib import Path
from typing import Dict, Set

import pytest

_ROOT = Path(__file__).parent
# the code whose strings end up on the screen: both GUIs and what they show of the services and the charts
_DIRECTORIES = ["gui", "qt_gui", "services", "plots"]

_ALLOWED = set(
    "×"  # U+00D7
    "—“”•…"  # U+2014, U+201C, U+201D, U+2022, U+2026
    "→∞⋯"  # U+2192, U+221E, U+22EF
    "■▶▸▼▾◂○●◐"  # U+25A0, U+25B6, U+25B8, U+25BC, U+25BE, U+25C2, U+25CB, U+25CF, U+25D0
    "⚠✓✕✗⟳"  # U+26A0, U+2713, U+2715, U+2717, U+27F3
)

_STRING_TOKENS = {tokenize.STRING} | (
    {getattr(tokenize, "FSTRING_MIDDLE")} if hasattr(tokenize, "FSTRING_MIDDLE") else set()
)


def _sources() -> list[Path]:
    return sorted(
        path
        for directory in _DIRECTORIES
        for path in (_ROOT / directory).rglob("*.py")
        if not path.name.startswith("test_") and path.name != "conftest.py"
    )


def _characters_in_strings(path: Path) -> Dict[str, Set[int]]:
    """The non-ASCII characters of the string literals in ``path`` (comments do not reach the screen), with lines."""
    found: Dict[str, Set[int]] = {}
    with path.open("rb") as source:
        for token in tokenize.tokenize(source.readline):
            if token.type in _STRING_TOKENS:
                for offset, line in enumerate(token.string.split("\n")):
                    for character in line:
                        if ord(character) > 127:
                            found.setdefault(character, set()).add(token.start[0] + offset)
    return found


def test_sources_are_found() -> None:
    assert len(_sources()) > 20


@pytest.mark.parametrize("path", _sources(), ids=lambda path: str(path.relative_to(_ROOT)))
def test_only_portable_symbols_in_texts(path: Path) -> None:
    offending = {
        f"U+{ord(character):04X} {character!r} (line {', '.join(map(str, sorted(lines)))})"
        for character, lines in _characters_in_strings(path).items()
        if character not in _ALLOWED
    }
    assert (
        not offending
    ), "symbols that hosts without an emoji / CJK font cannot draw (see the docstring of this test): " + "; ".join(
        sorted(offending)
    )
