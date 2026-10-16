# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import queue
from typing import Callable, List, Tuple

from discopop_library.ProjectManager.gui.job_adapter import POLL_INTERVAL_MS, TkJobAdapter
from discopop_library.ProjectManager.services.jobs import JobEvent, JobFinished, JobOutput


class _FakeWidget:
    """Collects what would be scheduled on the Tk main loop."""

    def __init__(self) -> None:
        self.scheduled: List[Tuple[int, Callable[[], None]]] = []

    def after(self, delay: int, func: Callable[[], None]) -> None:
        self.scheduled.append((delay, func))

    def run_next(self) -> None:
        _, func = self.scheduled.pop(0)
        func()


def test_events_are_handled_in_order_and_polling_stops_after_the_terminal_event() -> None:
    widget = _FakeWidget()
    events: "queue.Queue[JobEvent]" = queue.Queue()
    handled: List[JobEvent] = []
    TkJobAdapter(widget, events, handled.append).start()

    widget.run_next()  # nothing queued yet: polls again
    assert handled == [] and len(widget.scheduled) == 1 and widget.scheduled[0][0] == POLL_INTERVAL_MS

    events.put(JobOutput("a"))
    events.put(JobOutput("b"))
    widget.run_next()
    assert handled == [JobOutput("a"), JobOutput("b")] and len(widget.scheduled) == 1

    events.put(JobFinished(0, False))
    widget.run_next()
    assert handled[-1] == JobFinished(0, False)
    assert widget.scheduled == []  # the loop ended
