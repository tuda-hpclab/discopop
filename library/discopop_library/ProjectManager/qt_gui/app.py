# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Starts the Qt GUI: ``discopop_project_manager --gui --gui-toolkit qt``."""

import os
import signal
import sys
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.main_window import MainWindow
from discopop_library.ProjectManager.services.jobs import let_children_receive_sigint
from discopop_library.ProjectManager.utilities.initializeFiles import initialize_configuration_files

# how often the event loop hands control to Python, so that a Ctrl+C in the terminal is handled while it runs
SIGNAL_WAKE_UP_MS = 200


def create_application() -> QApplication:
    """The application object; an existing one (the tests create it once) is reused."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]] if sys.argv else ["discopop_project_manager"])
    assert isinstance(app, QApplication)
    app.setApplicationName("DiscoPoP Project Manager")
    app.setStyleSheet(widgets.APP_STYLE_SHEET)
    return app


def run_qt_gui(arguments: ProjectManagerArguments) -> None:
    # Stop sends SIGINT to the autotuner and patch repair jobs
    let_children_receive_sigint()
    app = create_application()
    was_initialized = False
    if not os.path.exists(arguments.project_config_dir):
        try:
            from discopop_library.ProjectManager.utilities.initializeDirectories import initialize_directories

            initialize_directories(arguments)
            initialize_configuration_files(arguments)
            was_initialized = True
        except Exception as e:
            dialogs.show_error(None, "Initialization Error", f"Failed to initialize project configuration:\n{e}")
            return

    window = MainWindow(arguments, was_initialized=was_initialized)
    window.show()
    QTimer.singleShot(100, window.after_show)

    # A Ctrl+C in the terminal closes the window like the close button does (the jobs are cancelled). Python
    # handles a signal only when the interpreter runs, so a timer hands control back to it while Qt waits.
    def close_window(_signum: int, _frame: Any) -> None:
        window.close()

    signal.signal(signal.SIGINT, close_window)
    wake_up = QTimer()
    wake_up.timeout.connect(lambda: None)
    wake_up.start(SIGNAL_WAKE_UP_MS)

    # exec() produces no output for as long as the window is open, which a caller that is not a person -- a script,
    # a CI job, an agent -- cannot tell apart from a hang. Name what it is waiting for.
    print("Opening the DiscoPoP Project Manager. Close the window to continue.", file=sys.stderr)
    try:
        app.exec()
    finally:
        wake_up.stop()
        window.cancel_running_jobs()
