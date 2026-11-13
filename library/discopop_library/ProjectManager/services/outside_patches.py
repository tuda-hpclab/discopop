# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Suggestions that patch files outside of the project, for the Execute stage of a GUI.

The classification itself is in :mod:`discopop_library.PatchApplicator.outside_project`; this module adds what a
panel needs around it: the suggestions of a manual selection that are affected, and the text of the separate
confirmation that has to be given before they are applied. No GUI toolkit is imported; the panel only shows the text.
"""

from typing import Dict, Iterable, List

from discopop_library.PatchApplicator.outside_project import find_outside_project_targets

CONFIRMATION_TITLE = "Files outside the project"

# the files are listed up to this number per message; the rest is counted
_MAX_LISTED_FILES = 12


def outside_project_suggestions(dot_dp: str, suggestion_ids: Iterable[str]) -> Dict[str, List[str]]:
    """The suggestions of ``suggestion_ids`` that patch files outside of the project of ``dot_dp``, with those files."""
    return find_outside_project_targets(dot_dp, list(suggestion_ids))


def confirmation_text(outside: Dict[str, List[str]]) -> str:
    """The question of the confirmation for applying suggestions with targets outside the project."""
    files = sorted({path for targets in outside.values() for path in targets})
    listed = "\n".join("    " + path for path in files[:_MAX_LISTED_FILES])
    if len(files) > _MAX_LISTED_FILES:
        listed += f"\n    ... and {len(files) - _MAX_LISTED_FILES} more"
    suggestions = ", ".join(sorted(outside, key=lambda suggestion_id: (len(suggestion_id), suggestion_id)))
    return (
        f"The selected suggestion(s) {suggestions} patch files that lie OUTSIDE the project:\n\n"
        f"{listed}\n\n"
        "These files are modified in place, not in a copy of the project, and other projects may use them. "
        "They are restored after the run (also when it fails or is stopped).\n\n"
        "Do you want to apply these suggestions?"
    )
