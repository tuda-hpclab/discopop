# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The "Shared build" section of the Build stage: which configurations are compiled by which one.

A configuration can build from another one (its *owner*): the owner's compile script, settings and files make the
build and the configuration only runs its own ``execute.sh`` in it (see ``configurations/build_sharing.py``). The
section edits that declaration for the selected configuration, either as "Build from" (it is a member) or as the
list of the configurations that use its build (it is an owner), and saves at once.
"""

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QListWidgetItem, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.build_sharing import (
    BuildSharingError,
    build_owner_of,
    check_can_share,
    members_of,
    set_build_from,
)
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.services.configurations import list_configurations
from discopop_library.ProjectManager.services.hotspot_session import forget_build_states
from discopop_library.ProjectManager.services.project_state import ConfigurationsChanged, ProjectState

ITSELF_TEXT = "itself (own build)"
HINT = (
    "Configurations that differ only in what execute.sh does (input, arguments, threads) can share one build: it is "
    "compiled once, with the compile script and the settings of the configuration that owns it."
)


class SharedBuildSection(widgets.FormSection):
    """Edits ``build_from`` of the selected configuration; ``changed`` is called after every saved change."""

    def __init__(
        self, arguments: ProjectManagerArguments, project_state: ProjectState, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__("Shared build", parent)
        self.arguments = arguments
        self.project_state = project_state
        self._config: Optional[str] = None
        self._updating = False

        hint = QLabel(HINT)
        hint.setWordWrap(True)
        self.add_widget(hint)
        self.owner_combo = QComboBox()
        self.owner_combo.activated.connect(self._owner_chosen)
        self.owner_combo.setToolTip("The configuration whose build is used")
        self.add_row("Build from:", self.owner_combo, stretch_field=True)
        self.members_label = QLabel("Also used by:")
        self.members_list = QListWidget()
        self.members_list.itemChanged.connect(self._member_toggled)
        self.add_widget(self.members_label)
        self.add_widget(widgets.resizable(self.members_list, 110, minimum=40, fixed=True))

    @property
    def _config_dir(self) -> str:
        return self.arguments.project_config_dir

    def refresh(self, config: Optional[str]) -> None:
        """Show the declarations of ``config`` (None: no configuration selected)."""
        self._config = config
        self._updating = True
        try:
            self.owner_combo.clear()
            self.members_list.clear()
            if not config:
                self.setEnabled(False)
                self.members_label.setVisible(False)
                self.members_list.setVisible(False)
                return
            names = [name for name in list_configurations(self._config_dir) if name != config]
            owner = build_owner_of(self._config_dir, config)
            members = members_of(self._config_dir, config)

            self.owner_combo.addItem(ITSELF_TEXT, None)
            for name in names:
                # a configuration that builds from another one cannot be an owner (builds are not chained)
                if name == owner or build_owner_of(self._config_dir, name) == name:
                    self.owner_combo.addItem(name, name)
            self.owner_combo.setCurrentIndex(max(0, self.owner_combo.findData(owner if owner != config else None)))
            # an owner stays one until its members are released
            self.owner_combo.setEnabled(not members)
            self.owner_combo.setToolTip(
                "Other configurations build from this one; release them first."
                if members
                else "The configuration whose build is used"
            )

            # only a configuration that builds for itself can be the owner of others
            can_own = owner == config
            self.members_label.setVisible(can_own)
            self.members_list.setVisible(can_own)
            if can_own:
                for name in names:
                    item = QListWidgetItem(name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if name in members else Qt.CheckState.Unchecked)
                    problem = self._problem_of(name, config) if name not in members else ""
                    if problem:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                        item.setToolTip(problem)
                    self.members_list.addItem(item)
        finally:
            self._updating = False

    def _problem_of(self, member: str, owner: str) -> str:
        """Why ``member`` cannot build from ``owner`` ("" if it can)."""
        try:
            check_can_share(self._config_dir, member, owner)
        except BuildSharingError as error:
            return str(error)
        return ""

    def _apply(self, member: str, owner: Optional[str]) -> None:
        try:
            set_build_from(self._config_dir, member, owner)
        except BuildSharingError as error:
            dialogs.show_error(self, "Cannot Share the Build", str(error))
        else:
            forget_build_states()
            self.project_state.publish(ConfigurationsChanged())
        self.refresh(self._config)

    def _owner_chosen(self, _index: int) -> None:
        if self._updating or not self._config:
            return
        data = self.owner_combo.currentData()
        config = self._config
        # not from inside the signal of the widget that refresh() rebuilds
        QTimer.singleShot(0, lambda: self._apply(config, str(data) if data else None))

    def _member_toggled(self, item: QListWidgetItem) -> None:
        if self._updating or not self._config:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        member, owner = item.text(), self._config if checked else None
        QTimer.singleShot(0, lambda: self._apply(member, owner))

    def checked_members(self) -> List[str]:
        return [
            self.members_list.item(row).text()
            for row in range(self.members_list.count())
            if self.members_list.item(row).checkState() == Qt.CheckState.Checked
        ]
