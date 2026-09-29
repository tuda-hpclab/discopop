# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import json
import re
import shutil
import signal
import subprocess
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from filelock import FileLock

from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult, read_application_result
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution_time import (
    TIME_SOURCE_CONSOLE,
    TIME_SOURCE_FALLBACK,
    TIME_SOURCE_WALL_CLOCK,
    extract_execution_time,
)
from discopop_library.ProjectManager.configurations.repetitions import (
    SINGLE_MEASUREMENT,
    TIME_AGGREGATE_FAILED_RUN,
    TIME_AGGREGATE_MEDIAN,
    TIME_AGGREGATE_NOT_MEASURED,
    select_representative,
    validate_repetitions,
)

PATH = str

# Return code stored for a run that was never started because the requested
# parallelization suggestions could not be applied. It is deliberately not 0: such a
# record carries no measurement, and treating it as a successful run would report the
# unmodified sequential code as a parallel configuration without a speedup.
NOT_EXECUTED_RETURN_CODE = -1

logger = logging.getLogger("ConfigurationManager")


def _resolve_compiler(cmd: str, search_path: str) -> str:
    """Resolve an unversioned clang/clang++ to an installed versioned binary.

    Settings default CC/CXX to the unversioned ``clang``/``clang++`` names, but
    many distributions only ship versioned binaries (e.g. ``clang-21``) with no
    bare ``clang`` symlink. If ``cmd`` already resolves on ``search_path`` it is
    returned unchanged; if it is a bare ``clang``/``clang++`` that does not
    resolve, fall back to the highest ``clang-<N>``/``clang++-<N>`` found on
    ``search_path``. Anything else is returned unchanged so the build fails with
    its own error rather than being silently rewritten.
    """
    if shutil.which(cmd, path=search_path):
        return cmd
    if cmd not in ("clang", "clang++"):
        return cmd
    pattern = re.compile(re.escape(cmd) + r"-(\d+)$")
    best: Optional[Tuple[int, str]] = None
    for directory in (search_path or "").split(os.pathsep):
        if not directory or not os.path.isdir(directory):
            continue
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for name in entries:
            match = pattern.match(name)
            if match and shutil.which(name, path=search_path):
                version = int(match.group(1))
                if best is None or version > best[0]:
                    best = (version, name)
    return best[1] if best else cmd


class _RunOutcome(NamedTuple):
    """What one run of a script produced, before it is written to the results file.

    ``time`` is the measurement of interest -- the wall clock time, or what the
    program reported about itself when asked for -- and ``wall_clock_time`` is
    always the real duration of the process. The two coincide unless an
    execution time was read from the output.
    """

    returncode: int
    time: float
    wall_clock_time: float
    time_source: str
    stdout: str
    stderr: str
    timeout_expired: bool


