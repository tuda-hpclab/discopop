# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Delivers the events of a background job to the Tk main thread.

A Tk (or later Qt / web) port replaces this adapter and the panels; the job runner and what the events mean stay.
"""

import queue
from typing import Any, Callable

from discopop_library.ProjectManager.services.jobs import JobEvent, is_terminal

POLL_INTERVAL_MS = 50


class TkJobAdapter:
    """Takes the events out of a job's queue from one ``after`` loop and passes them to ``handler``.

    ``handler`` always runs on the Tk main thread. The loop ends after the terminal event of the job.
    """

    def __init__(self, widget: Any, events: "queue.Queue[JobEvent]", handler: Callable[[JobEvent], None]) -> None:
        self._widget = widget
        self._events = events
        self._handler = handler

    def start(self) -> None:
        self._widget.after(POLL_INTERVAL_MS, self._poll)

    def _poll(self) -> None:
        finished = False
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            self._handler(event)
            if is_terminal(event):
                finished = True
                break
        if not finished:
            self._widget.after(POLL_INTERVAL_MS, self._poll)
