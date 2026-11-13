# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.ProjectManager.services.measurement_queue import (
    FAILED,
    MEASURED,
    QUEUED,
    RUNNING,
    STOPPED,
    MeasurementQueue,
    QueueItem,
    state_text,
)


def test_the_states_of_a_batch_and_its_tally() -> None:
    queue = MeasurementQueue(["a", "b", "c"])
    assert [item.state for item in queue.items] == [QUEUED] * 3 and not queue.finished()
    queue.apply("a", RUNNING, "1/3")
    assert queue.running() == QueueItem("a", RUNNING, "1/3") and queue.position("b") == 2
    queue.apply("a", MEASURED)
    queue.apply("b", FAILED, "execution failed")
    queue.apply("unknown", FAILED)  # not part of the batch: ignored
    queue.stop_remaining()
    assert [item.state for item in queue.items] == [MEASURED, FAILED, STOPPED] and queue.finished()
    assert queue.tally() == "1 measured, 1 failed ✗, 1 stopped"
    assert MeasurementQueue([]).tally() == "nothing measured" and queue.position("x") == 0


def test_the_text_of_a_state() -> None:
    assert state_text(QueueItem("a", FAILED, "no result")) == "✗ failed: no result"
    assert state_text(QueueItem("a", RUNNING, "2/3")) == "⏳ measuring…: 2/3"
    assert state_text(QueueItem("a", MEASURED, "ignored")) == "✓ measured"
    assert state_text(QueueItem("a", STOPPED)) == "stopped"
