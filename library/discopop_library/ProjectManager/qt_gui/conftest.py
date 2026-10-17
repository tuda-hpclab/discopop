# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Widget tests of the Qt GUI: offscreen, without modal dialogs.

The platform plugin is chosen when the QApplication is created, so it is set here, before pytest-qt creates it;
``QT_QPA_PLATFORM=xcb`` in the environment runs the tests on a real display instead.

Windows a test leaves open are deleted after it (see ``delete_leftover_widgets``).

A modal dialog would block a test (offscreen it is not even visible). Every function of ``qt_gui/dialogs.py`` is
replaced by a recorder: messages are recorded, questions are answered from ``dialog_answers`` and fail the test
when it has no answer. Any other modal ``exec()`` fails the test as well.
"""

import os
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from discopop_library.ProjectManager.qt_gui import dialogs  # noqa: E402

_QT_GUI_DIR = Path(__file__).parent

_QUESTIONS = {"ask_yes_no", "ask_string", "ask_choice", "ask_open_file", "ask_directory", "ask_save_file"}


def pytest_collection_modifyitems(items: List[pytest.Item]) -> None:
    for item in items:
        if _QT_GUI_DIR in Path(str(item.path)).parents:
            item.add_marker(pytest.mark.qt)


class DialogRecorder:
    """What the code under test showed (``calls``: name, title, message) and the answers it gets."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, str]] = []
        self._answers: Dict[str, Deque[Any]] = {}

    def answer(self, name: str, *answers: Any) -> None:
        """Queue the answers the next calls of the question ``name`` (e.g. "ask_yes_no") return."""
        self._answers.setdefault(name, deque()).extend(answers)

    def titles(self, name: Optional[str] = None) -> List[str]:
        return [title for called, title, _ in self.calls if name is None or called == name]

    def messages(self, name: Optional[str] = None) -> List[str]:
        return [message for called, _, message in self.calls if name is None or called == name]

    def make(self, name: str) -> Callable[..., Any]:
        def record(_parent: Any, title: str, message: str = "", *_args: Any, **_kwargs: Any) -> Any:
            self.calls.append((name, title, message))
            if name not in _QUESTIONS:
                return None
            pending = self._answers.get(name)
            if not pending:
                raise AssertionError(f"unexpected dialog {name}({title!r}, {message!r}): queue an answer first")
            return pending.popleft()

        return record


def _no_modal_exec(self: Any, *_args: Any) -> int:
    raise AssertionError(f"a modal {type(self).__name__} was opened; show dialogs through qt_gui.dialogs")


@pytest.fixture(autouse=True)
def dialog_answers(monkeypatch: pytest.MonkeyPatch) -> Iterator[DialogRecorder]:
    recorder = DialogRecorder()
    for name in dialogs.__all__:
        monkeypatch.setattr(dialogs, name, recorder.make(name))
    monkeypatch.setattr(QDialog, "exec", _no_modal_exec)
    monkeypatch.setattr(QMessageBox, "exec", _no_modal_exec)
    yield recorder


@pytest.fixture(autouse=True)
def delete_leftover_widgets(qapp: QApplication) -> Iterator[None]:
    """Delete the windows a test left behind, while the application still exists.

    A widget without a parent that only Python holds is otherwise destroyed at interpreter exit, after the
    QApplication, which corrupts the heap ("pure virtual method called", "malloc_consolidate()") at random.
    """
    yield
    for widget in QApplication.topLevelWidgets():
        # hidden, not closed: a close handler asking a question would fail outside the test
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
