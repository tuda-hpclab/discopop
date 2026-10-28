# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import datetime
import json
import logging
import os
import re
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

from mcp.types import TextContent

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

if TYPE_CHECKING:
    from discopop_explorer.side_effects.analysis import SideEffectIndex

logger = logging.getLogger("discopop-mcp")


# One line of a compiler, a runtime or a program that reports a problem: "warning: ...", "error: ...",
# "OMP: Warning #96: ...".
_DIAGNOSTIC = re.compile(r"\b(warning|error|fatal error)\b(\s*#\d+)?\s*:", re.IGNORECASE)
MAX_DIAGNOSTIC_CHARS = 200
# Warnings a step of gather_data lists in its result; the number of the rest is given.
MAX_WARNINGS = 5


def diagnostics(*outputs: Any) -> list[str]:
    """The warning and error lines of the outputs of a build or a run, each once, in order."""
    found: list[str] = []
    for output in outputs:
        for line in str(output or "").splitlines():
            line = line.strip()
            if _DIAGNOSTIC.search(line) and line not in found:
                found.append(line if len(line) <= MAX_DIAGNOSTIC_CHARS else line[:MAX_DIAGNOSTIC_CHARS] + "...")
    return found


def warning_fields(*outputs: Any) -> dict[str, Any]:
    """`warnings` for the result of a step that succeeded: the first warning lines and how many more there are.

    Empty when there are none, so that a step without warnings says nothing.
    """
    warnings = [line for line in diagnostics(*outputs) if not re.search(r"\berror\b", line, re.IGNORECASE)]
    if not warnings:
        return {}
    listed = warnings[:MAX_WARNINGS]
    if len(warnings) > len(listed):
        listed.append(f"{len(warnings) - len(listed)} more warnings.")
    return {"warnings": listed}


# How much of a script's stdout or stderr a tool returns. The end of the output is
# where a compiler error, a failed assertion or a crash shows up; a full log is what
# made a single call cost tens of thousands of tokens.
OUTPUT_TAIL_CHARS = 2000


def tail_of_output(text: Any) -> tuple[str, Optional[int]]:
    """The end of `text`, and its full length if it was cut."""
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    if len(text) <= OUTPUT_TAIL_CHARS:
        return text, None
    return text[-OUTPUT_TAIL_CHARS:], len(text)


# Printed by the placeholder compile.sh that initialize_discopop_directory writes; its
# presence is what marks a compile.sh as not configured yet. Testing for "exit 1"
# instead would misread every real script that bails out with `|| exit 1`.
COMPILE_SCRIPT_PLACEHOLDER_MARKER = "compile.sh has not been configured yet"


def compile_script_configured(configs_dir: Path) -> bool:
    """Whether the shared compile.sh exists and is not the initial placeholder."""
    compile_sh = configs_dir / "compile.sh"
    try:
        return compile_sh.is_file() and COMPILE_SCRIPT_PLACEHOLDER_MARKER not in compile_sh.read_text()
    except OSError:
        return False


def configuration_names(configs_dir: Path) -> list[str]:
    """The execution configurations that can be run, i.e. that have an execute.sh."""
    if not configs_dir.is_dir():
        return []
    return sorted(d.name for d in configs_dir.iterdir() if d.is_dir() and (d / "execute.sh").is_file())


def invalid_configuration_name(config_name: str) -> Optional[str]:
    """Why `config_name` cannot name a configuration, or None if it can.

    A configuration is a directory directly under configs/, and its name is joined onto
    that path to read, run, overwrite and delete scripts. Anything but a plain name --
    "..", "a/../b", an absolute path -- would reach other directories.
    """
    if (
        not config_name
        or config_name.startswith(".")
        or "/" in config_name
        or os.sep in config_name
        or Path(config_name).name != config_name
    ):
        return f"Invalid config_name '{config_name}'. Must be a plain name without path separators or leading dots."
    return None


def unknown_configuration_message(configs_dir: Path, config_name: str) -> str:
    """Why `config_name` cannot be used, with the names that can.

    Listing the defined names in the error itself saves the round trip a caller would
    otherwise need to find out what it should have passed.
    """
    names = configuration_names(configs_dir)
    defined = (
        f"Defined configurations: {', '.join(names)}."
        if names
        else "No execution configuration is defined yet; create one with create_execution_configuration."
    )
    return (
        f"Configuration '{config_name}' not found. {defined} " "get_configurations shows each configuration's scripts."
    )


