# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.ProjectManager.gui.plots.mode_style import (
    CONFIG_PALETTE,
    DEFAULT_MARKER,
    NOT_APPLIED_STATUS,
    STATUS_ORDER,
    assign_config_colors,
    autotuner_status,
    execution_status,
    mode_dashes,
    mode_marker,
    status_color,
    status_label,
    status_marker,
)


def test_assign_config_colors_is_deterministic_and_sorted() -> None:
    colors = assign_config_colors(["clang-O3", "default"])
    # assignment follows sorted order, so it is stable regardless of input order
    assert colors == assign_config_colors(["default", "clang-O3"])
    assert colors["clang-O3"] == CONFIG_PALETTE[0]
    assert colors["default"] == CONFIG_PALETTE[1]


def test_assign_config_colors_stable_under_subsetting() -> None:
    full = assign_config_colors(["a", "b", "c"])
    # a chart that later hides "b" must keep "a" and "c" on their colours, so the
    # colour of an entity is a function of the full sorted universe passed in.
    assert full["a"] == CONFIG_PALETTE[0]
    assert full["c"] == CONFIG_PALETTE[2]


def test_assign_config_colors_wraps_when_palette_exhausted() -> None:
    many = [f"cfg{i:02d}" for i in range(len(CONFIG_PALETTE) + 1)]
    colors = assign_config_colors(many)
    assert colors[many[0]] == colors[many[len(CONFIG_PALETTE)]]  # wrapped around


def test_mode_marker_and_dashes() -> None:
    assert mode_marker("par") == "s"
    assert mode_marker("unknown") == DEFAULT_MARKER
    assert mode_dashes("par") == (None, None)  # solid
    assert mode_dashes("dp") == (6, 3)
    assert mode_dashes("unknown") == (None, None)


def test_status_colors() -> None:
    assert status_color("valid") != status_color("failed")
    assert status_color("nonsense") == status_color("failed")  # safe fallback


def test_not_applied_is_visually_distinct_from_every_other_status() -> None:
    # a skipped run must be distinguishable from both a failure and a slow success
    colors = {status: status_color(status) for status in STATUS_ORDER}
    assert len(set(colors.values())) == len(STATUS_ORDER)
    # and additionally carries its own marker, since it has no measurement to plot
    assert status_marker(NOT_APPLIED_STATUS) != status_marker("valid")
    assert status_marker("nonsense") == "o"
    assert "not applied" in status_label(NOT_APPLIED_STATUS)


def test_execution_status() -> None:
    assert execution_status(valid=True) == "valid"
    assert execution_status(valid=False) == "failed"
    assert execution_status(valid=False, timeout=True) == "failed"


def test_execution_status_reports_an_unapplied_run_as_its_own_state() -> None:
    # application_failed wins over every other flag: the run never happened
    assert execution_status(valid=False, application_failed=True) == NOT_APPLIED_STATUS
    assert execution_status(valid=True, application_failed=True) == NOT_APPLIED_STATUS


def test_autotuner_status() -> None:
    assert autotuner_status(0, True, True) == "valid"
    assert autotuner_status(0, False, True) == "invalid"
    assert autotuner_status(0, True, False) == "invalid"
    assert autotuner_status(1, False, False) == "failed"


def test_autotuner_status_reports_an_unpatched_configuration_separately() -> None:
    # would otherwise read as "invalid" (return code 0, result not valid)
    assert autotuner_status(0, False, False, application_failed=True) == NOT_APPLIED_STATUS