def _run_once(
    script_path: PATH,
    project_copy_root_path: PATH,
    my_env: Dict[str, str],
    thread_count: int,
    timeout: Optional[float],
    execution_time_regex: Optional[str],
    process_started_callback: Optional[Callable[["subprocess.Popen[bytes]"], None]],
) -> _RunOutcome:
    """Run the script once and report what it took.

    Split out of :func:`execute_configuration` so that a measurement can be
    repeated (see
    :mod:`discopop_library.ProjectManager.configurations.repetitions`) without
    redoing everything around it: the project copy, the environment and the
    settings are prepared once and every repetition runs against them.
    """
    timeout_expired = False
    stdout = b""
    stderr = b""
    start = time.time()
    try:
        if timeout is None:
            cmd = f"/bin/bash {str(script_path)}"
        else:
            cmd = f"timeout {str(timeout)} /bin/bash {str(script_path)}"
        p = subprocess.Popen(
            cmd,
            cwd=project_copy_root_path,
            executable="/bin/bash",
            shell=True,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=my_env,
        )

        if process_started_callback is not None:
            process_started_callback(p)

        stdout, stderr = p.communicate()

    except subprocess.TimeoutExpired as tex:
        timeout_expired = True
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        print("KILLED PROCESS: ", p.pid)

    elapsed = round((time.time() - start), 3)

    # A program reporting its own execution time excludes what is of no interest
    # (setup, teardown, reading and writing files); prefer that value, but never
    # silently: a run whose pattern found nothing is reported as falling back to
    # the wall clock time, so a measurement is never mistaken for the other kind.
    wall_clock_time = elapsed
    time_source = TIME_SOURCE_WALL_CLOCK
    if execution_time_regex is not None and not timeout_expired:
        reported_time = extract_execution_time(
            stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), execution_time_regex
        )
        if reported_time is None:
            time_source = TIME_SOURCE_FALLBACK
            logger.warning(
                "Falling back to the wall clock time of "
                + os.path.basename(script_path)
                + ": its output did not report an execution time."
            )
        else:
            elapsed = round(reported_time, 3)
            time_source = TIME_SOURCE_CONSOLE
            logger.debug("-> execution time reported by the program: " + str(elapsed) + "s")

    decoded_stdout = stdout.decode("utf-8") if not timeout_expired else ""
    decoded_stderr = stderr.decode("utf-8") if not timeout_expired else ""

    logger.debug("-> return code: " + str(p.returncode))
    logger.debug("-> thread count: " + str(thread_count))
    logger.debug("-> stdout:\n" + decoded_stdout)
    logger.debug("-> stderr:\n" + decoded_stderr)
    logger.debug("-> elapsed time: " + str(elapsed) + "s")

    return _RunOutcome(
        returncode=p.returncode,
        time=elapsed,
        wall_clock_time=wall_clock_time,
        time_source=time_source,
        stdout=decoded_stdout,
        stderr=decoded_stderr,
        timeout_expired=timeout_expired,
    )


