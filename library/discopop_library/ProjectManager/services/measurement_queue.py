# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The queue of a batch of measurements: one item per execution configuration, run one after another.

A small state machine, toolkit-free: queued -> running -> measured / failed / stopped. A failed item does not stop
the batch (the next configuration is measured anyway); Stop ends the running item and every queued one. The worker
reports the transitions as :class:`~discopop_library.ProjectManager.services.jobs.WorkProgress` events, the GUI
applies them with :meth:`MeasurementQueue.apply` and shows :func:`state_text` per item and :meth:`tally` at the end.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

QUEUED = "queued"
RUNNING = "running"
MEASURED = "measured"
FAILED = "failed"
STOPPED = "stopped"
TERMINAL = (MEASURED, FAILED, STOPPED)

# the text of a state in the list of configurations (a failure adds its reason)
STATE_TEXTS: Dict[str, str] = {
    QUEUED: "queued",
    RUNNING: "⏳ measuring…",
    MEASURED: "✓ measured",
    FAILED: "✗ failed",
    STOPPED: "stopped",
}


@dataclass
class QueueItem:
    name: str
    state: str = QUEUED
    detail: str = ""


def state_text(item: QueueItem) -> str:
    text = STATE_TEXTS.get(item.state, item.state)
    return f"{text}: {item.detail}" if item.detail and item.state in (FAILED, RUNNING) else text


class MeasurementQueue:
    """The items of one batch, in the order they run."""

    def __init__(self, names: Iterable[str]) -> None:
        self.items: List[QueueItem] = [QueueItem(name) for name in names]

    def item(self, name: str) -> Optional[QueueItem]:
        return next((item for item in self.items if item.name == name), None)

    def apply(self, name: str, state: str, detail: str = "") -> None:
        item = self.item(name)
        if item is not None:
            item.state = state
            item.detail = detail

    def stop_remaining(self) -> None:
        """Stop pressed (or the work ended early): what has not finished is stopped."""
        for item in self.items:
            if item.state not in TERMINAL:
                item.state = STOPPED
                item.detail = ""

    def running(self) -> Optional[QueueItem]:
        return next((item for item in self.items if item.state == RUNNING), None)

    def position(self, name: str) -> int:
        """1-based position of ``name`` in the batch (0 if it is not part of it)."""
        return next((index + 1 for index, item in enumerate(self.items) if item.name == name), 0)

    def finished(self) -> bool:
        return all(item.state in TERMINAL for item in self.items)

    def tally(self) -> str:
        """E.g. "2 measured, 1 failed ✗" (states without items are left out)."""
        parts = []
        for state in (MEASURED, FAILED, STOPPED):
            count = sum(1 for item in self.items if item.state == state)
            if count:
                parts.append(f"{count} {state}" + (" ✗" if state == FAILED else ""))
        return ", ".join(parts) if parts else "nothing measured"
