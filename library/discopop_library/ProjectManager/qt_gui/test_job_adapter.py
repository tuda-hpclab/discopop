# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import threading
from typing import Any, List

from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QWidget

from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.threads import on_main_thread
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkFinished, WorkOutput


def test_events_reach_the_handler_on_the_main_thread(qtbot: QtBot) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    received: List[Any] = []
    threads: List[bool] = []

    def work(context: WorkContext) -> str:
        assert threading.current_thread() is not threading.main_thread()
        context.output("one")
        context.output("two")
        return "done"

    def handler(event: Any) -> None:
        threads.append(on_main_thread())
        received.append(event)

    start_work(owner, work, handler)
    qtbot.waitUntil(lambda: any(isinstance(event, WorkFinished) for event in received), timeout=5000)

    assert [event.text for event in received if isinstance(event, WorkOutput)] == ["one", "two"]
    finished = received[-1]
    assert isinstance(finished, WorkFinished) and finished.result == "done" and finished.error is None
    assert all(threads)


def test_a_handler_may_start_the_next_job(qtbot: QtBot) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    finished: List[str] = []

    def second(event: Any) -> None:
        if isinstance(event, WorkFinished):
            finished.append(event.result)

    def first(event: Any) -> None:
        if isinstance(event, WorkFinished):
            finished.append(event.result)
            start_work(owner, lambda _context: "second", second)

    start_work(owner, lambda _context: "first", first)
    qtbot.waitUntil(lambda: len(finished) == 2, timeout=5000)
    qtbot.wait(200)
    # each terminal event is delivered exactly once
    assert finished == ["first", "second"]


def test_an_exception_of_the_work_is_delivered_as_error(qtbot: QtBot) -> None:
    owner = QWidget()
    qtbot.addWidget(owner)
    received: List[Any] = []

    def work(_context: WorkContext) -> None:
        raise ValueError("broken")

    start_work(owner, work, received.append)
    qtbot.waitUntil(lambda: bool(received), timeout=5000)
    assert isinstance(received[-1], WorkFinished) and "broken" in str(received[-1].error)
