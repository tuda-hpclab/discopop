# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Update notifications: the check for newer DiscoPoP packages on PyPI, the button in the status line that shows
an available update, the dialog installing it, the version list and the settings menu.

What is installed and what PyPI offers is decided by ``tools/update_notifications/update_notifier.py`` (no GUI
toolkit); it is called through the module, so the tests can replace it.
"""

import os
import shlex
import sys
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.qt_gui import dialogs, help_dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.services.jobs import (
    JobSpec,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
)
from discopop_library.tools.update_notifications import update_notifier
from discopop_library.tools.update_notifications.update_notifier import (
    CHANNEL_AUTO,
    CHANNEL_PRE,
    CHANNEL_STABLE,
    InstalledPackage,
    UpdateCheckResult,
    UpdateSettings,
)

CHECK_TITLE = "Check for Updates"
UPDATE_BUTTON_TEXT = "● Update available"

CHANNEL_TITLES: Dict[str, str] = {
    CHANNEL_AUTO: "Automatic (follow the installed version)",
    CHANNEL_STABLE: "Stable releases only",
    CHANNEL_PRE: "Include pre-releases",
}

_USED_CHANNEL_TEXT: Dict[str, str] = {
    CHANNEL_STABLE: "stable releases",
    CHANNEL_PRE: "pre-releases included",
    CHANNEL_AUTO: "per package, by its installed version",
}

BUILD_NOTE = (
    "Some DiscoPoP packages (e.g. the profiler) are built from source while they are installed: this needs "
    "clang / LLVM 19-22 with its development files and CMake, and can take several minutes."
)

RESTART_NOTE = "Restart the Project Manager to use the new version."

SETTINGS_MENU_TEXT = "Settings → Updates"
CHECK_AT_START_CHECKBOX_TEXT = "Check for DiscoPoP updates when the Project Manager starts (applies to all projects)"


def versions_text(packages: Sequence[InstalledPackage], python: str = sys.executable) -> str:
    """The installed DiscoPoP packages, their versions and where they came from, for Help → Version."""
    lines = ["Installed DiscoPoP packages", ""]
    if not packages:
        lines.append("  (none found)")
    name_width = max((len(p.name) for p in packages), default=0)
    version_width = max((len(p.version) for p in packages), default=0)
    for package in packages:
        lines.append(f"  {package.name:<{name_width}}  {package.version:<{version_width}}  {package.describe_source()}")
    lines += ["", f"Python {sys.version.split()[0]}: {python}"]
    return "\n".join(lines)


def show_versions(parent: QWidget) -> help_dialogs.HelpDialog:
    """Help → Version: a window listing the installed packages (selectable, for a bug report)."""
    dialog = help_dialogs.show_text(parent, "DiscoPoP Versions", versions_text(update_notifier.installed_packages()))
    # the columns line up
    dialog.text.setFont(widgets.monospace_font())
    dialog.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    return dialog


def _not_checked_text(result: UpdateCheckResult) -> str:
    return "\n".join(f"  {p.name} {p.version} ({p.describe_source()})" for p in result.not_checked)


class UpdateDialog(QDialog):
    """The available updates and the command installing them; "Update now" runs it here, with its output below.

    Application modal while it is open, so no job of the window starts while pip replaces the packages; shown with
    ``show()`` (not ``exec()``), like the other windows of the GUI.
    """

    restart_requested = Signal()
    # pip succeeded: the result of the check is out of date
    updated = Signal()

    def __init__(
        self,
        result: UpdateCheckResult,
        busy_reason: Callable[[], str],
        parent: Optional[QWidget] = None,
        prefix: Optional[Sequence[str]] = None,
        runnable: Optional[bool] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DiscoPoP Update")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(760, 360)
        self.check_result = result
        self._busy_reason = busy_reason
        self._runner: Optional[WorkRunner] = None
        if prefix is None or runnable is None:
            prefix, runnable = update_notifier.installer_prefix()
        self.command: List[str] = update_notifier.upgrade_command(result.updates, prefix)
        self._runnable = runnable and result.can_update_with_pip

        layout = QVBoxLayout(self)
        layout.addWidget(widgets.heading_label("A new version of DiscoPoP is available"))
        self.table = QTableWidget(len(result.updates), 3)
        self.table.setHorizontalHeaderLabels(["Package", "Installed", "Available"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, update in enumerate(result.updates):
            for column, text in enumerate((update.name, update.installed, update.latest)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeRowsToContents()
        # exactly the rows: the table does not scroll and leaves no empty space
        rows_height = sum(self.table.rowHeight(row) for row in range(self.table.rowCount()))
        self.table.setFixedHeight(self.table.horizontalHeader().sizeHint().height() + rows_height + 4)
        layout.addWidget(self.table)
        channel = _USED_CHANNEL_TEXT.get(result.channel, result.channel)
        layout.addWidget(widgets.caption_label(f"Release channel: {channel} (change it in {SETTINGS_MENU_TEXT})."))

        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.notes)
        if not result.can_update_with_pip:
            self.notes.setText(
                "These DiscoPoP packages were not installed from PyPI and are not updated here:\n"
                f"{_not_checked_text(result)}\n\n"
                "Updating the others with pip could replace them with the PyPI build. Update them where they came "
                "from; if you want to update the others anyway, run the command below yourself."
            )
        elif not runnable:
            self.notes.setText(
                "Neither pip nor uv was found for this Python environment. Install the update with the tool that "
                "manages it; the command below is what pip would run."
            )
        else:
            self.notes.setText(f"{BUILD_NOTE} Other programs using this Python environment are affected too.")

        self.command_field = QLineEdit(shlex.join(self.command))
        self.command_field.setReadOnly(True)
        self.command_field.setFont(widgets.monospace_font())
        # the interpreter at the start is the informative part
        self.command_field.setCursorPosition(0)
        self.copy_button = widgets.create_button("Copy", self.copy_command, tooltip="Copy the command")
        layout.addLayout(widgets.hbox(self.command_field, self.copy_button))

        self.console = widgets.OutputConsole()
        self.console.setVisible(False)
        layout.addWidget(self.console, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        # the free space below the content, until the output of pip takes it
        self._spacer = QWidget()
        layout.addWidget(self._spacer, 1)

        self.update_button = widgets.primary_button("Update now", self.start_update)
        self.update_button.setVisible(self._runnable)
        self.stop_button = widgets.create_button("Stop", self.stop_update)
        self.stop_button.setVisible(False)
        self.restart_button = widgets.primary_button("Restart now", self._request_restart)
        self.restart_button.setVisible(False)
        self.close_button = widgets.create_button("Close", self._close)
        layout.addLayout(
            widgets.hbox(None, self.update_button, self.stop_button, self.restart_button, self.close_button)
        )

    # --- the update ---

    def is_running(self) -> bool:
        return self._runner is not None

    def copy_command(self) -> None:
        QGuiApplication.clipboard().setText(self.command_field.text())

    def start_update(self) -> None:
        if self._runner is not None or not self._runnable:
            return
        reason = self._busy_reason()
        if reason:
            dialogs.show_warning(self, "Update", f"{reason}\nUpdate once it has finished.")
            return
        self.console.setVisible(True)
        self._spacer.setVisible(False)
        if self.height() < 560:
            self.resize(self.width(), 560)
        self.console.clear()
        self.console.append_text("$ " + shlex.join(self.command) + "\n", "INFO")
        self._set_running(True)
        self._set_status(f"Installing... {BUILD_NOTE}", widgets.STATUS_BUSY)
        command = list(self.command)

        def work(context: WorkContext) -> int:
            spec = JobSpec(command, cwd=os.path.expanduser("~"))
            return context.run_command(spec, lambda line: context.output(line + "\n"))

        self._runner = start_work(self, work, self._on_event)

    def stop_update(self) -> None:
        if self._runner is None:
            return
        if dialogs.ask_yes_no(
            self, "Stop the Update", "Stop pip? Packages it already replaced stay replaced; the others are not updated."
        ):
            self._runner.cancel()

    def _on_event(self, event: WorkEvent) -> None:
        if isinstance(event, WorkOutput):
            self.console.append_text(event.text)
            return
        if not isinstance(event, WorkFinished):
            return
        cancelled = self._runner is not None and self._runner.cancel_requested
        self._runner = None
        self._set_running(False)
        if event.error is not None:
            self.console.append_text(event.error + "\n", "ERROR")
            self._set_status(f"The update could not be started: {event.error}", widgets.STATUS_FAIL)
        elif cancelled:
            self._set_status(
                "The update was stopped. Check the installed versions in Help → Version.", widgets.STATUS_STOP
            )
        elif event.result == 0:
            self._set_status(f"DiscoPoP was updated. {RESTART_NOTE}", widgets.STATUS_OK)
            self.update_button.setVisible(False)
            self.restart_button.setVisible(True)
            self.updated.emit()
        else:
            self._set_status(
                f"pip failed (exit code {event.result}); see its output above. Nothing was changed if it failed "
                "before installing.",
                widgets.STATUS_FAIL,
            )

    def _set_running(self, running: bool) -> None:
        self.update_button.setEnabled(not running)
        self.stop_button.setVisible(running)
        self.close_button.setEnabled(not running)

    def _set_status(self, text: str, color: str) -> None:
        self.status_label.setText(text)
        widgets.set_label_color(self.status_label, color)
        self.status_label.setVisible(True)

    def _close(self) -> None:
        self.close()

    def _request_restart(self) -> None:
        self.restart_requested.emit()
        self.close()

    # --- closing ---

    def reject(self) -> None:
        # Escape: not while pip runs
        if self._runner is None:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        if self._runner is not None:
            event.ignore()
            self.stop_update()
            return
        super().closeEvent(event)


class UpdateController(QObject):
    """Checks for updates (at the start if enabled, and on request), shows the result in ``button`` (for the status
    line) and opens the :class:`UpdateDialog`; builds the menu Settings → Updates."""

    # the check ended; the result (None if it failed)
    checked = Signal(object)

    def __init__(
        self,
        window: QWidget,
        busy_reason: Callable[[], str],
        restart: Callable[[], None],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._busy_reason = busy_reason
        self._restart = restart
        self._runner: Optional[WorkRunner] = None
        self._manual = False
        self.result: Optional[UpdateCheckResult] = None
        self.dialog: Optional[UpdateDialog] = None

        self.button = QToolButton()
        self.button.setObjectName(widgets.FLAT_NAME)
        self.button.setText(UPDATE_BUTTON_TEXT)
        # stands out in the status line (orange in both themes)
        self.button.setStyleSheet(f"QToolButton {{ color: {widgets.STATUS_STOP}; font-weight: bold; }}")
        self.button.setVisible(False)
        self.button.clicked.connect(lambda _checked=False: self.open_dialog())

        self.check_at_start_action: Optional[QAction] = None
        self.channel_actions: Dict[str, QAction] = {}

    # --- checking ---

    def is_checking(self) -> bool:
        return self._runner is not None

    def check_at_start(self) -> None:
        """The automatic check: only if enabled, never for a development install, silent if it fails."""
        if not update_notifier.load_settings().check_at_start:
            return
        if update_notifier.is_development_install(update_notifier.installed_packages()):
            return
        self.check(manual=False)

    def check(self, manual: bool = True) -> None:
        """Ask PyPI in the background; ``manual`` (Help → Check for updates) reports the result in any case."""
        self._manual = self._manual or manual
        if self._runner is not None:
            return
        channel = update_notifier.load_settings().channel

        def work(_context: WorkContext) -> UpdateCheckResult:
            return update_notifier.check_for_updates(channel)

        self._runner = start_work(self, work, self._on_event)

    def _on_event(self, event: WorkEvent) -> None:
        if not isinstance(event, WorkFinished):
            return
        manual, self._manual, self._runner = self._manual, False, None
        if event.error is not None or not isinstance(event.result, UpdateCheckResult):
            if manual:
                dialogs.show_warning(self._window, CHECK_TITLE, f"The check for updates failed:\n{event.error}")
            self.checked.emit(None)
            return
        result: UpdateCheckResult = event.result
        self.result = result
        self._show_button(result)
        self.checked.emit(result)
        if manual:
            self._report(result)

    def _show_button(self, result: UpdateCheckResult) -> None:
        self.button.setVisible(bool(result.updates))
        self.button.setToolTip(
            "\n".join(f"{u.name}: {u.installed} → {u.latest}" for u in result.updates) + "\nClick to update."
            if result.updates
            else ""
        )

    def _report(self, result: UpdateCheckResult) -> None:
        if result.development_install:
            dialogs.show_message(
                self._window,
                CHECK_TITLE,
                "DiscoPoP was installed from a local checkout (a development install), so it is not updated from "
                "PyPI. Update the checkout (e.g. git pull) and install it again.\n\n" + _not_checked_text(result),
            )
            return
        if result.updates:
            self.open_dialog()
            return
        if result.errors:
            dialogs.show_warning(
                self._window, CHECK_TITLE, "PyPI could not be reached:\n" + "\n".join(f"  {e}" for e in result.errors)
            )
            return
        channel = _USED_CHANNEL_TEXT.get(result.channel, result.channel)
        message = f"DiscoPoP is up to date (release channel: {channel})."
        if result.not_checked:
            message += "\n\nNot installed from PyPI, so not checked:\n" + _not_checked_text(result)
        dialogs.show_message(self._window, CHECK_TITLE, message)

    # --- the dialog ---

    def open_dialog(self) -> Optional[UpdateDialog]:
        if self.result is None or not self.result.updates:
            return None
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return self.dialog
        dialog = UpdateDialog(self.result, self._busy_reason, self._window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.restart_requested.connect(self._restart)
        dialog.updated.connect(self._on_updated)
        dialog.destroyed.connect(lambda *_: self._forget_dialog())
        self.dialog = dialog
        dialog.show()
        return dialog

    def _on_updated(self) -> None:
        """The update is installed: nothing to offer until the next check (after the restart)."""
        self.result = None
        self.button.setVisible(False)

    def _forget_dialog(self) -> None:
        self.dialog = None

    # --- Settings → Updates ---

    def build_settings_menu(self, parent: QMenu) -> QMenu:
        """The submenu "Updates": whether to check at the start, and the release channel."""
        menu = parent.addMenu("&Updates")
        self.check_at_start_action = menu.addAction("Check for updates at start")
        self.check_at_start_action.setCheckable(True)
        self.check_at_start_action.setToolTip(
            "Ask PyPI for newer DiscoPoP versions whenever the Project Manager starts"
        )
        self.check_at_start_action.toggled.connect(lambda _checked: self._save_from_menu())
        menu.addSection("Release channel")
        group = QActionGroup(menu)
        group.setExclusive(True)
        for channel in update_notifier.CHANNELS:
            action = menu.addAction(CHANNEL_TITLES[channel])
            action.setCheckable(True)
            action.toggled.connect(lambda checked: self._save_from_menu() if checked else None)
            group.addAction(action)
            self.channel_actions[channel] = action
        # the wizard and other tools change the settings too
        menu.aboutToShow.connect(self.refresh_settings_menu)
        self.refresh_settings_menu()
        return menu

    def refresh_settings_menu(self) -> None:
        settings = update_notifier.load_settings()
        actions: List[QAction] = list(self.channel_actions.values())
        if self.check_at_start_action is not None:
            actions.append(self.check_at_start_action)
        for action in actions:
            action.blockSignals(True)
        if self.check_at_start_action is not None:
            self.check_at_start_action.setChecked(settings.check_at_start)
        if settings.channel in self.channel_actions:
            self.channel_actions[settings.channel].setChecked(True)
        for action in actions:
            action.blockSignals(False)

    def _save_from_menu(self) -> None:
        check = self.check_at_start_action is not None and self.check_at_start_action.isChecked()
        channel = next((key for key, action in self.channel_actions.items() if action.isChecked()), CHANNEL_AUTO)
        update_notifier.save_settings(UpdateSettings(check_at_start=check, channel=channel))


def check_at_start_checkbox() -> QCheckBox:
    """The setting "check at the start" as a check box (the welcome step of the wizard), saved when toggled."""
    checkbox = QCheckBox(CHECK_AT_START_CHECKBOX_TEXT)
    checkbox.setChecked(update_notifier.load_settings().check_at_start)
    checkbox.setToolTip(f"Ask PyPI for newer DiscoPoP versions; also in {SETTINGS_MENU_TEXT}")

    def save(checked: bool) -> None:
        settings = update_notifier.load_settings()
        update_notifier.save_settings(UpdateSettings(check_at_start=checked, channel=settings.channel))

    checkbox.toggled.connect(save)
    return checkbox
