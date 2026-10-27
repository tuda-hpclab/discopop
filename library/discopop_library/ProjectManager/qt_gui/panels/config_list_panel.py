# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The configuration list on the left of the main window: select, create, copy, rename, delete, the wizard.

Ported from ``gui/mixins/config_list.py``, ``gui/mixins/config_crud.py`` and ``gui/mixins/wizard_launcher.py``
(without ``_update_execute_modes``: the Execute panel reacts to ``ConfigChanged`` / ``ConfigurationsChanged``).
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QMenu, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.tabs import TAB_EDITOR, TAB_EXECUTE, TAB_REPORT
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.wizard import ConfigurationWizard
from discopop_library.ProjectManager.services.configurations import (
    ConfigurationError,
    SameNameError,
    copy_configuration_directory,
    create_configuration,
    delete_configuration_directory,
    has_real_configuration,
    list_configurations,
    rename_configuration,
)
from discopop_library.ProjectManager.services.project_state import ConfigChanged, ConfigurationsChanged, ProjectState

_STATUS_RESET_MS = 2000


class ConfigListPanel(Panel):
    """The "Run Configs" list with its buttons.

    ``confirm_leave_config`` is asked before the user's selection changes (a click, the right-click menu); False
    keeps the old selection (the Editor panel uses it for unsaved changes). ``open_compilation_editor`` is the
    "Edit Compilation" button. ``tabs`` switches the tabs of the main window.

    Publishes ``ConfigChanged`` when the selection changes or is refreshed, and ``ConfigurationsChanged`` after
    a configuration was created, copied, renamed, deleted or written by the wizard; refreshes on the latter.
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        confirm_leave_config: Callable[[], bool],
        open_compilation_editor: Callable[[], None],
        tabs: TabHost,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self._confirm_leave_config = confirm_leave_config
        self._open_compilation_editor = open_compilation_editor
        self._tabs = tabs
        self.config_dir = arguments.project_config_dir
        self._updating = False
        self._shown_config: Optional[str] = None
        self._wizard: Optional[ConfigurationWizard] = None
        self._menu: Optional[QMenu] = None

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.customContextMenuRequested.connect(self._on_right_click)
        self.new_button = widgets.primary_button("+ New", self.new_config)
        self.edit_compilation_button = widgets.create_button("Edit Compilation", self._open_compilation_editor)

        heading = widgets.heading_label("Run Configs", title=True)
        layout = widgets.vbox(
            heading,
            self.list,
            self.new_button,
            self.edit_compilation_button,
            margins=5,
        )
        layout.setStretchFactor(self.list, 1)
        layout.setAlignment(heading, Qt.AlignmentFlag.AlignHCenter)
        self.setLayout(layout)

        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh())
        self.refresh()

    # --- the list ---

    def names(self) -> List[str]:
        return [self._item_name(row) for row in range(self.list.count())]

    def _item_name(self, row: int) -> str:
        item = self.list.item(row)
        return item.text() if item is not None else ""

    def refresh(self) -> None:
        """Show the configurations on disk; the selection stays, else the first one is selected."""
        previous = self.project_state.current_config
        configs = list_configurations(self.config_dir)
        self._updating = True
        try:
            self.list.clear()
            self.list.addItems(configs)
            chosen = previous if previous in configs else (configs[0] if configs else None)
            if chosen is not None:
                self.list.setCurrentRow(configs.index(chosen))
        finally:
            self._updating = False
        self.project_state.current_config = chosen
        self._shown_config = chosen
        # nothing is selected without configurations: the panels listening must not keep showing the deleted one
        self.project_state.publish(ConfigChanged(chosen))

    def _selected_name(self) -> Optional[str]:
        items = self.list.selectedItems()
        return items[0].text() if items else None

    def _select(self, name: Optional[str]) -> None:
        """Select ``name`` in the list without telling anybody (the caller does)."""
        self._updating = True
        try:
            self.list.clearSelection()
            if name is not None:
                self.list.setCurrentRow(self.names().index(name))
        finally:
            self._updating = False

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        name = self._selected_name()
        if name is None or name == self._shown_config:
            return
        self._change_selection(name)

    def _change_selection(self, name: str) -> bool:
        """The user selected ``name``: ask whether to leave the current configuration, then switch."""
        if not self._confirm_leave_config():
            self._select(self._shown_config)
            return False
        self._shown_config = name
        self.project_state.current_config = name
        self.project_state.publish(ConfigChanged(name))
        # Execute and Report show the results of all configurations: back to the Editor of the selected one
        if self._tabs.current_tab() in (TAB_EXECUTE, TAB_REPORT):
            self._tabs.show_tab(TAB_EDITOR)
        return True

    # --- the context menu ---

    def _on_right_click(self, position: QPoint) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        if not self._select_for_menu(item):
            return
        self._menu = self.context_menu()
        self._menu.popup(self.list.viewport().mapToGlobal(position))

    def _select_for_menu(self, item: QListWidgetItem) -> bool:
        name = item.text()
        if name == self._shown_config:
            return True
        self._select(name)
        return self._change_selection(name)

    def context_menu(self) -> QMenu:
        menu = QMenu(self.list)
        copy_action: QAction = menu.addAction("Copy")
        copy_action.triggered.connect(lambda _checked=False: self.copy_config())
        rename_action: QAction = menu.addAction("Rename")
        rename_action.triggered.connect(lambda _checked=False: self.rename_config())
        menu.addSeparator()
        delete_action: QAction = menu.addAction("Delete")
        delete_action.triggered.connect(lambda _checked=False: self.delete_config())
        return menu

    # --- create / copy / rename / delete ---

    def _done(self, text: str) -> None:
        self.status.set(text, widgets.STATUS_OK, reset_ms=_STATUS_RESET_MS)

    def _failed(self, text: str) -> None:
        self.status.set(text, widgets.STATUS_FAIL)

    def new_config(self) -> None:
        name = dialogs.ask_string(self, "New Configuration", "Enter configuration name:")
        if not name:
            return
        try:
            config_name = create_configuration(self.arguments, name)
        except ConfigurationError as e:
            dialogs.show_error(self, e.title, e.message)
            return
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to create configuration: {e}")
            self._failed("Error creating config")
            return
        try:
            # the refresh keeps the selection, so the new configuration becomes the selected one
            self.project_state.current_config = config_name
            self.project_state.publish(ConfigurationsChanged())
            self._done(f"Created configuration '{config_name}'")
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to create configuration: {e}")
            self._failed("Error creating config")

    def copy_config(self) -> None:
        current = self.project_state.current_config
        if not current:
            dialogs.show_warning(self, "No selection", "Please select a configuration to copy")
            return
        name = dialogs.ask_string(self, "Copy Configuration", f"Enter new name for copy of '{current}':")
        if not name:
            return
        try:
            config_name = copy_configuration_directory(self.config_dir, current, name)
        except ConfigurationError as e:
            dialogs.show_error(self, e.title, e.message)
            return
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to copy configuration: {e}")
            self._failed("Error copying config")
            return
        try:
            self.project_state.publish(ConfigurationsChanged())
            self._done(f"Copied configuration to '{config_name}'")
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to copy configuration: {e}")
            self._failed("Error copying config")

    def rename_config(self) -> None:
        current = self.project_state.current_config
        if not current:
            dialogs.show_warning(self, "No selection", "Please select a configuration to rename")
            return
        name = dialogs.ask_string(self, "Rename Configuration", f"Enter new name for '{current}':")
        if not name:
            return
        try:
            new_name = rename_configuration(self.config_dir, current, name)
        except SameNameError:
            dialogs.show_message(self, "No change", "New name is the same as the current name")
            return
        except ConfigurationError as e:
            dialogs.show_error(self, e.title, e.message)
            return
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to rename configuration: {e}")
            self._failed("Error renaming config")
            return
        try:
            self.project_state.current_config = new_name
            self.project_state.publish(ConfigurationsChanged())
            self._done(f"Renamed configuration to '{new_name}'")
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to rename configuration: {e}")
            self._failed("Error renaming config")

    def delete_config(self) -> None:
        current = self.project_state.current_config
        if not current:
            dialogs.show_warning(self, "No selection", "Please select a configuration to delete")
            return
        if not dialogs.ask_yes_no(
            self, "Confirm Delete", f"Are you sure you want to delete '{current}'? This cannot be undone."
        ):
            return
        try:
            delete_configuration_directory(self.config_dir, current)
            self.project_state.current_config = None
            self.project_state.publish(ConfigurationsChanged())
            self._done("Deleted configuration")
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to delete configuration: {e}")
            self._failed("Error deleting config")

    # --- the wizard ---

    def maybe_open_wizard(self, was_initialized: bool) -> None:
        """Offer the configuration wizard if the project has no real configuration; call once the window is shown."""
        if has_real_configuration(self.config_dir):
            return
        if was_initialized:
            dialogs.show_message(
                self,
                "Project Initialized",
                f"Project configuration directory has been initialized:\n{self.config_dir}",
            )
        self.open_configuration_wizard()

    def open_configuration_wizard(self) -> None:
        wizard = ConfigurationWizard(self.arguments, self)
        wizard.finished.connect(lambda _code, w=wizard: self._wizard_finished(w))  # type: ignore[misc]
        self._wizard = wizard
        wizard.open()

    def _wizard_finished(self, wizard: ConfigurationWizard) -> None:
        self._wizard = None
        result = wizard.result_name
        if result:
            self.project_state.current_config = result
        self.project_state.publish(ConfigurationsChanged())
        if result and result in self.names():
            self._tabs.show_tab(TAB_EXECUTE)
        wizard.deleteLater()

    def cancel_jobs(self) -> None:
        if self._wizard is not None:
            self._wizard.cancel_jobs()