def setup_next_step(configs_dir: Path) -> str:
    """The next step towards a project gather_data can run on, given what is set up.

    Derived from the project's state rather than from the tool that was just called:
    the setup tools can be called in any order and repeated, so the step that is
    still missing is the one worth naming.
    """
    if not configs_dir.is_dir():
        return "Call initialize_discopop_directory to set up the project."
    if not compile_script_configured(configs_dir):
        return "Call set_compile_script to describe how the project is built."
    names = configuration_names(configs_dir)
    if not names:
        return "Call create_execution_configuration to describe how the compiled program is run."
    hotspot_hint = (
        f", passing hotspot_config_names (e.g. {names[:2]}) for the hotspot ranking of the suggestions"
        if len(names) >= 2
        else (
            "; adding a second configuration with a different input size and passing it as "
            "hotspot_config_names improves the hotspot ranking of the suggestions"
        )
    )
    return (
        f"The project is set up. Call gather_data with config_name set to one of {names} "
        f"to profile it and detect parallelization opportunities{hotspot_hint}."
    )


# Receives (progress, total, message) for the tool call currently running.
ProgressReporter = Callable[[float, Optional[float], Optional[str]], None]

# How often a long-running step reports that it is still alive. Each notification
# also lets a client that resets its request timeout on progress keep waiting.
HEARTBEAT_INTERVAL_SECONDS = 15.0
# How long a process gets to shut down after SIGTERM before SIGKILL.
KILL_GRACE_SECONDS = 10.0


def _stat(pid: int) -> Optional[list[str]]:
    """The fields of /proc/<pid>/stat after the command name: state, ppid, pgrp, session, ..."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            # the command name in parentheses may contain spaces
            return f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


# index of the start time (field 22 of /proc/<pid>/stat) in what _stat returns
_START_TIME = 19


def _process_table() -> dict[int, list[str]]:
    """_stat of every process, by pid."""
    table: dict[int, list[str]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return table
    for entry in entries:
        if entry.isdigit():
            fields = _stat(int(entry))
            if fields is not None and len(fields) > _START_TIME:
                table[int(entry)] = fields
    return table


def _descendants(pid: int, table: Optional[dict[int, list[str]]] = None) -> list[int]:
    """The processes `pid` started, directly or not, from /proc; empty where there is none."""
    children: dict[int, list[int]] = {}
    for child, fields in (table if table is not None else _process_table()).items():
        children.setdefault(int(fields[1]), []).append(child)
    found: list[int] = []
    pending = [pid]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child)
    return found


def _tree(proc: "subprocess.Popen[Any]") -> dict[int, str]:
    """The processes `proc` started, by pid, each with its start time.

    Found as `proc`'s descendants and, for a `proc` started in a session of its own, as
    the members of that session: a process whose parent exited is no longer a descendant,
    but stays in the session even where it moved to a group of its own. The start time
    tells a process from a later one that reused its pid.
    """
    table = _process_table()
    pids = set(_descendants(proc.pid, table)) if proc.poll() is None else set()
    # once `proc` is reaped, a process with its pid is a stranger, and so is its session
    if proc.poll() is None or proc.pid not in table:
        pids.update(pid for pid, fields in table.items() if int(fields[3]) == proc.pid and pid != proc.pid)
    return {pid: table[pid][_START_TIME] for pid in pids if pid in table}


def _alive(pid: int, start_time: Optional[str] = None) -> bool:
    """Whether `pid` still runs, and is the process started at `start_time` if given.

    A zombie only waits to be reaped and counts as gone.
    """
    fields = _stat(pid)
    if fields is None or fields[0] == "Z":
        return False
    return start_time is None or (len(fields) > _START_TIME and fields[_START_TIME] == start_time)


def _own_group(proc: "subprocess.Popen[Any]") -> Optional[int]:
    """`proc`'s process group if it leads one, i.e. was started in its own session.

    Never the server's group: a child started without a session of its own shares it,
    and signalling that group would take down the server.
    """
    if proc.poll() is not None:
        return None
    try:
        return proc.pid if os.getpgid(proc.pid) == proc.pid else None
    except OSError:
        return None


def _signal_tree(
    proc: "subprocess.Popen[Any]", group: Optional[int], known: dict[int, str], sig: int
) -> dict[int, str]:
    """Send `sig` to `proc` and everything it started; returns the processes signalled.

    Both by group and process by process: a descendant may have moved to a group of its
    own (GNU timeout, which runs the compile and execute scripts, does), and one whose
    parent exited is no longer found as a descendant.
    """
    pids = {**known, **_tree(proc)}
    if group is not None and proc.poll() is None:
        try:
            os.killpg(group, sig)
        except OSError:
            pass
    # a pid only counts while the process found under it runs, so that no reused pid is signalled
    for pid in [p for p, start_time in pids.items() if _alive(p, start_time)]:
        try:
            os.kill(pid, sig)
        except OSError:
            pass
    if proc.poll() is None:
        try:
            proc.send_signal(sig)
        except OSError:
            pass
    return pids


def _wait_for_tree(proc: "subprocess.Popen[Any]", pids: dict[int, str], timeout: float) -> bool:
    """Wait until `proc` and `pids` have ended; False if some still run after `timeout`."""
    deadline = time.monotonic() + timeout
    while True:
        if proc.poll() is not None and not any(_alive(pid, start_time) for pid, start_time in pids.items()):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def terminate_process_tree(proc: "subprocess.Popen[Any]", grace_seconds: float = KILL_GRACE_SECONDS) -> None:
    """Stop `proc` and every process it started: SIGTERM, then SIGKILL after the grace period.

    Stopping only `proc` would leave the compile or execute scripts it runs behind, and
    those are what takes the time.
    """
    group = _own_group(proc)
    pids = _signal_tree(proc, group, {}, signal.SIGTERM)
    if _wait_for_tree(proc, pids, grace_seconds):
        return
    pids = _signal_tree(proc, group, pids, signal.SIGKILL)
    _wait_for_tree(proc, pids, grace_seconds)


@dataclass(frozen=True)
class SideEffectDataProblem:
    """Why the side effect data of a project cannot be queried, worded for the caller.

    ``reason`` is one of "missing" (also after a pattern detection with
    --ignore-dependency-states, which writes no export), "unreadable" (also: written in
    another format version), "stale" and "ignore_dependency_states" (an export written
    by an older explorer with --ignore-dependency-states).
    """

    reason: str
    message: str
    next_step: str


def dynamic_dependencies_path(project_path: str) -> Path:
    """The profiler's dependency file, as discopop_explorer reads it by default (--dep-file)."""
    return Path(project_path) / ".discopop" / "profiler" / "dynamic_dependencies.txt"