def execute_configuration(
    arguments: ProjectManagerArguments,
    project_copy_root_path: PATH,
    config_path: PATH,
    settings_path: PATH,
    script_path: PATH,
    thread_count: int,
    timeout: Optional[float] = None,
    process_started_callback: Optional[Callable[["subprocess.Popen[bytes]"], None]] = None,
    execution_time_regex: Optional[str] = None,
    measurement: Optional[Dict[str, Any]] = None,
    repetitions: int = SINGLE_MEASUREMENT,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Optional[Tuple[int, float, str, str]]:
    """Run one script of a configuration and record what it took.

    ``execution_time_regex``, when given, is searched for in the script's output
    and the value it finds is reported as the elapsed time in place of the
    measured wall clock time -- see
    :mod:`discopop_library.ProjectManager.configurations.execution_time`. Callers
    pass it only for ``execute.sh``: ``compile.sh`` and ``validate.sh`` run
    through this function too, but produce no measurement. The wall clock time is
    recorded alongside either way, and remains the reported time whenever the
    pattern finds nothing.

    ``repetitions`` runs the script that many times and reports the median of
    the measured times -- see
    :mod:`discopop_library.ProjectManager.configurations.repetitions`, which also
    explains why one of the runs is singled out rather than each field averaged
    separately. Callers pass it for ``execute.sh`` alone, for the same reason
    they pass ``execution_time_regex`` there alone: the other scripts produce no
    measurement, so repeating them would only cost time. Everything but the run
    itself -- the project copy, the environment, the settings -- is prepared once
    and shared by every repetition.

    ``measurement``, if given, is updated with the record written to
    ``execution_results.json``. A caller needing more than the reported time --
    the autotuner derives its per-candidate timeout from ``wall_clock_time``,
    which has to bound the whole process -- reads it from there rather than from
    the return value, whose shape many callers depend on.
    """
    # Checked before anything about the process is changed -- in particular before
    # the working directory is moved into the project copy below, which a raise
    # from further down would leave behind in a directory that is about to be
    # deleted.
    repetition_error = validate_repetitions(repetitions)
    if repetition_error is not None:
        raise ValueError("repetitions: " + repetition_error)

    # check prerequisites
    if not os.path.exists(settings_path):
        return None

    config_name = os.path.basename(config_path)
    settings_name = os.path.basename(settings_path)
    script_name = os.path.basename(script_path)

    config_path = config_path.replace(arguments.project_root, project_copy_root_path)
    settings_path = settings_path.replace(arguments.project_root, project_copy_root_path)
    script_path = script_path.replace(arguments.project_root, project_copy_root_path)
    project_copy_dp_path = os.path.join(project_copy_root_path, ".discopop")

    # get applied suggestions
    applied_suggestions = read_applied_suggestions(project_copy_dp_path)
    # ... and whether all *requested* suggestions actually made it into the code
    application_result = read_application_result(os.path.join(project_copy_dp_path, "patch_applicator"))

    # load environment settings
    logger.debug(
        "executing configuration: "
        + str(os.path.basename(config_path))
        + " --- "
        + str(os.path.basename(script_path))
        + " --- "
        + str(os.path.basename(settings_path))
    )
    with open(settings_path, "r") as f:
        settings = json.load(f)
    logger.debug("-> settings:\n" + str(settings))

    # prepare environment variables
    home_dir = os.getcwd()
    os.chdir(project_copy_root_path)
    my_env: Dict[str, str] = os.environ.copy()
    for key in settings:
        my_env[key] = settings[key]
    my_env["DP_PROJECT_ROOT_DIR"] = project_copy_root_path
    my_env["DOT_DISCOPOP"] = project_copy_dp_path
    my_env["OMP_NUM_THREADS"] = str(thread_count)

    # Ensure the PATH includes the directory where discopop tools are found
    import sys

    venv_bin = os.path.dirname(sys.executable)
    if venv_bin not in my_env.get("PATH", ""):
        my_env["PATH"] = venv_bin + os.pathsep + my_env.get("PATH", "")

    # Resolve unversioned clang/clang++ to an installed versioned binary when no
    # bare clang is on PATH (common on distros shipping only clang-<N>). Done
    # after PATH is finalized so the venv bin is included in the search.
    for compiler_key in ("CC", "CXX"):
        original = my_env.get(compiler_key, "")
        if not original:
            continue
        resolved = _resolve_compiler(original, my_env.get("PATH", ""))
        if resolved != original:
            logger.info("Resolved %s=%s to %s (no bare %s on PATH)", compiler_key, original, resolved, original)
            my_env[compiler_key] = resolved

    # print("MYENV:")
    # for key in my_env:
    #    print("--> ", key, " : ", my_env[key])

    outcomes: List[_RunOutcome] = []
    for repetition in range(repetitions):
        if repetitions > 1:
            logger.debug("-> repetition " + str(repetition + 1) + " of " + str(repetitions))
        outcome = _run_once(
            script_path,
            project_copy_root_path,
            my_env,
            thread_count,
            timeout,
            execution_time_regex,
            process_started_callback,
        )
        outcomes.append(outcome)
        # Asked between repetitions so that stopping a repeated run does not have
        # to wait for the remaining ones. Terminating the running process is the
        # caller's business (process_started_callback hands it over); this only
        # keeps the loop from starting another.
        if should_abort is not None and should_abort():
            logger.debug("-> stopping after " + str(repetition + 1) + " repetitions: aborted by the caller.")
            break
        # Repetitions exist to average the noise out of a *working* run. A
        # configuration that failed or ran into its timeout will do so again, so
        # running it another four times would only cost time -- and the entry
        # recorded below has to be that failure in either case.
        if outcome.returncode != 0 or outcome.timeout_expired:
            if repetition + 1 < repetitions:
                logger.debug(
                    "-> stopping after "
                    + str(repetition + 1)
                    + " of "
                    + str(repetitions)
                    + " repetitions: the run did not succeed."
                )
            break

    # What the median is taken over; narrowed below when a pattern was given and
    # only some repetitions matched it.
    usable = outcomes
    if outcomes[-1].returncode != 0 or outcomes[-1].timeout_expired:
        # The run that failed is what has to be reported: a median taken among the
        # repetitions that did succeed would describe the configuration as working.
        # Its time is that one run's, so it is not labelled as an aggregate either.
        representative = outcomes[-1]
        time_aggregate = TIME_AGGREGATE_FAILED_RUN
    else:
        # A repetition whose output did not report a time was measured by the wall
        # clock instead, which systematically includes the setup, teardown and file
        # I/O the pattern exists to exclude. Taking a median across the two would
        # let those runs bias the result upward -- and a program that only
        # intermittently prints its timing is exactly the flaky case repetitions are
        # meant to help with -- so they are left out of the choice. Unless none
        # reported a time at all: the wall clock times are then all there is, and
        # their median is what the run would have reported anyway.
        usable = [outcome for outcome in outcomes if outcome.time_source != TIME_SOURCE_FALLBACK]
        if usable and len(usable) < len(outcomes):
            logger.warning(
                str(len(outcomes) - len(usable))
                + " of "
                + str(len(outcomes))
                + " repetitions of "
                + os.path.basename(script_path)
                + " did not report an execution time; their wall clock times are excluded from the median."
            )
        if not usable:
            usable = outcomes
        representative = usable[select_representative([outcome.time for outcome in usable])]
        time_aggregate = TIME_AGGREGATE_MEDIAN
    if len(usable) > 1 and time_aggregate == TIME_AGGREGATE_MEDIAN:
        logger.debug(
            "-> reported time: "
            + str(representative.time)
            + "s ("
            + TIME_AGGREGATE_MEDIAN
            + " of "
            + str([outcome.time for outcome in usable])
            + ")"
        )

    # save execution results
    stored = _store_execution_result(
        arguments,
        config_name,
        script_name,
        settings_name,
        applied_suggestions,
        application_result,
        {
            "code": representative.returncode,
            "stdout": representative.stdout,
            "stderr": representative.stderr,
            "timeout_expired": representative.timeout_expired,
            "time": representative.time,
            "wall_clock_time": representative.wall_clock_time,
            "time_source": representative.time_source,
            "thread_count": thread_count,
            "executed": True,
            "repetitions": len(outcomes),
            "repetition_times": [outcome.time for outcome in outcomes],
            "repetition_wall_clock_times": [outcome.wall_clock_time for outcome in outcomes],
            # How each repetition's time came about, so a reader can tell which of
            # them the median was taken over: a "wall_clock_fallback" entry is
            # recorded but excluded from the choice above.
            "repetition_time_sources": [outcome.time_source for outcome in outcomes],
            "time_aggregate": time_aggregate,
        },
    )
    if measurement is not None:
        measurement.update(stored)

    os.chdir(home_dir)

    return (
        representative.returncode,
        representative.time,
        representative.stdout,
        representative.stderr,
    )


def read_applied_suggestions(dot_discopop_path: PATH) -> List[int]:
    """The suggestion ids the patch applicator actually put into the code."""
    applied_suggestions_file = os.path.join(dot_discopop_path, "patch_applicator", "applied_suggestions.json")
    if not os.path.exists(applied_suggestions_file):
        return []
    try:
        with open(applied_suggestions_file, "r") as f:
            applied: List[int] = json.load(f)["applied"]
            return applied
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def _execution_label(arguments: ProjectManagerArguments) -> str:
    label: str = "" + arguments.label_prefix
    if arguments.apply_suggestions == "auto":
        label += "auto"
    if arguments.apply_suggestions == "prm":
        label += "prm"
    return label


def _store_execution_result(
    arguments: ProjectManagerArguments,
    config_name: str,
    script_name: str,
    settings_name: str,
    applied_suggestions: List[int],
    application_result: Optional[PatchApplicationResult],
    measurement: Dict[str, Any],
) -> Dict[str, Any]:
    """Append one entry to ``execution_results.json``, replacing an equivalent one.

    ``requested_suggestions`` / ``failed_suggestions`` /
    ``suggestion_application_failed`` are stored next to the measurement so every
    consumer (Report tab, PDF/CSV reports) can tell a genuine measurement apart from
    a run of unmodified code. They are also part of the duplicate key: otherwise a
    failed application -- whose ``applied_suggestions`` is empty -- would overwrite
    the configuration's real no-suggestion baseline entry.
    """
    lock = FileLock(os.path.join(arguments.project_dir, "execution_results.json.lock"))
    with lock:

        execution_results_path = os.path.join(arguments.project_dir, "execution_results.json")
        execution_results: Dict[str, Any] = dict()
        if os.path.exists(execution_results_path):
            with open(execution_results_path, "r") as f:
                execution_results = json.load(f)

        if config_name not in execution_results:
            execution_results[config_name] = dict()
        if script_name not in execution_results[config_name]:
            execution_results[config_name][script_name] = dict()
        if settings_name not in execution_results[config_name][script_name]:
            execution_results[config_name][script_name][settings_name] = []

        label = _execution_label(arguments)
        requested_suggestions = [int(s) for s in application_result.requested] if application_result is not None else []
        failed_suggestions = [int(s) for s in application_result.unapplied] if application_result is not None else []

        result_dict: Dict[str, Any] = {
            "applied_suggestions": applied_suggestions,
            "requested_suggestions": requested_suggestions,
            "failed_suggestions": failed_suggestions,
            "suggestion_application_failed": bool(failed_suggestions),
            "label": label,
        }
        result_dict.update(measurement)

        # check for duplicates and overwrite them
        to_be_removed: List[int] = []
        for idx, entry in enumerate(execution_results[config_name][script_name][settings_name]):
            if entry["applied_suggestions"] != applied_suggestions:
                continue
            if entry.get("requested_suggestions", []) != requested_suggestions:
                continue
            if entry["thread_count"] != result_dict["thread_count"]:
                continue
            if entry["label"] != label:
                continue
            to_be_removed.append(idx)
        for idx in sorted(to_be_removed, reverse=True):
            del execution_results[config_name][script_name][settings_name][idx]
        execution_results[config_name][script_name][settings_name].append(result_dict)

        # overwrite execution results file
        with open(execution_results_path, "w+") as f:
            json.dump(execution_results, f, sort_keys=True, indent=4)

    return result_dict


def record_skipped_execution(
    arguments: ProjectManagerArguments,
    project_copy_root_path: PATH,
    config_path: PATH,
    settings_path: PATH,
    script_path: PATH,
    thread_count: int,
    application_result: PatchApplicationResult,
) -> Dict[str, Any]:
    """Record that a run was skipped because its suggestions could not be applied.

    Compiling and executing the copy would measure the *original* code, so the run is
    not started at all. A placeholder entry is written nonetheless: without it the
    case would be invisible in the Report tab and could not be told apart from a
    configuration that was never requested.
    """
    project_copy_dp_path = os.path.join(project_copy_root_path, ".discopop")
    return _store_execution_result(
        arguments,
        os.path.basename(config_path),
        os.path.basename(script_path),
        os.path.basename(settings_path),
        read_applied_suggestions(project_copy_dp_path),
        application_result,
        {
            "code": NOT_EXECUTED_RETURN_CODE,
            "stdout": "",
            "stderr": application_result.summary(),
            "timeout_expired": False,
            "time": 0.0,
            "wall_clock_time": 0.0,
            "time_source": TIME_SOURCE_WALL_CLOCK,
            "thread_count": thread_count,
            "executed": False,
            # Empty rather than a list holding the placeholder 0.0: the run never
            # happened, so there is no measurement to put in it.
            "repetitions": 0,
            "repetition_times": [],
            "repetition_wall_clock_times": [],
            "repetition_time_sources": [],
            "time_aggregate": TIME_AGGREGATE_NOT_MEASURED,
        },
    )
