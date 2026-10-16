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
from typing import Dict, List, Mapping, Optional, Union


class CancelPolicy(Enum):
    """How a running job is asked to stop."""

    # like Ctrl+C: the tool finishes gracefully and saves what it has (autotuner, patch repair)
    SIGINT = "sigint"
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
    # start the process in a new session (required for SIGTERM_GROUP)
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


def is_terminal(event: JobEvent) -> bool:
    """Whether no further event follows ``event``."""
    return isinstance(event, (JobFinished, JobFailedToStart))


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
        if process.poll() is not None:
            return
        policy = self._spec.cancel_policy
        try:
            if policy is CancelPolicy.SIGINT:
                process.send_signal(signal.SIGINT)
            elif policy is CancelPolicy.SIGTERM_GROUP:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    process.terminate()
            else:
                process.terminate()
        except OSError:
            pass  # the process ended in the meantime

    def _run(self) -> None:
        try:
            env: Optional[Dict[str, str]] = dict(self._spec.env) if self._spec.env is not None else None
            try:
                process = subprocess.Popen(
                    self._spec.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=self._spec.cwd,
                    env=env,
                    start_new_session=self._spec.new_session,
                )
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
