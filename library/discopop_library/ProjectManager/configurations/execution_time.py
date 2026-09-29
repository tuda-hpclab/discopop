# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Reading a program's own execution time from its console output.

The wall clock time of ``execute.sh`` is not always the measurement of interest:
it also covers setup and teardown, reading input files and writing results. When
the program prints the time of the region that actually matters, that value is
the better measurement -- so ``execute_configuration`` can be told to search the
program's output for it and record it in place of the wall clock time.

What is searched for is a regular expression whose *first capture group* holds
the number, e.g. ``Total time:\\s*([0-9.]+)`` for a program printing
``Total time: 1.234 seconds``. ``DEFAULT_EXECUTION_TIME_REGEX`` looks for the
``<DP_EXEC_TIME>1.234</DP_EXEC_TIME>`` tag instead, which a program can print
without any assumption about how the rest of its output is formatted.

The search is off unless it is asked for, and it is asked for in two ways:

* per configuration, by an ``execution_time.json`` next to that configuration's
  ``execute.sh`` -- the stored setting, edited in the graphical configuration
  manager alongside the script it belongs to,
* per invocation, by ``--execution-time-regex``, which overrides the stored
  setting of every configuration for that one run (this is what the benchmark
  harnesses pass).

``resolve_execution_time_regex`` implements that precedence. Only ``execute.sh``
is ever searched: ``compile.sh`` and ``validate.sh`` run through the same
function but produce no measurement, so their callers never pass a pattern.
"""

import json
import logging
import os
import re
from typing import Optional, Tuple

PATH = str

logger = logging.getLogger("ExecutionTime")

# The tag a program can print to report its own execution time without making
# any assumption about the surrounding output.
DEFAULT_EXECUTION_TIME_TAG = "DP_EXEC_TIME"

# Matches "<DP_EXEC_TIME>1.234</DP_EXEC_TIME>". The value pattern is deliberately
# permissive (it accepts things float() rejects) so that a malformed value is
# reported as such instead of silently failing to match at all.
DEFAULT_EXECUTION_TIME_REGEX = (
    "<" + DEFAULT_EXECUTION_TIME_TAG + r">\s*([-+0-9.eE]+)\s*</" + DEFAULT_EXECUTION_TIME_TAG + ">"
)

# Name of the per-configuration file holding the stored setting.
EXECUTION_TIME_SETTINGS_FILE = "execution_time.json"

# Passed as the override to disable the search even though a configuration
# stores one. Spelled as the empty string so that it can be expressed on a
# command line ("--execution-time-regex ''").
EXECUTION_TIME_DISABLED = ""

# How the recorded runtime came about; stored as "time_source" next to the
# measurement so every consumer can tell the two apart.
TIME_SOURCE_WALL_CLOCK = "wall_clock"
TIME_SOURCE_CONSOLE = "console"
TIME_SOURCE_FALLBACK = "wall_clock_fallback"


def validate_execution_time_regex(pattern: str) -> Optional[str]:
    """An error message describing why ``pattern`` is unusable, or None if it is fine.

    Beyond being compilable, the pattern must contain a capture group: the value
    is read from group 1, so a pattern without one could never yield a time and
    is a mistake worth reporting before a run rather than after it.
    """
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        return "not a valid regular expression: " + str(error)
    if compiled.groups < 1:
        return (
            "the pattern contains no capture group; the execution time is read from the "
            "first group, e.g. 'Total time:\\s*([0-9.]+)'"
        )
    return None


def extract_execution_time(stdout: str, stderr: str, pattern: str, quiet: bool = False) -> Optional[float]:
    """The execution time ``pattern`` finds in the program's output, or None.

    ``stdout`` is searched first and ``stderr`` only if that found nothing, since
    programs report their timing on either stream. Of several matches the *last*
    one wins: a program printing a time per phase ends with the total.

    Returns None -- and says why -- whenever no usable value can be read, so the
    caller can fall back to the wall clock time instead of failing the run.
    ``quiet`` suppresses that explanation, for a caller re-checking an output that
    has already been searched once.
    """
    error = validate_execution_time_regex(pattern)
    if error is not None:
        if not quiet:
            logger.warning("Not searching the output for the execution time: " + error)
        return None

    compiled = re.compile(pattern)
    for stream_name, stream in (("stdout", stdout), ("stderr", stderr)):
        matches = compiled.findall(stream)
        if not matches:
            continue
        # findall yields tuples once the pattern has more than one group
        last = matches[-1]
        value = last[0] if isinstance(last, tuple) else last
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            if not quiet:
                logger.warning(
                    "The execution time pattern matched in "
                    + stream_name
                    + ", but '"
                    + str(value)
                    + "' is not a number."
                )
            return None
        if len(matches) > 1:
            logger.debug(
                "The execution time pattern matched "
                + str(len(matches))
                + " times in "
                + stream_name
                + "; using the last value."
            )
        return parsed

    if not quiet:
        logger.warning("The execution time pattern did not match the program's output.")
    return None


def read_execution_time_settings(config_path: PATH) -> Tuple[bool, str]:
    """The ``(enabled, regex)`` stored for one configuration.

    A missing, unreadable or malformed file means the search is off; the returned
    regex is then the default, so that switching it on requires no further input.
    """
    settings_path = os.path.join(config_path, EXECUTION_TIME_SETTINGS_FILE)
    if not os.path.exists(settings_path):
        return False, DEFAULT_EXECUTION_TIME_REGEX
    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)
        regex = settings.get("regex") or DEFAULT_EXECUTION_TIME_REGEX
        return bool(settings.get("enabled", False)), str(regex)
    except (OSError, json.JSONDecodeError, AttributeError):
        logger.warning("Ignoring unreadable " + settings_path)
        return False, DEFAULT_EXECUTION_TIME_REGEX


def write_execution_time_settings(config_path: PATH, enabled: bool, regex: str) -> None:
    """Store the ``(enabled, regex)`` setting of one configuration.

    The regex is kept even while the search is off, so that turning it off and on
    again does not discard a pattern that was tailored to the program's output.
    """
    settings_path = os.path.join(config_path, EXECUTION_TIME_SETTINGS_FILE)
    with open(settings_path, "w") as f:
        json.dump({"enabled": bool(enabled), "regex": regex}, f, indent=2, sort_keys=True)


def resolve_execution_time_regex(config_path: PATH, override: Optional[str]) -> Optional[str]:
    """The pattern to search one configuration's output with, or None to not search.

    ``override`` is what the command line asked for and wins over the stored
    setting of every configuration: None leaves the stored setting alone, the
    empty string switches the search off, anything else is used as the pattern.
    """
    if override is not None:
        if override == EXECUTION_TIME_DISABLED:
            return None
        return override
    enabled, regex = read_execution_time_settings(config_path)
    return regex if enabled else None
