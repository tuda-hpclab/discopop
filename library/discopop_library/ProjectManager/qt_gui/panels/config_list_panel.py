# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The configuration selector in the header bar of the main window: select, create, copy, rename, delete, the wizard.

Ported from ``gui/mixins/config_list.py``, ``gui/mixins/config_crud.py`` and ``gui/mixins/wizard_launcher.py``
(without ``_update_execute_modes``: the Execute panel reacts to ``ConfigChanged`` / ``ConfigurationsChanged``).
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.tabs import TAB_EDITOR, TAB_EXECUTE, TAB_PROFILING, TAB_REPORT
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

SWITCHER_CAPTION = "EXECUTION CONFIGURATION"
NO_CONFIGURATION = "No configuration"
_SWITCHER_MIN_WIDTH = 200


class ConfigSwitcher(QToolButton):
    """The button of the switcher: a small caption over the name of the selected configuration, and a "▾".

    A tool button (so it opens its menu on a click and takes the keyboard focus like any button) with labels laid out
    on it; the labels let the clicks through to the button.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(widgets.SWITCHER_NAME)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.caption_label = QLabel(SWITCHER_CAPTION)
        caption_font = QFont(self.font())
        caption_font.setPointSizeF(max(caption_font.pointSizeF() * 0.75, 6.5))
        caption_font.setBold(True)
        caption_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        self.caption_label.setFont(caption_font)
        self.caption_label.setObjectName(widgets.SWITCHER_CAPTION_NAME)
        self.name_label = QLabel(NO_CONFIGURATION)
        name_font = QFont(self.font())
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.arrow_label = QLabel("▾")
        self.arrow_label.setObjectName(widgets.SWITCHER_CAPTION_NAME)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        texts.addWidget(self.caption_label)
        texts.addWidget(self.name_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 4)
        layout.setSpacing(10)
        layout.addLayout(texts, 1)
        layout.addWidget(self.arrow_label, 0, Qt.AlignmentFlag.AlignVCenter)
        for label in (self.caption_label, self.name_label, self.arrow_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_name(self, name: Optional[str]) -> None:
        self.name_label.setText(name if name is not None else NO_CONFIGURATION)
        self.setAccessibleName(f"Execution configuration: {name or NO_CONFIGURATION}")
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        layout = self.layout()
        hint = layout.sizeHint() if layout is not None else super().sizeHint()
        return QSize(max(hint.width(), _SWITCHER_MIN_WIDTH), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        return self.sizeHint()


class ConfigListPanel(Panel):
    """The configuration switcher in the header bar: one button naming the selected configuration; its menu lists the
    configurations to switch to and creates, copies, renames and deletes them.

    It used to be a list taking the left side of the window, then a combo box with "+ New" and a "⋯" menu beside it;
    one configuration is worked on at a time, so one button (as the scheme or run configuration selectors of IDEs)
    says the same and keeps everything about configurations in one place.

    ``confirm_leave_config`` is asked before the user's selection changes; False keeps the old selection (the Editor
    panel uses it for unsaved changes). ``tabs`` switches the tabs of the main window. The files shared by all
    configurations (compile.sh, settings) are edited in the Project Setup stage.

    Publishes ``ConfigChanged`` when the selection changes or is refreshed, and ``ConfigurationsChanged`` after
    a configuration was created, copied, renamed, deleted or written by the wizard; refreshes on the latter.
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        confirm_leave_config: Callable[[], bool],
        tabs: TabHost,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self._confirm_leave_config = confirm_leave_config
        self._tabs = tabs
        self.config_dir = arguments.project_config_dir
        self._names: List[str] = []
        self._shown_config: Optional[str] = None
        self._wizard: Optional[ConfigurationWizard] = None

        self.switcher = ConfigSwitcher()
        self.switcher.setToolTip("The configuration the stages work on: switch, create, copy, rename or delete")
        self._menu = QMenu(self.switcher)
        # rebuilt when it opens, so it always lists what is on disk and names the selected configuration
        self._menu.aboutToShow.connect(self._fill_menu)
        self.switcher.setMenu(self._menu)
        self.config_actions: List[QAction] = []
        self.setLayout(widgets.hbox(self.switcher, margins=0))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh())
        self.refresh()

    # --- the list ---

    def names(self) -> List[str]:
        return list(self._names)

    def selected(self) -> Optional[str]:
        return self._shown_config

    def refresh(self) -> None:
        """Show the configurations on disk; the selection stays, else the first one is selected."""
        previous = self.project_state.current_config
        configs = list_configurations(self.config_dir)
        self._names = list(configs)
        chosen = previous if previous in configs else (configs[0] if configs else None)
        self.project_state.current_config = chosen
        self._shown_config = chosen
        self.switcher.set_name(chosen)
        # nothing is selected without configurations: the panels listening must not keep showing the deleted one
        self.project_state.publish(ConfigChanged(chosen))

    def select(self, name: str) -> bool:
        """Select ``name`` as the user would (asking whether to leave the current one); False if refused."""
        if name == self._shown_config:
            return True
        if name not in self._names:
            return False
        return self._change_selection(name)

    def _change_selection(self, name: str) -> bool:
        """The user selected ``name``: ask whether to leave the current configuration, then switch."""
        if not self._confirm_leave_config():
            return False
        self._shown_config = name
        self.switcher.set_name(name)
        self.project_state.current_config = name
        self.project_state.publish(ConfigChanged(name))
        # Execute and Report show the results of all configurations: back to the Editor of the selected one
        if self._tabs.current_tab() in (TAB_EXECUTE, TAB_REPORT):
            self._tabs.show_tab(TAB_EDITOR)
        return True

    # --- the menu ---

    def menu(self) -> QMenu:
        """The menu of the switcher (filled when it opens, see :meth:`_fill_menu`)."""
        return self._menu

    def _fill_menu(self) -> None:
        """The configurations (the selected one checked), then the actions: new, wizard, copy, rename, delete."""
        menu = self._menu
        menu.clear()
        self.config_actions = []
        if self._names:
            group = QActionGroup(menu)
            group.setExclusive(True)
            for name in self._names:
                action = menu.addAction(name)
                action.setCheckable(True)
                action.setChecked(name == self._shown_config)
                action.triggered.connect(lambda _checked=False, name=name: self._menu_select(name))
                group.addAction(action)
                self.config_actions.append(action)
        else:
            empty = menu.addAction("No configurations yet")
            empty.setEnabled(False)
        menu.addSeparator()
        current = self._shown_config
        self._add_action("New Configuration…", self.new_config)
        self._add_action("New with Wizard…", self.open_configuration_wizard)
        menu.addSeparator()
        for text, slot in (("Copy", self.copy_config), ("Rename", self.rename_config), ("Delete", self.delete_config)):
            action = self._add_action(f"{text} “{current}”…" if current else f"{text}…", slot)
            action.setEnabled(current is not None)

    def _add_action(self, text: str, slot: Callable[[], None]) -> QAction:
        action: QAction = self._menu.addAction(text)
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _menu_select(self, name: str) -> None:
        self.select(name)

    def menu_actions(self) -> List[str]:
        """The texts of the menu as it opens (separators as ""), for tests."""
        self._fill_menu()
        return [action.text() for action in self._menu.actions()]

    def trigger(self, text: str) -> None:
        """Trigger the menu entry ``text`` as the user would (for tests)."""
        self._fill_menu()
        action = next(action for action in self._menu.actions() if action.text() == text)
        action.trigger()

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
        # the first stage of the pipeline
        if result and result in self.names():
            self._tabs.show_tab(TAB_PROFILING)
        wizard.deleteLater()

    def cancel_jobs(self) -> None:
        if self._wizard is not None:
            self._wizard.cancel_jobs()
