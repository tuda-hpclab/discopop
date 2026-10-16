# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import queue
import sys
import threading
from pathlib import Path
from typing import List

import pytest

from discopop_library.ProjectManager.services.jobs import (
    CancelPolicy,
    JobEvent,
    JobFailedToStart,
    JobFinished,
    JobOutput,
    JobRunner,
    JobSpec,
    is_terminal,
)


def _run_to_end(spec: JobSpec, timeout: float = 20) -> List[JobEvent]:
    events: "queue.Queue[JobEvent]" = queue.Queue()
    JobRunner(spec, events).start()
    result: List[JobEvent] = []
    while True:
        event = events.get(timeout=timeout)
        result.append(event)
        if is_terminal(event):
            return result


def _python(code: str, tmp_path: Path, **kwargs: object) -> JobSpec:
    return JobSpec([sys.executable, "-u", "-c", code], str(tmp_path), **kwargs)  # type: ignore[arg-type]


def test_output_lines_and_return_code(tmp_path: Path) -> None:
    events = _run_to_end(_python("import sys; print('a'); print('b', file=sys.stderr); sys.exit(3)", tmp_path))
    assert [e.line for e in events if isinstance(e, JobOutput)] == ["a", "b"]
    assert events[-1] == JobFinished(3, False)


def test_the_job_runs_in_the_given_directory(tmp_path: Path) -> None:
    events = _run_to_end(_python("import os; print(os.getcwd())", tmp_path))
    assert Path(events[0].line).resolve() == tmp_path.resolve()  # type: ignore[union-attr]


def test_a_missing_executable_is_reported(tmp_path: Path) -> None:
    events = _run_to_end(JobSpec(["/nonexistent/tool"], str(tmp_path)))
    assert len(events) == 1 and isinstance(events[0], JobFailedToStart)


@pytest.mark.parametrize(
    "policy,new_session",
    [(CancelPolicy.SIGINT, False), (CancelPolicy.SIGTERM_GROUP, True), (CancelPolicy.TERMINATE, False)],
)
def test_cancelling_a_running_job(tmp_path: Path, policy: CancelPolicy, new_session: bool) -> None:
    code = "import time; print('ready', flush=True); time.sleep(60)"
    events: "queue.Queue[JobEvent]" = queue.Queue()
    runner = JobRunner(_python(code, tmp_path, cancel_policy=policy, new_session=new_session), events)
    runner.start()
    assert events.get(timeout=20) == JobOutput("ready")
    runner.cancel()
    last = events.get(timeout=20)
    while not is_terminal(last):
        last = events.get(timeout=20)
    assert isinstance(last, JobFinished)
    assert last.cancelled
    assert last.returncode != 0


def test_a_cancel_before_the_process_exists_still_stops_it(tmp_path: Path) -> None:
    events: "queue.Queue[JobEvent]" = queue.Queue()
    runner = JobRunner(_python("import time; time.sleep(60)", tmp_path, cancel_policy=CancelPolicy.TERMINATE), events)
    runner.cancel()
    runner.start()
    last = events.get(timeout=20)
    assert isinstance(last, JobFinished) and last.cancelled


def test_events_are_not_delivered_through_callbacks_on_the_worker_thread(tmp_path: Path) -> None:
    """The consumer takes events out of the queue on its own thread; nothing is called back."""
    events: "queue.Queue[JobEvent]" = queue.Queue()
    runner = JobRunner(_python("print('x')", tmp_path), events)
    runner.start()
    event = events.get(timeout=20)
    assert isinstance(event, JobOutput) and threading.current_thread() is threading.main_thread()


def test_a_runner_runs_only_once(tmp_path: Path) -> None:
    events: "queue.Queue[JobEvent]" = queue.Queue()
    runner = JobRunner(_python("pass", tmp_path), events)
    runner.start()
    with pytest.raises(RuntimeError):
        runner.start()
