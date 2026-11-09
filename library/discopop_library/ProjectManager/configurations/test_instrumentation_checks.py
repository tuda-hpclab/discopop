# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the checks after an instrumented build and an instrumented run.

The directory trees are faked in ``tmp_path``; ``os.utime`` decides what counts as written since the snapshot.
"""

import os
import time
from pathlib import Path
from typing import Optional

from discopop_library.ProjectManager.configurations.instrumentation_checks import (
    CheckResult,
    START_MARKER,
    Snapshot,
    check_build,
    check_profiling_run,
    file_mapping_covers,
    find_stray_dot_discopop_dirs,
    take_snapshot,
)

OLD = 1000.0  # seconds since the epoch: far before any snapshot


def _touch(path: Path, mtime: Optional[float] = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _snapshot() -> Snapshot:
    return Snapshot(started=time.time())


# ---- CheckResult


def test_check_result_messages_prefixes() -> None:
    result = CheckResult(errors=["e1", "e2"], warnings=["w1"])
    assert result.messages() == ["ERROR: e1", "ERROR: e2", "WARNING: w1"]
    assert CheckResult().messages() == []


# ---- take_snapshot


def test_take_snapshot_uses_the_mtime_of_the_marker(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    before = time.time()
    snapshot = take_snapshot(str(dot))
    marker = dot / START_MARKER
    assert marker.is_file()
    assert snapshot.started == os.path.getmtime(marker)
    assert before - 5 <= snapshot.started <= time.time() + 5


def test_take_snapshot_rewrites_an_old_marker(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / START_MARKER, OLD)
    assert take_snapshot(str(dot)).started > OLD + 1000


def test_take_snapshot_falls_back_to_the_clock_without_directory(tmp_path: Path) -> None:
    before = time.time()
    snapshot = take_snapshot(str(tmp_path / "missing" / ".discopop"))
    assert before <= snapshot.started <= time.time()
    assert not (tmp_path / "missing").exists()


def test_the_marker_is_not_a_stray_directory(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    snapshot = take_snapshot(str(dot))
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), snapshot.started - 5) == []
    result = check_build(snapshot, "dp_settings.json", str(tmp_path), str(dot), str(tmp_path) + "/")
    assert result.errors == []


# ---- file_mapping_covers


def _mapping(dot: Path, *lines: str) -> None:
    dot.mkdir(parents=True, exist_ok=True)
    (dot / "FileMapping.txt").write_text("".join(line + "\n" for line in lines))


def test_file_mapping_covers_line_under_scope(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _mapping(dot, "1\t/elsewhere/a.c", "2\t/proj/src/b.c")
    assert file_mapping_covers(str(dot), "/proj/src/")


def test_file_mapping_does_not_cover_lines_outside_scope(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _mapping(dot, "1\t/proj/src_old/a.c", "2\t/elsewhere/b.c")
    assert not file_mapping_covers(str(dot), "/proj/src/")


def test_file_mapping_missing_or_empty_does_not_cover(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    assert not file_mapping_covers(str(dot), "/proj/")
    _mapping(dot)
    assert not file_mapping_covers(str(dot), "/proj/")


# ---- find_stray_dot_discopop_dirs


def test_new_stray_file_mapping_is_reported(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / "FileMapping.txt")
    stray = _touch(tmp_path / "build" / "sub" / ".discopop" / "FileMapping.txt").parent
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == [str(stray)]


def test_new_stray_profiler_dir_is_reported(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    stray = tmp_path / "a" / ".discopop"
    (stray / "profiler").mkdir(parents=True)
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == [str(stray)]


def test_expected_dot_discopop_is_not_reported(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / "FileMapping.txt")
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == []


def test_expected_dot_discopop_via_symlinked_path_is_not_reported(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _touch(real / ".discopop" / "FileMapping.txt")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert find_stray_dot_discopop_dirs(str(real), str(link / ".discopop"), time.time() - 5) == []


def test_old_stray_dot_discopop_is_not_reported(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    _touch(tmp_path / "old" / ".discopop" / "FileMapping.txt", OLD)
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time()) == []


def test_stray_dir_without_build_output_is_not_reported(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    _touch(tmp_path / "x" / ".discopop" / "unrelated.txt")
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == []


def test_git_directory_is_skipped(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    _touch(tmp_path / ".git" / "sub" / ".discopop" / "FileMapping.txt")
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == []


def test_nested_directories_below_a_stray_are_not_walked(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    outer = _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt").parent
    _touch(outer / "inner" / ".discopop" / "FileMapping.txt")
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == [str(outer)]


def test_nested_directories_below_the_expected_one_are_not_walked(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / "copy" / ".discopop" / "FileMapping.txt")
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == []


def test_stray_dirs_are_sorted(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    b = _touch(tmp_path / "b" / ".discopop" / "FileMapping.txt").parent
    a = _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt").parent
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), time.time() - 5) == [str(a), str(b)]


def test_mtime_slack_counts_slightly_older_files(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    started = time.time()
    stray = _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt", started - 0.5).parent
    assert find_stray_dot_discopop_dirs(str(tmp_path), str(dot), started) == [str(stray)]


# ---- check_build


def test_check_build_ignores_seq_and_par(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt")
    for name in ("seq_settings.json", "par_settings.json"):
        result = check_build(_snapshot(), name, str(tmp_path), str(dot), str(tmp_path) + "/")
        assert result.errors == [] and result.warnings == []


def test_check_build_reports_stray_dirs_in_dp_and_hd(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    stray = _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt").parent
    snapshot = Snapshot(started=time.time() - 5)
    for name in ("dp_settings.json", "hd_settings.json"):
        result = check_build(snapshot, name, str(tmp_path), str(dot), str(tmp_path) + "/")
        assert len(result.errors) == 1
        assert str(stray) in result.errors[0]
        assert str(dot) in result.errors[0]


def test_check_build_truncates_long_stray_lists(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    for i in range(7):
        _touch(tmp_path / ("d%d" % i) / ".discopop" / "FileMapping.txt")
    snapshot = Snapshot(started=time.time() - 5)
    result = check_build(snapshot, "hd_settings.json", str(tmp_path), str(dot), str(tmp_path) + "/")
    assert "7 directories" in result.errors[0]
    assert result.errors[0].count(".discopop") >= 5
    assert "..." in result.errors[0]


def test_check_build_warns_without_file_mapping(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    for name in ("dp_settings.json", "hd_settings.json"):
        result = check_build(Snapshot(time.time()), name, str(tmp_path), str(dot), "/scope/")
        assert result.errors == []
        assert len(result.warnings) == 1
        assert "/scope/" in result.warnings[0]
        assert "FileMapping.txt" in result.warnings[0]


def test_check_build_no_warning_with_a_mapping_line_under_scope(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _mapping(dot, "1\t/scope/a.c")
    for name in ("dp_settings.json", "hd_settings.json"):
        assert check_build(Snapshot(time.time()), name, str(tmp_path), str(dot), "/scope/").messages() == []


def test_check_build_warns_for_a_mapping_only_outside_scope(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _mapping(dot, "1\t/other/a.c")
    result = check_build(Snapshot(time.time()), "dp_settings.json", str(tmp_path), str(dot), "/scope/")
    assert len(result.warnings) == 1


def test_check_build_reports_errors_and_warnings_together(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(tmp_path / "a" / ".discopop" / "FileMapping.txt")
    result = check_build(Snapshot(time.time() - 5), "dp_settings.json", str(tmp_path), str(dot), "/scope/")
    assert len(result.errors) == 1 and len(result.warnings) == 1
    assert [m.split(":")[0] for m in result.messages()] == ["ERROR", "WARNING"]


# ---- check_profiling_run


def test_profiling_run_dp_missing_dependencies_is_an_error(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    result = check_profiling_run(_snapshot(), "dp_settings.json", str(dot))
    assert len(result.errors) == 1
    assert "dynamic_dependencies.txt" in result.errors[0]


def test_profiling_run_dp_old_dependencies_is_an_error(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / "profiler" / "dynamic_dependencies.txt", OLD)
    result = check_profiling_run(_snapshot(), "dp_settings.json", str(dot))
    assert len(result.errors) == 1


def test_profiling_run_dp_new_dependencies_pass(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    snapshot = _snapshot()
    _touch(dot / "profiler" / "dynamic_dependencies.txt", snapshot.started + 1)
    assert check_profiling_run(snapshot, "dp_settings.json", str(dot)).messages() == []


def test_profiling_run_hd_missing_result_is_an_error(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    result = check_profiling_run(_snapshot(), "hd_settings.json", str(dot))
    assert len(result.errors) == 1
    assert "hotspot_detection" in result.errors[0]


def test_profiling_run_hd_old_result_is_an_error(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    _touch(dot / "hotspot_detection" / "private" / "hotspot_result_0.txt", OLD)
    assert len(check_profiling_run(_snapshot(), "hd_settings.json", str(dot)).errors) == 1


def test_profiling_run_hd_new_result_passes(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    snapshot = _snapshot()
    _touch(dot / "hotspot_detection" / "private" / "hotspot_result_0.txt", snapshot.started + 1)
    assert check_profiling_run(snapshot, "hd_settings.json", str(dot)).messages() == []


def test_profiling_run_hd_one_new_among_old_results_passes(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    snapshot = _snapshot()
    _touch(dot / "hotspot_detection" / "private" / "hotspot_result_0.txt", OLD)
    _touch(dot / "hotspot_detection" / "private" / "hotspot_result_1.txt", snapshot.started + 1)
    assert check_profiling_run(snapshot, "hd_settings.json", str(dot)).messages() == []


def test_profiling_run_seq_and_par_produce_no_messages(tmp_path: Path) -> None:
    for name in ("seq_settings.json", "par_settings.json"):
        assert check_profiling_run(_snapshot(), name, str(tmp_path / ".discopop")).messages() == []
