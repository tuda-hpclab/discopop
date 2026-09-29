# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Whether a window can be opened on this host, and a fail-fast guard.

Deliberately free of tkinter: the check has to survive -- and be testable on --
a host where importing the GUI itself would already fail.
"""

import os
import sys

# Platforms whose GUI does not go through an X / Wayland display server.
_NATIVE_DISPLAY_PLATFORMS = ("darwin", "win32")

NO_DISPLAY_MESSAGE = (
    "ERROR: this command opens a graphical window, but no display is available "
    "(neither $DISPLAY nor $WAYLAND_DISPLAY is set).\n"
    "-> For non-interactive use, see: discopop_project_manager --help"
)


def have_display() -> bool:
    """Whether a graphical window can be shown here."""
    if sys.platform in _NATIVE_DISPLAY_PLATFORMS:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def require_display() -> None:
    """Exit with a readable message where no window can be shown.

    Without it, a GUI command reached from a script, a CI job or an agent dies
    with a raw TclError out of the depths of the tkinter import -- or, on a host
    that has no GUI extras installed at all, with an ImportError naming a module
    the caller never asked for.
    """
    if have_display():
        return
    print(NO_DISPLAY_MESSAGE, file=sys.stderr)
    sys.exit(1)
