# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The setting of the thread count of compile scripts: storage and precedence."""

import json
from pathlib import Path
from typing import Optional

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services import build_thread_count


def _arguments(root: Path, override: Optional[bool] = None) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        build_thread_count=override,
    )


def test_the_default_is_not_to_pass_the_thread_count(tmp_path: Path) -> None:
    assert build_thread_count.load_build_thread_count(str(tmp_path)) == build_thread_count.BuildThreadCount(False)
    assert not build_thread_count.passes_thread_count_to_builds(_arguments(tmp_path))


def test_a_stored_setting_round_trips_as_json(tmp_path: Path) -> None:
    build_thread_count.save_build_thread_count(str(tmp_path), build_thread_count.BuildThreadCount(True))
    stored = json.loads((tmp_path / "build_thread_count.json").read_text())
    assert stored == {"pass_to_builds": True}
    assert build_thread_count.load_build_thread_count(str(tmp_path)).pass_to_builds


def test_it_only_writes_on_change(tmp_path: Path) -> None:
    build_thread_count.save_build_thread_count(str(tmp_path), build_thread_count.BuildThreadCount(True))
    path = tmp_path / "build_thread_count.json"
    mtime = path.stat().st_mtime_ns
    build_thread_count.save_build_thread_count(str(tmp_path), build_thread_count.BuildThreadCount(True))
    assert path.stat().st_mtime_ns == mtime
    assert not (tmp_path / "build_thread_count.json.tmp").exists()


def test_broken_files_give_the_default(tmp_path: Path) -> None:
    path = tmp_path / "build_thread_count.json"
    for content in ("{not json", "[]", '{"pass_to_builds": "yes"}'):
        path.write_text(content)
        assert build_thread_count.load_build_thread_count(str(tmp_path)).pass_to_builds is False


def test_the_command_line_option_wins_over_the_stored_setting(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    build_thread_count.save_build_thread_count(arguments.project_dir, build_thread_count.BuildThreadCount(True))
    assert build_thread_count.passes_thread_count_to_builds(arguments)
    arguments.build_thread_count = False
    assert not build_thread_count.passes_thread_count_to_builds(arguments)
    build_thread_count.save_build_thread_count(arguments.project_dir, build_thread_count.BuildThreadCount(False))
    arguments.build_thread_count = True
    assert build_thread_count.passes_thread_count_to_builds(arguments)
