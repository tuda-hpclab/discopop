# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for reading a program's own execution time from its console output."""

import json
import logging
from pathlib import Path

import pytest

from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    EXECUTION_TIME_DISABLED,
    EXECUTION_TIME_SETTINGS_FILE,
    extract_execution_time,
    read_execution_time_settings,
    resolve_execution_time_regex,
    validate_execution_time_regex,
    write_execution_time_settings,
)

TOTAL_TIME_REGEX = r"Total time:\s*([0-9.]+)"


def test_the_default_pattern_reads_the_dp_exec_time_tag() -> None:
    output = "starting\n<DP_EXEC_TIME>1.234</DP_EXEC_TIME>\ndone\n"
    assert extract_execution_time(output, "", DEFAULT_EXECUTION_TIME_REGEX) == 1.234


def test_the_default_pattern_tolerates_whitespace_inside_the_tag() -> None:
    assert extract_execution_time("<DP_EXEC_TIME> 2.5 </DP_EXEC_TIME>", "", DEFAULT_EXECUTION_TIME_REGEX) == 2.5


def test_a_custom_pattern_reads_the_programs_own_wording() -> None:
    # the case this feature exists for: rodinia's hotspot times its computation
    # itself and prints the value in the middle of its other output
    output = "Reading input...\nTotal time: 1.234 seconds\nWriting output...\n"
    assert extract_execution_time(output, "", TOTAL_TIME_REGEX) == 1.234


def test_a_pattern_that_does_not_match_yields_no_time() -> None:
    assert extract_execution_time("no timing here\n", "", TOTAL_TIME_REGEX) is None


def test_the_last_of_several_matches_wins() -> None:
    # a program printing a time per phase ends with the total
    output = "Total time: 1.0\nTotal time: 2.0\nTotal time: 7.5\n"
    assert extract_execution_time(output, "", TOTAL_TIME_REGEX) == 7.5


def test_stderr_is_searched_when_stdout_reports_nothing() -> None:
    assert extract_execution_time("nothing\n", "Total time: 3.5\n", TOTAL_TIME_REGEX) == 3.5


def test_stdout_wins_over_stderr() -> None:
    assert extract_execution_time("Total time: 1.0\n", "Total time: 9.0\n", TOTAL_TIME_REGEX) == 1.0


def test_a_match_that_is_not_a_number_yields_no_time() -> None:
    # permissive value patterns can match something float() rejects; that must be
    # reported as "no time found" rather than crash the run
    assert extract_execution_time("<DP_EXEC_TIME>-.-e</DP_EXEC_TIME>", "", DEFAULT_EXECUTION_TIME_REGEX) is None


def test_a_pattern_with_several_groups_reads_the_first_one() -> None:
    output = "Total time: 4.5 s (of 9.0 s)\n"
    assert extract_execution_time(output, "", r"Total time: ([0-9.]+) s \(of ([0-9.]+) s\)") == 4.5


def test_an_uncompilable_pattern_yields_no_time() -> None:
    assert extract_execution_time("Total time: 1.0\n", "", "Total time: ([0-9.]+") is None


def test_a_pattern_without_a_capture_group_yields_no_time() -> None:
    # nothing could be read from it, so it is a mistake rather than a non-match
    assert extract_execution_time("Total time: 1.0\n", "", "Total time:") is None


def test_quiet_changes_only_the_logging(caplog: pytest.LogCaptureFixture) -> None:
    # a caller re-checking an already searched output must not warn a second time
    with caplog.at_level(logging.WARNING, logger="ExecutionTime"):
        assert extract_execution_time("nothing\n", "", TOTAL_TIME_REGEX, quiet=True) is None
    assert caplog.records == []

    with caplog.at_level(logging.WARNING, logger="ExecutionTime"):
        assert extract_execution_time("nothing\n", "", TOTAL_TIME_REGEX) is None
    assert len(caplog.records) == 1

    assert extract_execution_time("Total time: 2.0\n", "", TOTAL_TIME_REGEX, quiet=True) == 2.0


def test_validation_accepts_a_usable_pattern() -> None:
    assert validate_execution_time_regex(TOTAL_TIME_REGEX) is None
    assert validate_execution_time_regex(DEFAULT_EXECUTION_TIME_REGEX) is None


def test_validation_rejects_an_uncompilable_pattern() -> None:
    error = validate_execution_time_regex("Total time: ([0-9.]+")
    assert error is not None and "regular expression" in error


def test_validation_rejects_a_pattern_without_a_capture_group() -> None:
    error = validate_execution_time_regex("Total time:")
    assert error is not None and "capture group" in error


def test_an_unconfigured_configuration_has_the_search_switched_off(tmp_path: Path) -> None:
    enabled, regex = read_execution_time_settings(str(tmp_path))
    assert enabled is False
    # the default is offered nonetheless, so switching it on needs no further input
    assert regex == DEFAULT_EXECUTION_TIME_REGEX


def test_the_stored_setting_survives_a_round_trip(tmp_path: Path) -> None:
    write_execution_time_settings(str(tmp_path), True, TOTAL_TIME_REGEX)
    assert read_execution_time_settings(str(tmp_path)) == (True, TOTAL_TIME_REGEX)


def test_a_disabled_setting_keeps_its_pattern(tmp_path: Path) -> None:
    # switching the search off must not discard a pattern tailored to the program
    write_execution_time_settings(str(tmp_path), False, TOTAL_TIME_REGEX)
    assert read_execution_time_settings(str(tmp_path)) == (False, TOTAL_TIME_REGEX)


def test_an_unreadable_setting_switches_the_search_off(tmp_path: Path) -> None:
    (tmp_path / EXECUTION_TIME_SETTINGS_FILE).write_text("{not json")
    assert read_execution_time_settings(str(tmp_path)) == (False, DEFAULT_EXECUTION_TIME_REGEX)


def test_a_setting_without_a_pattern_falls_back_to_the_default(tmp_path: Path) -> None:
    (tmp_path / EXECUTION_TIME_SETTINGS_FILE).write_text(json.dumps({"enabled": True}))
    assert read_execution_time_settings(str(tmp_path)) == (True, DEFAULT_EXECUTION_TIME_REGEX)


def test_without_an_override_the_stored_setting_decides(tmp_path: Path) -> None:
    assert resolve_execution_time_regex(str(tmp_path), None) is None

    write_execution_time_settings(str(tmp_path), True, TOTAL_TIME_REGEX)
    assert resolve_execution_time_regex(str(tmp_path), None) == TOTAL_TIME_REGEX

    write_execution_time_settings(str(tmp_path), False, TOTAL_TIME_REGEX)
    assert resolve_execution_time_regex(str(tmp_path), None) is None


def test_an_override_wins_over_the_stored_setting(tmp_path: Path) -> None:
    write_execution_time_settings(str(tmp_path), False, TOTAL_TIME_REGEX)
    assert resolve_execution_time_regex(str(tmp_path), DEFAULT_EXECUTION_TIME_REGEX) == DEFAULT_EXECUTION_TIME_REGEX


def test_an_empty_override_switches_an_enabled_configuration_off(tmp_path: Path) -> None:
    write_execution_time_settings(str(tmp_path), True, TOTAL_TIME_REGEX)
    assert resolve_execution_time_regex(str(tmp_path), EXECUTION_TIME_DISABLED) is None
