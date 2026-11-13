# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The base class of the panels (the tabs of the main window).

A panel owns its widgets. It gets what it shares with the others in its constructor -- the arguments, the
:class:`ProjectState` and the status line -- and talks to other panels only through ``ProjectState`` events or
callbacks the main window passes in, never through attributes of the main window.
"""

from typing import Optional, Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui.widgets import OutputConsole
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services.project_state import ProjectState


class TabHost(Protocol):
    """What a panel may do with the tabs of the main window; tabs are named by the ``TAB_*`` constants."""

    def show_tab(self, name: str) -> None:
        """Bring tab ``name`` to the front."""

    def current_tab(self) -> str:
        """The name of the tab in front."""
        ...

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        """Enable or disable tab ``name``; ``tooltip`` explains a disabled tab."""

    def set_tab_title(self, name: str, title: str) -> None:
        """Show ``title`` on tab ``name`` (e.g. "Editor *" for unsaved changes)."""


class Panel(QWidget):
    """A panel of the main window.

    A panel with output creates its :class:`OutputConsole` with :meth:`make_console` (a hidden child it does not lay
    out) and returns it from :meth:`output_console`; the main window shows it in the output dock below the panels (under
    :attr:`output_title`). A panel emits :attr:`output_requested` when it starts a job, so the dock opens on its
    console.
    """

    output_title = ""
    output_requested = Signal()

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.arguments = arguments
        self.project_state = project_state
        self.status = status

    def make_console(self) -> OutputConsole:
        """A console for the output pane: a hidden child until the main window moves it into the pane.

        Hidden, so that it is not drawn over the panel's widgets when there is no main window (unit tests).
        """
        console = OutputConsole(self)
        console.hide()
        return console

    def output_console(self) -> Optional[OutputConsole]:
        """The console of this panel for the output dock, or None if it has none."""
        return None

    def cancel_jobs(self) -> None:
        """Stop the background jobs of this panel; called when the window closes."""
