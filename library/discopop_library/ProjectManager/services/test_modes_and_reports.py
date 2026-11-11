# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path
from typing import Optional

import pytest

from discopop_library.ProjectManager.services import reports
from discopop_library.ProjectManager.services.modes import (
    available_modes,
    selected_modes_in_order,
    settings_path,
)
from discopop_library.ProjectManager.services.reports import (
    ReportProblem,
    find_latest_report_pdf,
    has_execution_results,
)


def test_settings_path(tmp_path: Path) -> None:
    assert settings_path(str(tmp_path), "dp") == str(tmp_path / "dp_settings.json")
    assert settings_path(str(tmp_path), "bogus") is None


def test_modes_need_their_settings_and_both_scripts(tmp_path: Path) -> None:
    (tmp_path / "seq_settings.json").write_text("{}")
    (tmp_path / "par_settings.json").write_text("{}")
    compile_sh, execute_sh = tmp_path / "compile.sh", tmp_path / "execute.sh"
    compile_sh.write_text("")
    assert not any(available_modes(str(tmp_path), str(compile_sh), str(execute_sh)).values())
    execute_sh.write_text("")
    assert available_modes(str(tmp_path), str(compile_sh), str(execute_sh)) == {
        "seq": True,
        "dp": False,
        "hd": False,
        "par": True,
    }


def test_selected_modes_follow_the_execution_order() -> None:
    assert selected_modes_in_order({"par": True, "seq": True, "dp": False}) == ["seq", "par"]


def test_latest_report(tmp_path: Path) -> None:
    assert find_latest_report_pdf(str(tmp_path)) == (None, ReportProblem.NO_REPORTS_DIRECTORY)
    (tmp_path / "reports").mkdir()
    assert find_latest_report_pdf(str(tmp_path)) == (None, ReportProblem.NO_REPORT)
    (tmp_path / "reports" / "2").mkdir()
    (tmp_path / "reports" / "1").mkdir()
    assert find_latest_report_pdf(str(tmp_path)) == (None, ReportProblem.NO_PDF)
    pdf = tmp_path / "reports" / "2" / "full_report.pdf"
    pdf.write_text("")
    assert find_latest_report_pdf(str(tmp_path)) == (str(pdf), None)


def test_execution_results(tmp_path: Path) -> None:
    results = tmp_path / "execution_results.json"
    assert not has_execution_results(str(tmp_path))
    results.write_text("not json")
    assert not has_execution_results(str(tmp_path))
    results.write_text('{"tiny": {"execute.sh": {"seq_settings.json": []}}}')
    assert not has_execution_results(str(tmp_path))
    results.write_text('{"tiny": {"execute.sh": {"seq_settings.json": [{"code": 0, "time": 1.5}]}}}')
    assert has_execution_results(str(tmp_path))


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (None, "—"),
        (0.0, "0 s"),
        (0.01234, "0.0123 s"),
        (0.5, "0.500 s"),
        (1.23456, "1.23 s"),
        (12.3456, "12.3 s"),
        (123.456, "123 s"),
        (1234.5, "1230 s"),
        (float("nan"), "—"),
    ],
)
def test_format_seconds_has_three_significant_digits(seconds: Optional[float], expected: str) -> None:
    assert reports.format_seconds(seconds) == expected


def test_format_ratio_limit_and_ids() -> None:
    assert reports.format_ratio(2.5) == "2.50" and reports.format_ratio(None) == "—"
    assert reports.format_limit(float("inf")) == "unbounded" and reports.format_limit(3.14159) == "3.14"
    assert reports.format_limit(None) == "—"
    assert reports.format_suggestion_ids([3, 7]) == "3, 7"
    assert reports.format_suggestion_ids([]) == "—" and reports.format_suggestion_ids(None) == "—"
