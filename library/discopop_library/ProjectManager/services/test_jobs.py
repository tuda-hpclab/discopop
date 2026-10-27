# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, List

import pytest

from discopop_library.ProjectManager.services.jobs import (
    CancelPolicy,
    JobEvent,
    JobFailedToStart,
    JobFinished,
    JobOutput,
    JobRunner,
    JobSpec,
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkNotice,
    WorkOutput,
    WorkRunner,
    WorkStatus,
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
    [
        (CancelPolicy.SIGINT, False),
        (CancelPolicy.SIGINT_GROUP, True),
        (CancelPolicy.SIGTERM_GROUP, True),
        (CancelPolicy.TERMINATE, False),
    ],
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


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_sigint_to_the_group_stops_what_the_job_started(tmp_path: Path) -> None:
    # like the autotuner running a measured program: the grandchild has to stop as well, as on Ctrl+C in a terminal
    code = (
        "import subprocess, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        "print(child.pid, flush=True)\n"
        "try:\n"
        "    child.wait()\n"
        "except KeyboardInterrupt:\n"
        "    pass\n"
    )
    events: "queue.Queue[JobEvent]" = queue.Queue()
    runner = JobRunner(_python(code, tmp_path, cancel_policy=CancelPolicy.SIGINT_GROUP, new_session=True), events)
    runner.start()
    first = events.get(timeout=20)
    assert isinstance(first, JobOutput)
    grandchild = int(first.line)
    try:
        runner.cancel()
        last = events.get(timeout=20)
        while not is_terminal(last):
            last = events.get(timeout=20)
        assert isinstance(last, JobFinished) and last.cancelled
        deadline = time.time() + 10
        while _alive(grandchild) and time.time() < deadline:
            time.sleep(0.05)
        assert not _alive(grandchild)
    finally:
        if _alive(grandchild):
            os.kill(grandchild, signal.SIGKILL)


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


# ---- WorkRunner ---------------------------------------------------------------------------------------------


def _collect(events: "queue.Queue[WorkEvent]") -> List[WorkEvent]:
    result: List[WorkEvent] = []
    while True:
        event = events.get(timeout=20)
        result.append(event)
        if isinstance(event, WorkFinished):
            return result


def test_work_reports_through_its_context_and_returns_a_result() -> None:
    def work(ctx: WorkContext) -> int:
        ctx.output("a\n")
        ctx.status("busy", StatusKind.BUSY)
        ctx.notify("Title", "Message")
        return 7

    events: "queue.Queue[WorkEvent]" = queue.Queue()
    WorkRunner(work, events).start()
    assert _collect(events) == [
        WorkOutput("a\n"),
        WorkStatus("busy", StatusKind.BUSY),
        WorkNotice("Title", "Message"),
        WorkFinished(7, None),
    ]


def test_an_exception_of_the_work_is_reported() -> None:
    def work(ctx: WorkContext) -> None:
        raise ValueError("boom")

    events: "queue.Queue[WorkEvent]" = queue.Queue()
    WorkRunner(work, events).start()
    assert _collect(events) == [WorkFinished(None, "boom")]


def test_cancel_sets_the_event_and_terminates_the_running_command(tmp_path: Path) -> None:
    started = threading.Event()

    def work(ctx: WorkContext) -> int:
        spec = _python("import time; print('ready', flush=True); time.sleep(60)", tmp_path)
        return ctx.run_command(spec, lambda line: started.set() if line == "ready" else None)

    events: "queue.Queue[WorkEvent]" = queue.Queue()
    runner = WorkRunner(work, events)
    runner.start()
    assert started.wait(20)
    runner.cancel()
    finished = _collect(events)[-1]
    assert isinstance(finished, WorkFinished) and finished.error is None
    assert finished.result != 0
    assert runner.cancel_requested


def test_a_process_registered_after_the_cancel_is_terminated_at_once(tmp_path: Path) -> None:
    import subprocess

    events: "queue.Queue[WorkEvent]" = queue.Queue()
    registered = threading.Event()
    release = threading.Event()

    def work(ctx: WorkContext) -> Any:
        release.wait(20)
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
        ctx.register_process(process)
        registered.set()
        return process.wait()

    runner = WorkRunner(work, events)
    runner.start()
    runner.cancel()
    release.set()
    finished = _collect(events)[-1]
    assert isinstance(finished, WorkFinished) and finished.result != 0


_IGNORING_PARENT = """
import signal, subprocess, sys
from discopop_library.ProjectManager.services.jobs import let_children_receive_sigint
if sys.argv[1] == "fixed":
    let_children_receive_sigint()
child = subprocess.Popen(["sleep", "30"])
child.send_signal(signal.SIGINT)
try:
    print(child.wait(timeout=5))
except subprocess.TimeoutExpired:
    child.kill()
    print("ignored")
"""


@pytest.mark.parametrize("variant,expected", [("unfixed", "ignored"), ("fixed", str(-signal.SIGINT))])
def test_a_gui_started_with_sigint_ignored_can_still_stop_its_jobs(variant: str, expected: str) -> None:
    # a shell running the GUI in the background starts it with SIGINT ignored, which its children would inherit
    result = subprocess.run(
        [sys.executable, "-c", _IGNORING_PARENT, variant],
        capture_output=True,
        text=True,
        timeout=30,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN),
        # the checkout, not an installed copy
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])},
    )
    assert result.stdout.strip() == expected, result.stderr
