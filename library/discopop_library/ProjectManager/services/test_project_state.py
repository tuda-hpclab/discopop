# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List

import pytest

from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)


def test_subscribers_are_called_in_subscription_order_with_the_event() -> None:
    state = ProjectState()
    calls: List[str] = []
    state.subscribe(ConfigChanged, lambda e: calls.append("first " + str(e.configuration)))
    state.subscribe(ConfigChanged, lambda e: calls.append("second"))
    state.publish(ConfigChanged("tiny"))
    assert calls == ["first tiny", "second"]


def test_only_subscribers_of_the_published_type_are_called() -> None:
    state = ProjectState()
    calls: List[str] = []
    state.subscribe(PatternsChanged, lambda e: calls.append("patterns"))
    state.publish(ResultsChanged())  # nobody listens: fine
    assert calls == []
    state.publish(PatternsChanged())
    assert calls == ["patterns"]


def test_a_subscriber_may_subscribe_during_a_publish() -> None:
    state = ProjectState()
    calls: List[str] = []

    def first(_e: ResultsChanged) -> None:
        calls.append("first")
        state.subscribe(ResultsChanged, lambda e: calls.append("late"))

    state.subscribe(ResultsChanged, first)
    state.publish(ResultsChanged())
    assert calls == ["first"]  # the new subscriber is called from the next publish on
    state.publish(ResultsChanged())
    assert calls == ["first", "first", "late"]


def test_an_exception_of_a_subscriber_reaches_the_publisher() -> None:
    state = ProjectState()

    def failing(_e: ResultsChanged) -> None:
        raise RuntimeError("boom")

    state.subscribe(ResultsChanged, failing)
    with pytest.raises(RuntimeError):
        state.publish(ResultsChanged())
