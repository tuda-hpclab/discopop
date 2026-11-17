# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The "OpenMP flags" card of the Project Setup stage: the project setting of ``services/openmp_handling.py``, i.e.
whether the instrumented (dp / hd) compilations remove the OpenMP flags. The warnings of a build that kept them point
here, so the texts of :data:`TITLE` and :data:`TEXT` are the ones ``openmp_handling.GUI_LOCATION`` names."""

from typing import Optional

from PySide6.QtWidgets import QCheckBox, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import openmp_handling
from discopop_library.ProjectManager.services.project_state import (
    ConfigurationsChanged,
    ProjectDirectoriesChanged,
    ProjectState,
)

TITLE = "OpenMP flags"
TEXT = "Remove OpenMP flags"
HINT = (
    "Programs compiled with -fopenmp are profiled with their OpenMP pragmas active: the threads are instrumented as"
    " concurrent code, the dependences depend on the thread schedule and the pattern detection does not know that a"
    " loop is parallel already. Removing the flags from the instrumented (profiling and hotspot) builds profiles the"
    " sequential code instead; code that calls omp_* functions then needs #ifdef _OPENMP guards. Builds without"
    " OpenMP flags are not affected. Saved at once; takes effect with the next build."
)
OVERRIDDEN_TEXT = (
    "--strip-openmp / --no-strip-openmp overrides this setting for this invocation: the instrumented builds "
    "{state} the OpenMP flags."
)


class OpenMPSection(widgets.FormSection):
    """Edits ``.discopop/project/openmp_handling.json``; every change is stored at once and published like a change of
    the project directories (builds and profiling data compiled with the other setting are not current any more)."""

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(TITLE, parent)
        self.arguments = arguments
        self.project_state = project_state
        self.status = status
        self.checkbox = QCheckBox(TEXT)
        self.checkbox.setChecked(openmp_handling.load_openmp_handling(arguments.project_dir).strip)
        self.add_widget(self.checkbox, HINT)
        self.notice = widgets.WarningBanner()
        self.add_widget(self.notice)
        self.checkbox.toggled.connect(lambda _checked: self._changed())
        self._refresh_notice()

    def _changed(self) -> None:
        handling = openmp_handling.OpenMPHandling(strip=self.checkbox.isChecked())
        if handling == openmp_handling.load_openmp_handling(self.arguments.project_dir):
            return
        try:
            openmp_handling.save_openmp_handling(self.arguments.project_dir, handling)
        except OSError as error:
            self.status.set("Cannot save the OpenMP setting: " + str(error), widgets.STATUS_FAIL)
            return
        self.status.set(
            "OpenMP flags are " + ("removed from" if handling.strip else "kept in") + " the instrumented builds",
            widgets.STATUS_OK,
            reset_ms=3000,
        )
        self._refresh_notice()
        self.project_state.publish(ConfigurationsChanged())
        self.project_state.publish(ProjectDirectoriesChanged())

    def reload(self) -> None:
        """Show the stored setting (it may have been changed outside the GUI) without storing it again."""
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(openmp_handling.load_openmp_handling(self.arguments.project_dir).strip)
        self.checkbox.blockSignals(False)
        self._refresh_notice()

    def _refresh_notice(self) -> None:
        """The command line option of this invocation wins over the check box."""
        override = self.arguments.strip_openmp
        if override is None:
            self.notice.setVisible(False)
            return
        self.notice.set_message(TITLE, OVERRIDDEN_TEXT.format(state="remove" if override else "keep"))
        self.notice.setVisible(True)
