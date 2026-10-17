# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the logging redirection of the GUI (no display needed: the text area is a stand-in)."""

import logging
import threading
from typing import Any, Callable, List, Tuple, cast

from discopop_library.ProjectManager.gui.mixins.helpers import redirect_logging_to_text_area


class _FakeTextArea:
    """Records what the Tk main loop would do; ``after`` queues instead of running."""

    def __init__(self) -> None:
        self.queued: List[Callable[[], None]] = []
        self.inserted: List[Tuple[str, str]] = []
        self.threads_touching_widget: List[int] = []

    def after(self, _delay: int, func: Callable[[], None]) -> None:
        self.queued.append(func)

    def config(self, **_kwargs: Any) -> None:
        self.threads_touching_widget.append(threading.get_ident())

    def insert(self, _index: Any, text: str, tag: str) -> None:
        self.inserted.append((text, tag))

    def see(self, _index: Any) -> None:
        pass


def test_redirect_is_undone_and_does_not_touch_the_widget_from_the_emitting_thread() -> None:
    root = logging.getLogger()
    handlers_before = root.handlers[:]
    level_before = root.level
    area = _FakeTextArea()

    restore = redirect_logging_to_text_area(cast(Any, area), "INFO")
    try:
        assert len(root.handlers) == 1
        worker = threading.Thread(target=lambda: logging.getLogger("x").warning("hello"))
        worker.start()
        worker.join()
        # nothing was written by the worker; it only queued the update for the main loop
        assert area.threads_touching_widget == []
        assert len(area.queued) == 1
    finally:
        restore()

    area.queued[0]()
    assert area.inserted == [("[x] WARNING: hello\n", "WARNING")]
    assert root.handlers == handlers_before
    assert root.level == level_before
