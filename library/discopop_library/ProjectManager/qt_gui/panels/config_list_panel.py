# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The configuration selector at the top of the stages that work on the selected configuration: select, create,
copy, rename, delete, the wizard.

Ported from ``gui/mixins/config_list.py``, ``gui/mixins/config_crud.py`` and ``gui/mixins/wizard_launcher.py``
(without ``_update_execute_modes``: the Execute panel reacts to ``ConfigChanged`` / ``ConfigurationsChanged``).
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction, QFont, QWheelEvent
from PySide6.QtWidgets import QLabel, QMenu, QSizePolicy, QTabBar, QToolButton, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.tabs import TAB_PROFILING
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

CAPTION = "EXECUTION CONFIGURATION"
NO_CONFIGURATIONS = "No configurations yet"
# the tab strip shrinks to this width before it scrolls
_STRIP_MIN_WIDTH = 160
_NEW_BUTTON_WIDTH = 34
# the vertical margins of a tab (top and bottom, see widgets._chrome_rules)
_TAB_MARGINS = 4


class ConfigTabBar(QTabBar):
    """The configurations as a strip of link-like tabs; arrows scroll it when the tabs do not fit.

    The mouse wheel scrolls the strip (as the arrows do) instead of switching the configuration, so scrolling over
    the selector never switches it by accident.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(widgets.CONFIG_TABS_NAME)
        self.setUsesScrollButtons(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setDocumentMode(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt's name)
        hint = super().minimumSizeHint()
        hint.setWidth(min(_STRIP_MIN_WIDTH, self.sizeHint().width()))
        return hint

    def scroll_button(self, arrow: Qt.ArrowType) -> Optional[QToolButton]:
        """The scroll arrow pointing to ``arrow`` (left / right); shown by Qt only while the tabs do not fit."""
        return next((button for button in self.findChildren(QToolButton) if button.arrowType() == arrow), None)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt's name)
        delta = event.angleDelta()
        steps = delta.y() if abs(delta.y()) >= abs(delta.x()) else delta.x()
        button = self.scroll_button(Qt.ArrowType.LeftArrow if steps > 0 else Qt.ArrowType.RightArrow)
        if steps and button is not None and button.isVisible() and button.isEnabled():
            button.click()
        event.accept()


class ConfigListPanel(Panel):
    """The configurations as a strip of tabs, one per configuration (the selected one filled), "+" for a new one and
    a "⋯" menu (new with the wizard, copy, rename, delete).

    There is one selector; the main window moves it to the top of the stage in front when that stage works on the
    selected configuration (``tabs.CONFIG_STAGES``) and hides it on the others.
    Right-clicking a tab offers copy, rename and delete of its configuration.

    It used to be a list taking the left side of the window, then a combo box; the tabs show all configurations at
    a glance and switch with one click, and scroll when there are more than fit.

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
        self._updating = False
        self._shown_config: Optional[str] = None
        self._wizard: Optional[ConfigurationWizard] = None

        self.caption_label = QLabel(CAPTION)
        caption_font = QFont(self.caption_label.font())
        caption_font.setPointSizeF(max(caption_font.pointSizeF() * 0.75, 6.5))
        caption_font.setBold(True)
        caption_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        self.caption_label.setFont(caption_font)
        self.caption_label.setObjectName(widgets.CAPTION_NAME)
        self.tab_bar = ConfigTabBar()
        self.tab_bar.currentChanged.connect(lambda _index: self._on_tab_changed())
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._show_tab_menu)
        self.empty_label = QLabel(NO_CONFIGURATIONS)
        self.empty_label.setObjectName(widgets.CAPTION_NAME)
        # a framed button (not a flat one as "⋯"): creating a configuration is a main action of the selector
        self.new_button = widgets.create_button("+", self.new_config, tooltip="New configuration")
        self.new_button.setObjectName(widgets.COMPACT_NAME)
        self.new_button.setFixedWidth(_NEW_BUTTON_WIDTH)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName(widgets.FLAT_NAME)
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip("New with the wizard, copy, rename or delete the configuration; the color theme")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = QMenu(self.menu_button)
        self.menu_button.setMenu(self._menu)
        self._fill_menu()
        # as wide as its content (as a card of a page), up to the width of the page, where the tabs scroll
        layout = widgets.hbox(
            self.caption_label, self.tab_bar, self.empty_label, self.new_button, self.menu_button, margins=0
        )
        layout.setSpacing(6)
        layout.setContentsMargins(10, 4, 8, 4)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # a strip of its own on the page, in the color of the window's frame (widgets.CONFIG_BAR_NAME)
        self.setObjectName(widgets.CONFIG_BAR_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh())
        self.refresh()

    # --- the tabs ---

    def names(self) -> List[str]:
        return [self.tab_bar.tabText(index) for index in range(self.tab_bar.count())]

    def selected(self) -> Optional[str]:
        return self._shown_config

    def refresh(self) -> None:
        """Show the configurations on disk; the selection stays, else the first one is selected."""
        previous = self.project_state.current_config
        configs = list_configurations(self.config_dir)
        chosen = previous if previous in configs else (configs[0] if configs else None)
        self._updating = True
        try:
            while self.tab_bar.count():
                self.tab_bar.removeTab(0)
            for name in configs:
                index = self.tab_bar.addTab(name)
                self.tab_bar.setTabToolTip(index, f"Execution configuration '{name}'; right-click for more")
            if chosen is not None:
                self.tab_bar.setCurrentIndex(configs.index(chosen))
        finally:
            self._updating = False
        self.tab_bar.setVisible(bool(configs))
        if configs:
            # "+" as tall as the tabs (without their margins), so that it lines up with them
            self.new_button.setFixedHeight(max(self.tab_bar.tabRect(0).height() - _TAB_MARGINS, 24))
        self.empty_label.setVisible(not configs)
        self.project_state.current_config = chosen
        self._shown_config = chosen
        self._fill_menu()
        # nothing is selected without configurations: the panels listening must not keep showing the deleted one
        self.project_state.publish(ConfigChanged(chosen))

    def _select(self, name: Optional[str]) -> None:
        """Select the tab of ``name`` without telling anybody (the caller does)."""
        if name is None or name not in self.names():
            return
        self._updating = True
        try:
            self.tab_bar.setCurrentIndex(self.names().index(name))
        finally:
            self._updating = False

    def select(self, name: str) -> bool:
        """Select ``name`` as the user would (asking whether to leave the current one); False if refused."""
        if name == self._shown_config:
            return True
        if name not in self.names():
            return False
        self._select(name)
        return self._change_selection(name)

    def _on_tab_changed(self) -> None:
        if self._updating:
            return
        index = self.tab_bar.currentIndex()
        if index < 0:
            return
        name = self.tab_bar.tabText(index)
        if name != self._shown_config:
            self._change_selection(name)

    def _change_selection(self, name: str) -> bool:
        """The user selected ``name``: ask whether to leave the current configuration, then switch."""
        if not self._confirm_leave_config():
            self._select(self._shown_config)
            return False
        self._shown_config = name
        self.project_state.current_config = name
        self._fill_menu()
        # the stage in front stays: the selector is only shown on the stages that work on the selection
        self.project_state.publish(ConfigChanged(name))
        return True

    # --- the menus ---

    def menu(self) -> QMenu:
        """The menu of the "⋯" button; the main window adds the entries that are not about configurations."""
        return self._menu

    def _fill_menu(self) -> None:
        """The configuration entries of the "⋯" menu, naming the selected configuration; what the main window
        added after them (behind the separator ``self._menu_end``) stays."""
        menu = self._menu
        kept = list(menu.actions())
        end = getattr(self, "_menu_end", None)
        kept = kept[kept.index(end) + 1 :] if end in kept else []
        for action in list(menu.actions()):
            if action not in kept:
                menu.removeAction(action)
        first = kept[0] if kept else None
        current = self._shown_config
        entries: List[QAction] = []
        for text, slot in (
            ("New Configuration…", self.new_config),
            ("New with Wizard…", self.open_configuration_wizard),
        ):
            entries.append(self._make_action(text, slot))
        entries.append(self._separator())
        for text, slot in (("Copy", self.copy_config), ("Rename", self.rename_config), ("Delete", self.delete_config)):
            action = self._make_action(f"{text} “{current}”…" if current else f"{text}…", slot)
            action.setEnabled(current is not None)
            entries.append(action)
        self._menu_end = self._separator()
        entries.append(self._menu_end)
        for action in entries:
            if first is not None:
                menu.insertAction(first, action)
            else:
                menu.addAction(action)

    def _make_action(self, text: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, self._menu)
        action.triggered.connect(lambda _checked=False: slot())
        return action

    def _separator(self) -> QAction:
        action = QAction(self._menu)
        action.setSeparator(True)
        return action

    def tab_menu(self, name: str) -> QMenu:
        """The context menu of the tab of ``name``: copy, rename, delete (of that configuration)."""
        menu = QMenu(self)
        for text, slot in (("Copy", self.copy_config), ("Rename", self.rename_config), ("Delete", self.delete_config)):
            action = menu.addAction(f"{text} “{name}”…")
            action.triggered.connect(lambda _checked=False, slot=slot, name=name: self._on_tab_action(name, slot))
        return menu

    def _on_tab_action(self, name: str, slot: Callable[[], None]) -> None:
        # the actions work on the selected configuration: select the right-clicked one first (it may be refused)
        if self.select(name):
            slot()

    def _show_tab_menu(self, pos: QPoint) -> None:
        index = self.tab_bar.tabAt(pos)
        if index >= 0:
            self.tab_menu(self.tab_bar.tabText(index)).popup(self.tab_bar.mapToGlobal(pos))

    def menu_actions(self) -> List[str]:
        """The texts of the "⋯" menu (separators as ""), for tests."""
        return [action.text() for action in self._menu.actions()]

    def trigger(self, text: str) -> None:
        """Trigger the "⋯" menu entry ``text`` as the user would (for tests)."""
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
