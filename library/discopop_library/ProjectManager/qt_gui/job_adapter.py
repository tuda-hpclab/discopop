# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Delivers the events of a background job to the Qt main thread.

The counterpart of ``gui/job_adapter.py``: the runners in ``services/jobs.py`` put their events into a queue, a
timer on the main thread takes them out and passes them to the panel's handler.
"""

import queue
from typing import Any, Callable, Generic, Set, TypeVar

from PySide6.QtCore import QObject, QTimer

from discopop_library.ProjectManager.qt_gui.threads import assert_main_thread
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkRunner, is_terminal

E = TypeVar("E")

POLL_INTERVAL_MS = 50

# adapters whose job has not ended yet; Qt holds the timer, this keeps the Python object (and its handler) alive
_running: Set["QtJobAdapter[Any]"] = set()


class QtJobAdapter(Generic[E]):
    """Takes the events out of a job's queue on a timer and passes them to ``handler``.

    ``handler`` always runs on the main thread. The timer stops after the terminal event of the job, or when
    ``parent`` is deleted.
    """

    def __init__(self, parent: QObject, events: "queue.Queue[E]", handler: Callable[[E], None]) -> None:
        self._events = events
        self._handler = handler
        self._timer = QTimer(parent)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.destroyed.connect(lambda *_: _running.discard(self))

    def start(self) -> None:
        assert_main_thread()
        _running.add(self)
        self._timer.start()

    def _poll(self) -> None:
        assert_main_thread()
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            terminal = is_terminal(event)
            if terminal:
                # stopped before the handler runs: a handler that starts the next job must not be polled twice
                self._finish()
            self._handler(event)
            if terminal:
                return

    def _finish(self) -> None:
        self._timer.stop()
        self._timer.deleteLater()
        _running.discard(self)


def start_work(parent: QObject, work: Callable[[WorkContext], Any], handler: Callable[[WorkEvent], None]) -> WorkRunner:
    """Run ``work`` on a worker thread and pass its events to ``handler`` on the main thread."""
    events: "queue.Queue[WorkEvent]" = queue.Queue()
    runner = WorkRunner(work, events)
    QtJobAdapter(parent, events, handler).start()
    runner.start()
    return runner
