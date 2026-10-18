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
import tkinter as tk
from typing import Any, Callable, List, Tuple, cast

from discopop_library.ProjectManager.gui.mixins.helpers import grab_when_viewable, redirect_logging_to_text_area


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


class _FakeWindow:
    """A window that becomes viewable after ``unmapped_attempts`` failed grabs; ``after`` queues the retry."""

    def __init__(self, unmapped_attempts: int) -> None:
        self.unmapped_attempts = unmapped_attempts
        self.grabbed = False
        self.queued: List[Callable[[], None]] = []

    def grab_set(self) -> None:
        if self.unmapped_attempts > 0:
            self.unmapped_attempts -= 1
            raise tk.TclError("grab failed: window not viewable")
        self.grabbed = True

    def after(self, _delay: int, func: Callable[[], None]) -> None:
        self.queued.append(func)


def test_the_grab_waits_until_the_window_is_viewable() -> None:
    window = _FakeWindow(unmapped_attempts=3)
    grab_when_viewable(cast(tk.Misc, window))
    while window.queued:
        window.queued.pop(0)()
    assert window.grabbed


def test_a_window_that_never_becomes_viewable_is_given_up() -> None:
    window = _FakeWindow(unmapped_attempts=1000)
    grab_when_viewable(cast(tk.Misc, window), attempts=5)
    retries = 0
    while window.queued:
        window.queued.pop(0)()
        retries += 1
    assert retries == 4 and not window.grabbed