def _same_dependency_file(recorded: Any, current: Any) -> bool:
    """Whether the dependency file the export recorded is the current one (both may be absent)."""
    if recorded is None or current is None:
        return recorded is None and current is None
    try:
        return float(recorded["mtime"]) == float(current["mtime"]) and int(recorded["size"]) == int(current["size"])
    except (KeyError, TypeError, ValueError):
        return False


class ToolContext:
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        # project_path → (file_id_to_path, FileMapping.txt mtime)
        self._file_mapping_cache: dict[str, tuple[dict[int, Path], float]] = {}
        # project_path → ((export mtime_ns, size), ignore_dependency_states, dependency_file info, index).
        # The index is None for an export that cannot be queried (ignore_dependency_states).
        self._side_effect_cache: dict[str, tuple[tuple[int, int], bool, Any, Optional["SideEffectIndex"]]] = {}
        # Set by the server for the duration of one tool call whose client asked for
        # progress. Tool calls run one at a time, so a single slot is enough.
        self._progress_reporter: Optional[ProgressReporter] = None
        self._last_progress: Optional[float] = None
        # What was reported last, for heartbeats to repeat: (total, message, when)
        self._last_report: Optional[tuple[Optional[float], Optional[str], float]] = None
        self._progress_lock = threading.Lock()
        # Cancellation of the current call, see cancellable() and cancel(). The processes
        # the call started are registered, so that a cancel can stop them.
        self._cancel_event: Optional[threading.Event] = None
        self._processes: list["subprocess.Popen[Any]"] = []
        self._cancel_lock = threading.Lock()

    @contextmanager
    def cancellable(self) -> Iterator[None]:
        """Make the block a call that cancel() can stop."""
        with self._cancel_lock:
            self._cancel_event = threading.Event()
            self._processes = []
        try:
            yield
        finally:
            with self._cancel_lock:
                self._cancel_event = None
                self._processes = []

    @property
    def cancelled(self) -> bool:
        """Whether the client cancelled the current call. Handlers check it between steps."""
        with self._cancel_lock:
            return self._cancel_event is not None and self._cancel_event.is_set()

    def cancel(self) -> None:
        """Stop the current call: mark it cancelled and stop the processes it registered.

        Called from the event loop while the handler keeps running in its thread; the
        handler sees its processes fail, checks `cancelled` and cleans up.
        """
        with self._cancel_lock:
            if self._cancel_event is None or self._cancel_event.is_set():
                return
            self._cancel_event.set()
            processes = [p for p in self._processes if p.poll() is None]
        for proc in processes:
            threading.Thread(target=terminate_process_tree, args=(proc,), daemon=True).start()

    def track_process(self, proc: "subprocess.Popen[Any]") -> None:
        """Register a process of the current call, so that a cancel stops it.

        A process started after the cancel is stopped right away: the handler started it
        between its last look at `cancelled` and the cancel. Processes that clean up after a
        cancel (e.g. rebuilding the project without instrumentation) have to be able to
        finish, so they are not registered at all.
        """
        with self._cancel_lock:
            if self._cancel_event is None:
                return
            stop = self._cancel_event.is_set()
            if not stop:
                self._processes = [p for p in self._processes if p.poll() is None] + [proc]
        if stop:
            terminate_process_tree(proc)

    def run_process(
        self, cmd: list[str], timeout: Optional[float] = None, cleanup: bool = False, **kwargs: Any
    ) -> "subprocess.CompletedProcess[str]":
        """subprocess.run(cmd, capture_output=True, text=True, timeout=...) that cancel() can stop.

        With `cleanup`, the process cleans up after a cancel and runs to its end regardless.
        """
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, **kwargs
        )
        if not cleanup:
            self.track_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process_tree(proc)
            try:
                # bounded: a process that survived the kill may still hold the pipes
                proc.communicate(timeout=KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)

    @contextmanager
    def reporting_progress(self, reporter: Optional[ProgressReporter]) -> Iterator[None]:
        """Route report_progress to `reporter` while the block runs."""
        with self._progress_lock:
            self._progress_reporter = reporter
            self._last_progress = None
            self._last_report = None
        try:
            yield
        finally:
            with self._progress_lock:
                self._progress_reporter = None
                self._last_progress = None
                self._last_report = None

    def report_progress(
        self, progress: float, total: Optional[float] = None, message: Optional[str] = None, _heartbeat: bool = False
    ) -> None:
        """Tell the client how far the current call is. A no-op if it did not ask.

        MCP requires every notification's progress to exceed the previous one, so a
        repeated value -- a heartbeat within the same step -- is nudged upwards.
        Never raises: a lost notification must not fail the tool call.
        """
        with self._progress_lock:
            reporter = self._progress_reporter
            if reporter is None:
                return
            if self._last_progress is not None and progress <= self._last_progress:
                progress = self._last_progress + 0.001
            self._last_progress = progress
            # No total given: the one reported before still applies.
            if total is None and self._last_report is not None:
                total = self._last_report[0]
            if not _heartbeat:
                self._last_report = (total, message, time.monotonic())
        try:
            reporter(progress, total, message)
        except Exception as error:  # pragma: no cover - depends on the transport
            logger.debug(f"Progress notification failed: {error}")

    def _repeat_last_report(self) -> Optional[tuple[float, Optional[float], str]]:
        """The last reported state, marked as still running since it was reported."""
        with self._progress_lock:
            last, progress = self._last_report, self._last_progress
        if last is None or progress is None:
            return None
        total, message, since = last
        return progress, total, f"{message or 'Running'} (still running, {time.monotonic() - since:.0f}s)"

    @contextmanager
    def heartbeat(
        self,
        describe: Optional[Callable[[], Optional[tuple[float, Optional[float], str]]]] = None,
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> Iterator[None]:
        """Report `describe()` every `interval` seconds while the block runs.

        For steps that block for minutes or hours without a natural point to report
        from, such as waiting for a subprocess. Without `describe`, the last state
        reported via report_progress is repeated with the time it has been running.
        """
        describe = describe or self._repeat_last_report
        if self._progress_reporter is None:
            yield
            return
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    state = describe()
                    if state is not None:
                        self.report_progress(*state, _heartbeat=True)
                except Exception as error:  # pragma: no cover - describe() is caller code
                    logger.debug(f"Progress heartbeat failed: {error}")

        thread = threading.Thread(target=beat, name="mcp-progress-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=interval)

    def log_to_file(self, project_path: str, marker: str, tool_name: str, message: str) -> None:
        """Append a timestamped entry to <project_path>/.discopop/mcp_server/log.txt.
        Never raises — logging failures must not affect tool execution.

        Only into a .discopop that exists: creating it would create a mistyped project_path,
        and mark a directory as a DiscoPoP project that was never initialized as one."""
        try:
            if not (Path(project_path) / ".discopop").is_dir():
                return
            log_dir = Path(project_path) / ".discopop" / "mcp_server"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{ts}  {marker:<8}  {tool_name:<40}  {message}\n"
            with open(log_dir / "log.txt", "a") as f:
                f.write(line)
        except Exception:
            pass

    def log_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        logger.info(f"→ Incoming call: {tool_name}")
        if self.debug:
            logger.debug(f"  Arguments: {json.dumps(arguments, indent=2)}")
        project_path = arguments.get("project_path", "")
        if project_path:
            # a script is a file of its own, written to the configuration; its size is enough here
            args_summary = ", ".join(
                f"{k}=<{len(v)} chars>" if k.endswith("script_body") and isinstance(v, str) else f"{k}={v!r}"
                for k, v in arguments.items()
            )
            self.log_to_file(project_path, "→ CALL", tool_name, args_summary)

    def log_response(self, tool_name: str, result: Any, project_path: str = "") -> None:
        logger.info(f"← Outgoing response: {tool_name}")
        if self.debug:
            logger.debug(f"  Result: {json.dumps(result if isinstance(result, dict) else str(result), indent=2)}")
        if isinstance(result, dict):
            if not project_path:
                return
            status = "error" if result.get("status") == "error" else "ok"
            extras = {
                k: v
                for k in (
                    "returncode",
                    "elapsed_time",
                    "patterns_found",
                    "hotspots_found",
                    "files_created",
                    "profiling_files",
                    "created_files",
                    "patches",
                )
                if (v := result.get(k)) is not None
            }
            summary = f"status={status}" + (
                ", "
                + ", ".join(
                    f"{k}={v!r}" if not isinstance(v, list) else f"{k}=[{len(v)} items]" for k, v in extras.items()
                )
                if extras
                else ""
            )
            self.log_to_file(project_path, "← RESULT", tool_name, summary)

    def log_action(self, project_path: str, tool_name: str, message: str) -> None:
        logger.debug(f"  Action [{tool_name}]: {message}")
        if project_path:
            self.log_to_file(project_path, "· ACTION", tool_name, message)

    def error(
        self, message: str, project_path: str = "", tool_name: str = "", next_step: Optional[str] = None
    ) -> list[TextContent]:
        result = {"status": "error", "message": message}
        if next_step:
            result["next_step"] = next_step
        if project_path and tool_name:
            self.log_to_file(project_path, "← RESULT", tool_name, f"status=error, message={message}")
        return [TextContent(type="text", text=json.dumps(result))]

    def make_pm_args(self, project_path: str, timeout_seconds: Optional[int] = None) -> ProjectManagerArguments:
        return ProjectManagerArguments(
            project_root=project_path,
            full_execute=False,
            list=False,
            execute_configurations="",
            execute_inplace=True,
            skip_cleanup=False,
            generate_report=False,
            show_report=False,
            initialize_directory=False,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="mcp",
            timeout_execution=float(timeout_seconds) if timeout_seconds is not None else None,
            timeout_compilation=float(timeout_seconds) if timeout_seconds is not None else None,
            timeout_validation=float(timeout_seconds) if timeout_seconds is not None else None,
            log_level="WARNING",
            write_log=False,
        )

    def get_file_mapping(self, project_path: str) -> Optional[dict[int, Path]]:
        """Return a cached file_id → Path mapping loaded from .discopop/FileMapping.txt.
        Reloads when the file is newer than the cache. Returns None if the file does not exist."""
        fmap_path = Path(project_path) / ".discopop" / "FileMapping.txt"
        if not fmap_path.exists():
            return None
        current_mtime = fmap_path.stat().st_mtime
        cached = self._file_mapping_cache.get(project_path)
        if cached is not None:
            mapping, cached_mtime = cached
            if cached_mtime == current_mtime:
                return mapping
        try:
            from discopop_library.PathManagement.PathManagement import load_file_mapping

            mapping = load_file_mapping(str(fmap_path))
            self._file_mapping_cache[project_path] = (mapping, current_mtime)
            logger.info(f"Loaded FileMapping for {project_path} into cache")
            return mapping
        except Exception as e:
            logger.warning(f"Failed to load FileMapping from {fmap_path}: {e}")
            return None

    def get_side_effect_index(
        self, project_path: str
    ) -> tuple[Optional["SideEffectIndex"], Optional[SideEffectDataProblem]]:
        """The SideEffectIndex of the project's side effect export, or why there is none.

        Cached per project and reloaded when the export file changes (mtime or size). The
        staleness test against the profiler's dynamic_dependencies.txt runs on every call:
        a new profiling run changes that file without touching the export.
        """
        from discopop_explorer.side_effects.analysis import SideEffectIndex
        from discopop_explorer.side_effects.schema import (
            ExportFormatError,
            dependency_file_info,
            export_path,
            load_export,
        )

        path = export_path(project_path)
        try:
            stat = path.stat()
        except OSError:
            self._side_effect_cache.pop(project_path, None)
            # also the case after a pattern detection with --ignore-dependency-states (e.g. from the
            # GUI): the explorer then writes no export and removes an earlier one
            return None, SideEffectDataProblem(
                "missing",
                "No side effect data found for this project: gather_data has not run yet, or the last "
                "pattern detection ran with --ignore-dependency-states, which records none. Run gather_data.",
                "Run gather_data; its pattern detection step records the side effect data.",
            )
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._side_effect_cache.get(project_path)
        if cached is None or cached[0] != key:
            try:
                export = load_export(path)
            except ExportFormatError as e:
                self._side_effect_cache.pop(project_path, None)
                return None, SideEffectDataProblem(
                    "unreadable",
                    f"The side effect data cannot be used ({e}). Run gather_data again.",
                    "Run gather_data again to rebuild it with the installed DiscoPoP version.",
                )
            ignore_states = bool(export.get("ignore_dependency_states", False))
            index = None if ignore_states else SideEffectIndex(export)
            cached = (key, ignore_states, export.get("dependency_file"), index)
            self._side_effect_cache[project_path] = cached
            logger.info(f"Loaded side effect data for {project_path} into cache")
        _key, ignore_states, recorded_dependency_file, index = cached

        current = dependency_file_info(dynamic_dependencies_path(project_path))
        if not _same_dependency_file(recorded_dependency_file, current):
            return None, SideEffectDataProblem(
                "stale",
                "The side effect data is stale: it was built from other profiling data than the current "
                "dynamic_dependencies.txt. Run gather_data again.",
                "Run gather_data again to rebuild the side effect data from the current profiling data.",
            )
        if ignore_states or index is None:
            return None, SideEffectDataProblem(
                "ignore_dependency_states",
                "The last pattern detection ran with --ignore-dependency-states, which drops the "
                "call path information that attributes accesses to function calls, so side effects "
                "cannot be computed from it. Run gather_data again.",
                "Run gather_data again; it runs the pattern detection with dependency states.",
            )
        return index, None

    @staticmethod
    def newest_source_mtime(project_path: str) -> Optional[float]:
        """Return the mtime of the most recently modified source file under project_path,
        excluding the .discopop subtree. Returns None if no source files are found."""
        return max(ToolContext.source_mtimes(project_path).values(), default=None)

    @staticmethod
    def source_mtimes(project_path: str) -> dict[Path, float]:
        """The mtime of every source file under project_path.

        Not searched: the .discopop subtree, version control, and build trees. A CMake build tree
        (a directory with a CMakeCache.txt, or CMakeFiles) holds generated sources such as
        CMakeCCompilerId.c that every build rewrites, so counting them would mark the analysis stale
        right after the pipeline's own build.
        """
        source_exts = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh"}
        ignored_dirs = {".discopop", ".git", "CMakeFiles"}
        mtimes: dict[Path, float] = {}
        for dirpath, dirnames, filenames in os.walk(project_path):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in ignored_dirs and not os.path.isfile(os.path.join(dirpath, d, "CMakeCache.txt"))
            ]
            for name in filenames:
                if os.path.splitext(name)[1].lower() in source_exts:
                    f = Path(dirpath) / name
                    try:
                        mtimes[f] = f.stat().st_mtime
                    except OSError:
                        continue  # removed while walking
        return mtimes

    @staticmethod
    def fmt_ts(mtime: float) -> str:
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def extract_source_from_patch(patch_content: str) -> Optional[str]:
        """Extract the original source file path from the --- line of a unified diff."""
        for line in patch_content.splitlines():
            if line.startswith("--- "):
                path_part = line[4:].split("\t")[0].strip()
                if path_part and path_part != "/dev/null":
                    return path_part
        return None
