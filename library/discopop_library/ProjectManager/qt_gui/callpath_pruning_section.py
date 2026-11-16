# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The "Call path pruning" card of the Build stage: the project setting of ``services/callpath_pruning.py``, its
parameters and the notice that current hotspot results exist while pruning is off (or are missing while it is on)."""

from typing import Optional

from PySide6.QtWidgets import QCheckBox, QComboBox, QSpinBox, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import callpath_pruning
from discopop_library.ProjectManager.services.project_state import (
    CallpathPruningChanged,
    ConfigChanged,
    HotspotsChanged,
    ProjectDirectoriesChanged,
    ProjectState,
)

TITLE = "Call path pruning"
TEXT = "Prune the call path states with the hotspot detection results"
HINT = (
    "The profiling build folds the call path states of functions that are neither hot nor lead to a hot function"
    " into the state of their caller: faster profiling and smaller data, with the call paths of the hot code kept."
    " Needs current hotspot detection results (Hotspot Detection stage). Applies to the mode dp. Saved at once;"
    " takes effect with the next profiling build."
)
INACTIVE_TOOLTIP = "Call path pruning only applies to the mode dp; select it above to change the setting."
DEPTH_HINT = "Calls below a hot function whose call paths are kept."
UNCLASSIFIED_HINT = (
    "Functions the hotspot detection did not classify: keep their call paths or fold them into the caller."
)


class CallpathPruningSection(widgets.FormSection):
    """Edits ``.discopop/project/callpath_pruning.json``; every change is stored at once and published as
    ``CallpathPruningChanged``."""

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
        self._active = True
        stored = callpath_pruning.load_callpath_pruning(arguments.project_dir)
        self.checkbox = QCheckBox(TEXT)
        self.checkbox.setChecked(stored.enabled)
        self.add_widget(self.checkbox, HINT)
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(0, callpath_pruning.MAX_HOT_DEPTH)
        self.depth_spin.setValue(stored.hot_depth)
        self.add_row("Depth below hot functions", self.depth_spin, DEPTH_HINT)
        self.unclassified = QComboBox()
        self.unclassified.addItems(callpath_pruning.UNCLASSIFIED_CHOICES)
        self.unclassified.setCurrentText(stored.unclassified)
        self.add_row("Unclassified functions", self.unclassified, UNCLASSIFIED_HINT)
        self.notice = widgets.WarningBanner()
        self.add_widget(self.notice)
        self.checkbox.toggled.connect(lambda _checked: self._changed())
        # a value is stored when the entry is finished, not with every key stroke
        self.depth_spin.editingFinished.connect(self._changed)
        self.unclassified.currentTextChanged.connect(lambda _text: self._changed())
        for event_type in (HotspotsChanged, ProjectDirectoriesChanged, ConfigChanged):
            project_state.subscribe(event_type, lambda _event: self.refresh_notice())
        self.refresh_notice()

    def set_active(self, active: bool) -> None:
        """Only the mode dp prunes: for the others the section is collapsed to its title and disabled."""
        self._active = active
        for row in range(self.form.rowCount()):
            self.form.setRowVisible(row, active)
        self.setEnabled(active)
        self.setToolTip("" if active else INACTIVE_TOOLTIP)
        self.refresh_notice()

    def _changed(self) -> None:
        before = callpath_pruning.load_callpath_pruning(self.arguments.project_dir)
        pruning = callpath_pruning.CallpathPruning(
            enabled=self.checkbox.isChecked(),
            hot_depth=self.depth_spin.value(),
            unclassified=self.unclassified.currentText(),
            seeds=before.seeds,
            hotness=before.hotness,
        )
        if pruning == before:
            return
        try:
            callpath_pruning.save_callpath_pruning(self.arguments.project_dir, pruning)
        except OSError as error:
            self.status.set("Cannot save the call path pruning setting: " + str(error), widgets.STATUS_FAIL)
            return
        if pruning.enabled != before.enabled:
            text = "Call path pruning " + ("activated" if pruning.enabled else "deactivated")
        else:
            text = (
                "Call path pruning: depth "
                + str(pruning.hot_depth)
                + ", unclassified functions: "
                + pruning.unclassified
            )
        self.status.set(text, widgets.STATUS_OK, reset_ms=3000)
        self.refresh_notice()
        # builds and profiling data with another setting are not current any more
        self.project_state.publish(CallpathPruningChanged())

    def reload(self) -> None:
        """Show the stored setting (it may have been changed outside the GUI) without storing it again."""
        stored = callpath_pruning.load_callpath_pruning(self.arguments.project_dir)
        widgets_to_block = (self.checkbox, self.depth_spin, self.unclassified)
        for widget in widgets_to_block:
            widget.blockSignals(True)
        self.checkbox.setChecked(stored.enabled)
        self.depth_spin.setValue(stored.hot_depth)
        self.unclassified.setCurrentText(stored.unclassified)
        for widget in widgets_to_block:
            widget.blockSignals(False)
        self.refresh_notice()

    def refresh_notice(self) -> None:
        """Current hotspot results exist but pruning is off, or it is on without them."""
        config = self.project_state.current_config
        text = callpath_pruning.inactive_warning(
            self.arguments, config, at_setting=True
        ) or callpath_pruning.no_hotspots_warning(self.arguments, config)
        if text:
            self.notice.set_message("Call path pruning", text)
        self.notice.setVisible(bool(text) and self._active)
