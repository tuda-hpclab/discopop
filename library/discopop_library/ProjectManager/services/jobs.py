# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Running a command as a background job and reporting what it does as typed events.

One class replaces the hand-written ``threading.Thread`` + subprocess copies of the GUI panels. The job runs on a
worker thread and puts its events into a ``queue.Queue``; whoever owns the queue (a GUI adapter, a test) takes them
out on its own thread, so no callback ever runs on the worker thread. Threads plus subprocess, no asyncio.
"""

import os
import queue
import signal
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Union


class CancelPolicy(Enum):
    """How a running job is asked to stop."""

    # like Ctrl+C: the tool finishes gracefully and saves what it has
    SIGINT = "sigint"
    # SIGINT to the whole process group, as Ctrl+C in a terminal sends it: the programs the tool started stop as well
    # (autotuner, patch repair); the job is started in a new session
    SIGINT_GROUP = "sigint_group"
    # SIGTERM to the whole process group; the job is started in a new session (explorer)
    SIGTERM_GROUP = "sigterm_group"
    # Popen.terminate()
    TERMINATE = "terminate"


@dataclass(frozen=True)
class JobSpec:
    command: List[str]
    cwd: str
    cancel_policy: CancelPolicy = CancelPolicy.TERMINATE
    env: Optional[Mapping[str, str]] = None
    # start the process in a new session (required for SIGINT_GROUP and SIGTERM_GROUP)
    new_session: bool = False


@dataclass(frozen=True)
class JobOutput:
    """One line of the combined stdout and stderr of the job, without its line ending."""

    line: str


@dataclass(frozen=True)
class JobFinished:
    returncode: int
    # whether cancel() was called before the job ended
    cancelled: bool


@dataclass(frozen=True)
class JobFailedToStart:
    error: str


JobEvent = Union[JobOutput, JobFinished, JobFailedToStart]


def is_terminal(event: Any) -> bool:
    """Whether no further event follows ``event``."""
    return isinstance(event, (JobFinished, JobFailedToStart, WorkFinished))


def _signal_process(process: "subprocess.Popen[str]", policy: CancelPolicy) -> None:
    """Ask ``process`` to stop as ``policy`` says; a process that ended in the meantime is left alone."""
    if process.poll() is not None:
        return
    try:
        if policy is CancelPolicy.SIGINT:
            process.send_signal(signal.SIGINT)
        elif policy is CancelPolicy.SIGINT_GROUP:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
            except (ProcessLookupError, OSError):
                process.send_signal(signal.SIGINT)
        elif policy is CancelPolicy.SIGTERM_GROUP:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                process.terminate()
        else:
            process.terminate()
    except OSError:
        pass


def let_children_receive_sigint() -> None:
    """Undo an ignored SIGINT this process was started with; call from the main thread before starting jobs.

    A shell that runs a program in the background starts it with SIGINT ignored, and the jobs would inherit that:
    the SIGINT of their Stop would never arrive. A handled signal is reset to its default in a started program.
    """
    if signal.getsignal(signal.SIGINT) == signal.SIG_IGN:
        signal.signal(signal.SIGINT, signal.default_int_handler)


def _start_process(spec: JobSpec) -> "subprocess.Popen[str]":
    env: Optional[Dict[str, str]] = dict(spec.env) if spec.env is not None else None
    return subprocess.Popen(
        spec.command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=spec.cwd,
        env=env,
        start_new_session=spec.new_session,
    )


class JobRunner:
    """Runs one :class:`JobSpec` on a worker thread, once.

    Events are put into ``events``; the last one is a :class:`JobFinished` or :class:`JobFailedToStart`.
    """

    def __init__(self, spec: JobSpec, events: "queue.Queue[JobEvent]") -> None:
        self._spec = spec
        self._events = events
        self._lock = threading.Lock()
        self._process: Optional["subprocess.Popen[str]"] = None
        self._cancel_requested = False
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("a JobRunner runs its job only once")
        self._started = True
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        """Ask the job to stop, as its cancel policy says. Safe to call at any time and from any thread."""
        with self._lock:
            self._cancel_requested = True
            process = self._process
        if process is not None:
            self._signal(process)

    @property
    def cancel_requested(self) -> bool:
        with self._lock:
            return self._cancel_requested

    def _signal(self, process: "subprocess.Popen[str]") -> None:
        _signal_process(process, self._spec.cancel_policy)

    def _run(self) -> None:
        try:
            try:
                process = _start_process(self._spec)
            except OSError as e:
                self._events.put(JobFailedToStart(str(e)))
                return
            with self._lock:
                self._process = process
                cancel_already_requested = self._cancel_requested
            if cancel_already_requested:
                self._signal(process)
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    self._events.put(JobOutput(line.rstrip("\n")))
                process.wait()
            finally:
                with self._lock:
                    self._process = None
            self._events.put(JobFinished(process.returncode, self.cancel_requested))
        except Exception as e:  # never leave the consumer waiting for a terminal event
            self._events.put(JobFailedToStart(str(e)))


class StatusKind(Enum):
    """The tone of a status line; the GUI maps it to a colour."""

    BUSY = "busy"
    IDLE = "idle"
    OK = "ok"
    FAIL = "fail"
    STOP = "stop"


@dataclass(frozen=True)
class WorkOutput:
    """Text for the console of the panel."""

    text: str


@dataclass(frozen=True)
class WorkStatus:
    """A new text for the status line."""

    text: str
    kind: StatusKind


@dataclass(frozen=True)
class WorkNotice:
    """Something the user has to be told in a dialog once the work has been shown so far."""

    title: str
    message: str


@dataclass(frozen=True)
class WorkFinished:
    """The last event of a piece of work: its return value, or the exception that ended it."""

    result: Any
    error: Optional[str]


WorkEvent = Union[WorkOutput, WorkStatus, WorkNotice, WorkFinished]


class WorkContext:
    """What a piece of work running on a :class:`WorkRunner` can do; safe to use from the worker thread.

    The work reports through ``output`` / ``status`` / ``notify`` and never touches a widget. It stops
    when ``cancel_event`` is set. A subprocess it starts through ``register_process`` or ``run_command`` is
    terminated by ``WorkRunner.cancel``.
    """

    def __init__(self, events: "queue.Queue[WorkEvent]", cancel_event: threading.Event) -> None:
        self._events = events
        self.cancel_event = cancel_event
        self._lock = threading.Lock()
        self._process: Optional["subprocess.Popen[Any]"] = None
        self._policy = CancelPolicy.TERMINATE

    def output(self, text: str) -> None:
        self._events.put(WorkOutput(text))

    def status(self, text: str, kind: StatusKind = StatusKind.BUSY) -> None:
        self._events.put(WorkStatus(text, kind))

    def notify(self, title: str, message: str) -> None:
        self._events.put(WorkNotice(title, message))

    def register_process(self, process: "subprocess.Popen[Any]", policy: CancelPolicy = CancelPolicy.TERMINATE) -> None:
        """Make ``cancel`` stop ``process`` (a process started by a library function that reports it)."""
        with self._lock:
            self._process = process
            self._policy = policy
        if self.cancel_event.is_set():
            _signal_process(process, policy)

    def clear_process(self) -> None:
        with self._lock:
            self._process = None

    def run_command(self, spec: JobSpec, on_line: Callable[[str], None]) -> int:
        """Run ``spec`` to its end, passing every output line to ``on_line``; returns the return code.

        Raises OSError when the command cannot be started.
        """
        process = _start_process(spec)
        self.register_process(process, spec.cancel_policy)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                on_line(line.rstrip("\n"))
            process.wait()
        finally:
            self.clear_process()
        return process.returncode

    def terminate_running_process(self) -> None:
        with self._lock:
            process, policy = self._process, self._policy
        if process is not None:
            _signal_process(process, policy)


class WorkRunner:
    """Runs a function on a worker thread, once, and reports through the events of its :class:`WorkContext`.

    The last event is a :class:`WorkFinished`; an exception of the work is reported there instead of being lost.
    This replaces the ``threading.Thread`` + ``self.after(0, ...)`` idiom: the consumer of ``events`` is the only
    one touching widgets.
    """

    def __init__(self, work: Callable[[WorkContext], Any], events: "queue.Queue[WorkEvent]") -> None:
        self._work = work
        self._events = events
        self._cancel_event = threading.Event()
        self._context = WorkContext(events, self._cancel_event)
        self._started = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def start(self) -> None:
        if self._started:
            raise RuntimeError("a WorkRunner runs its work only once")
        self._started = True
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        """Ask the work to stop: sets its cancel event and terminates the process it has registered."""
        self._cancel_event.set()
        self._context.terminate_running_process()

    def _run(self) -> None:
        try:
            result = self._work(self._context)
        except Exception as e:  # a crash of the work must not leave the consumer waiting
            self._events.put(WorkFinished(None, str(e) or type(e).__name__))
            return
        self._events.put(WorkFinished(result, None))
