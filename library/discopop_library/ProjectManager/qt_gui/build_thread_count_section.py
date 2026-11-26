# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The "Thread count in builds" card of the Build stage: the project setting of ``services/build_thread_count.py``."""

from typing import Optional

from PySide6.QtWidgets import QCheckBox, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import build_thread_count

TITLE = "Thread count in builds"
TEXT = "Pass the thread count to compile scripts (OMP_NUM_THREADS)"
HINT = (
    "Off by default: compile scripts do not get OMP_NUM_THREADS from the project manager, so that $(nproc) in a"
    " script like make -j $(nproc) returns the number of CPUs. When on, $(nproc) returns the thread count of the"
    " run (e.g. 8 for a par run with 8 threads). execute.sh and validate.sh always get it. Saved at once; no"
    " build becomes stale."
)
OVERRIDDEN_TEXT = (
    "--build-thread-count / --no-build-thread-count overrides this setting for this invocation: the compile scripts "
    "{state} the thread count."
)


class BuildThreadCountSection(widgets.FormSection):
    """Edits ``.discopop/project/build_thread_count.json``; every change is stored at once. The setting is no part of
    the build fingerprint, so nothing is published."""

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(TITLE, parent)
        self.arguments = arguments
        self.status = status
        self.checkbox = QCheckBox(TEXT)
        self.checkbox.setChecked(build_thread_count.load_build_thread_count(arguments.project_dir).pass_to_builds)
        self.add_widget(self.checkbox, HINT)
        self.notice = widgets.WarningBanner()
        self.add_widget(self.notice)
        self.checkbox.toggled.connect(lambda _checked: self._changed())
        self._refresh_notice()

    def _changed(self) -> None:
        setting = build_thread_count.BuildThreadCount(pass_to_builds=self.checkbox.isChecked())
        if setting == build_thread_count.load_build_thread_count(self.arguments.project_dir):
            return
        try:
            build_thread_count.save_build_thread_count(self.arguments.project_dir, setting)
        except OSError as error:
            self.status.set("Cannot save the thread count setting: " + str(error), widgets.STATUS_FAIL)
            return
        self.status.set(
            "Compile scripts " + ("get" if setting.pass_to_builds else "do not get") + " the thread count",
            widgets.STATUS_OK,
            reset_ms=3000,
        )

    def reload(self) -> None:
        """Show the stored setting (it may have been changed outside the GUI) without storing it again."""
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(build_thread_count.load_build_thread_count(self.arguments.project_dir).pass_to_builds)
        self.checkbox.blockSignals(False)
        self._refresh_notice()

    def _refresh_notice(self) -> None:
        """The command line option of this invocation wins over the check box."""
        override = self.arguments.build_thread_count
        if override is None:
            self.notice.setVisible(False)
            return
        self.notice.set_message(TITLE, OVERRIDDEN_TEXT.format(state="get" if override else "do not get"))
        self.notice.setVisible(True)
