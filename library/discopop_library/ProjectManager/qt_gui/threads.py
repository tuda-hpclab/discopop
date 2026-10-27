# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Checks that code runs on the thread that owns the widgets."""

from PySide6.QtCore import QCoreApplication, QThread


def on_main_thread() -> bool:
    """Whether the calling thread is the thread of the application (the only one that may touch widgets)."""
    app = QCoreApplication.instance()
    if app is None:
        return True
    return QThread.currentThread() == app.thread()


def assert_main_thread() -> None:
    """Fail loudly where a widget would be touched from a worker thread.

    Qt does not raise in that case; it corrupts its state and crashes later, often somewhere else.
    """
    if not on_main_thread():
        raise RuntimeError("a Qt widget was used from a worker thread; deliver the result through qt_gui.job_adapter")
