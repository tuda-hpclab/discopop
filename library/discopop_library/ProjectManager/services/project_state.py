# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The state the panels of the GUI share (the selected configuration) and the events that tell them what changed.

A panel that changes something others display publishes an event; the panels interested in it subscribe once, when
the application is assembled. This replaces calls like ``if hasattr(self, "_update_x"): self._update_x()`` from one
panel into another: the publisher no longer knows who is listening.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

E = TypeVar("E")


@dataclass(frozen=True)
class ConfigChanged:
    """Another configuration was selected (or the selection was refreshed)."""

    configuration: Optional[str]


@dataclass(frozen=True)
class ResultsChanged:
    """Execution results or reports changed."""


@dataclass(frozen=True)
class PatternsChanged:
    """Pattern detection ran, or the set of parallelization suggestions (patches) changed."""


@dataclass(frozen=True)
class HotspotsChanged:
    """Hotspot detection results changed."""


@dataclass(frozen=True)
class AutotuningChanged:
    """The autotuner's suggestions, or what it can work on, changed."""


@dataclass(frozen=True)
class AutotuningFinished:
    """An autotuning run ended successfully; its selection of suggestions is the new current one."""


class ProjectState:
    """The selected configuration plus a synchronous observer.

    Subscribers of one event type are called in the order they subscribed, on the thread that publishes (the Tk main
    thread in the GUI). An exception of a subscriber propagates to the publisher.
    """

    def __init__(self) -> None:
        self.current_config: Optional[str] = None
        self._subscribers: Dict[type, List[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: Type[E], callback: Callable[[E], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event: object) -> None:
        for callback in list(self._subscribers.get(type(event), [])):
            callback(event)
