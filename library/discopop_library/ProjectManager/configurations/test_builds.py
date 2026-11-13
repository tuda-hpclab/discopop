# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the builds: compile once, reuse while current, rebuild when stale, delete on request."""

import json
import os
import queue
import threading
from pathlib import Path
from typing import Dict, Iterator

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.building import BuildOutcome, BuildResult, build_lock, ensure_build
from discopop_library.ProjectManager.configurations.builds import (
    BuildKey,
    BuildPolicy,
    BuildState,
    build_status,
    build_tree_path_of,
    delete_builds,
    list_builds,
    manifest_path_of,
)
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.jobs import WorkContext

KEY = BuildKey("cfg", "seq")


def _arguments(project_root: Path, **overrides: object) -> ProjectManagerArguments:
    values: Dict[str, object] = dict(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=False,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )
    values.update(overrides)
    return ProjectManagerArguments(**values)  # type: ignore[arg-type]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Dict[str, Path]]:
    """A project with the configuration ``cfg`` whose scripts count how often they ran in ``compiles.txt`` and
    ``executions.txt`` (next to the project, so that they survive the copies)."""
    root = tmp_path / "proj"
    configs = root / ".discopop" / "project" / "configs"
    (configs / "cfg").mkdir(parents=True)
    (root / "main.c").write_text("int main() { return 0; }\n")
    compile_sh = configs / "compile.sh"
    compile_sh.write_text(f'#!/bin/bash\necho compiled >> "{tmp_path}/compiles.txt"\ncp main.c prog.out\n')
    (configs / "cfg" / "execute.sh").write_text(
        f'#!/bin/bash\necho executed >> "{tmp_path}/executions.txt"\ntest -f prog.out\n'
    )
    for mode in ("seq", "dp", "hd", "par"):
        (configs / (mode + "_settings.json")).write_text(
            json.dumps({"CC": "cc", "CXX": "c++", "CFLAGS": "", "CXXFLAGS": ""})
        )
    yield {"root": root, "configs": configs, "compile": compile_sh, "tmp": tmp_path}


def _count(project: Dict[str, Path], name: str) -> int:
    path = project["tmp"] / name
    return len(path.read_text().splitlines()) if path.exists() else 0


def _build(
    project: Dict[str, Path],
    policy: BuildPolicy = BuildPolicy.AUTO,
    thread_count: int = 1,
    key: BuildKey = KEY,
    **kw: object,
) -> BuildOutcome:
    arguments = _arguments(project["root"], **kw)
    with build_lock(arguments, key):
        return ensure_build(
            arguments,
            key,
            str(project["configs"] / key.configuration),
            str(project["configs"] / (key.mode + "_settings.json")),
            str(project["compile"]),
            thread_count,
            policy,
        )


def test_the_first_run_compiles_and_the_second_reuses_the_build(project: Dict[str, Path]) -> None:
    first = _build(project)
    assert first.result == BuildResult.BUILT and first.tree is not None
    assert (Path(first.tree) / "prog.out").exists()
    assert _count(project, "compiles.txt") == 1

    # another thread count does not need another build
    second = _build(project, thread_count=8)
    assert second.result == BuildResult.REUSED and second.tree == first.tree
    assert _count(project, "compiles.txt") == 1

    records = list_builds(str(project["root"] / ".discopop" / "project"))
    assert [record.build_id for record in records] == ["cfg_seq"]


def test_the_build_tree_is_kept_next_to_the_project(project: Dict[str, Path]) -> None:
    outcome = _build(project)
    assert outcome.tree == build_tree_path_of(str(project["root"]), KEY)
    assert os.path.dirname(str(outcome.tree)) == str(project["tmp"] / "proj_discopop_builds")


@pytest.mark.parametrize("change", ["source", "new_file", "compile_script", "settings"])
def test_a_change_makes_the_build_stale_and_the_next_run_compiles(project: Dict[str, Path], change: str) -> None:
    _build(project)
    if change == "source":
        (project["root"] / "main.c").write_text("int main() { return 1; }\n")
    elif change == "new_file":
        (project["root"] / "util.h").write_text("\n")
    elif change == "compile_script":
        project["compile"].write_text(project["compile"].read_text() + "# changed\n")
    else:
        (project["configs"] / "seq_settings.json").write_text(json.dumps({"CC": "cc", "CXX": "c++", "CFLAGS": "-O2"}))
    arguments = _arguments(project["root"])
    status = build_status(arguments, KEY, str(project["compile"]), str(project["configs"] / "seq_settings.json"))
    assert status.state == BuildState.STALE and status.reason

    assert _build(project).result == BuildResult.BUILT
    assert _count(project, "compiles.txt") == 2


def test_the_data_in_dot_discopop_does_not_make_a_build_stale(project: Dict[str, Path]) -> None:
    _build(project)
    (project["root"] / ".discopop" / "profiler").mkdir()
    (project["root"] / ".discopop" / "profiler" / "dynamic_dependencies.txt").write_text("x")
    assert _build(project).result == BuildResult.REUSED


def test_the_policies(project: Dict[str, Path]) -> None:
    unavailable = _build(project, BuildPolicy.REUSE)
    assert unavailable.result == BuildResult.UNAVAILABLE and unavailable.tree is None
    assert _count(project, "compiles.txt") == 0

    assert _build(project, BuildPolicy.REBUILD).result == BuildResult.BUILT
    assert _build(project, BuildPolicy.REUSE).result == BuildResult.REUSED
    assert _build(project, BuildPolicy.REBUILD).result == BuildResult.BUILT
    assert _count(project, "compiles.txt") == 2

    (project["root"] / "main.c").write_text("int main() { return 2; }\n")
    assert _build(project, BuildPolicy.REUSE).result == BuildResult.UNAVAILABLE


def test_a_failed_compilation_leaves_no_build(project: Dict[str, Path]) -> None:
    project["compile"].write_text("#!/bin/bash\nexit 1\n")
    outcome = _build(project)
    assert outcome.result == BuildResult.COMPILE_FAILED and outcome.tree is None
    assert not os.path.exists(manifest_path_of(str(project["root"] / ".discopop" / "project"), KEY))
    assert not os.path.exists(build_tree_path_of(str(project["root"]), KEY))


def test_a_failed_rebuild_does_not_leave_the_old_build_behind(project: Dict[str, Path]) -> None:
    _build(project)
    project["compile"].write_text("#!/bin/bash\nexit 1\n")
    assert _build(project).result == BuildResult.COMPILE_FAILED
    assert _build(project, BuildPolicy.REUSE).result == BuildResult.UNAVAILABLE


def test_builds_of_other_modes_and_suggestions_are_separate(project: Dict[str, Path]) -> None:
    assert KEY.build_id == "cfg_seq"
    with_suggestions = BuildKey("cfg", "par", ("3", "1"))
    assert with_suggestions.build_id == BuildKey("cfg", "par", ("1", "3")).build_id != BuildKey("cfg", "par").build_id
    _build(project)
    other = _build(project, key=BuildKey("cfg", "dp"))
    assert other.result == BuildResult.BUILT and other.tree != build_tree_path_of(str(project["root"]), KEY)
    assert _count(project, "compiles.txt") == 2
    assert [r.build_id for r in list_builds(str(project["root"] / ".discopop" / "project"))] == ["cfg_dp", "cfg_seq"]


def test_deleting_builds(project: Dict[str, Path]) -> None:
    _build(project)
    other = _build(project, key=BuildKey("cfg", "dp"))
    arguments = _arguments(project["root"])
    assert delete_builds(arguments, ["cfg_seq", "unknown"]) == ["cfg_seq"]
    assert not os.path.exists(build_tree_path_of(str(project["root"]), KEY))
    assert other.tree is not None and os.path.isdir(other.tree)
    assert delete_builds(arguments) == ["cfg_dp"]
    assert list_builds(arguments.project_dir) == []
    # the project itself is never touched
    assert (project["root"] / "main.c").exists()


def test_deleting_a_build_never_removes_a_directory_outside_the_build_trees(project: Dict[str, Path]) -> None:
    _build(project)
    arguments = _arguments(project["root"])
    manifest = manifest_path_of(arguments.project_dir, KEY)
    with open(manifest) as f:
        data = json.load(f)
    data["tree"] = str(project["root"])
    with open(manifest, "w") as f:
        json.dump(data, f)
    delete_builds(arguments)
    assert (project["root"] / "main.c").exists()


def test_a_run_of_the_execute_stage_compiles_once_for_several_runs(project: Dict[str, Path]) -> None:
    arguments = _arguments(project["root"])

    def run(**kw: object) -> None:
        request = execution_run.ExecutionRequest(
            configuration="cfg",
            modes=("seq",),
            inplace=False,
            skip_cleanup=False,
            thread_count=1,
            label_prefix="",
            timeout_execution=0,
            timeout_compilation=0,
            timeout_validation=0,
            repetitions=1,
            log_level="WARNING",
            suggestion_ids=(),
            **kw,  # type: ignore[arg-type]
        )
        execution_run.run_execution(arguments, request, WorkContext(queue.Queue(), threading.Event()))

    run()
    run()
    assert _count(project, "compiles.txt") == 1 and _count(project, "executions.txt") == 2
    run(build_policy="rebuild")
    assert _count(project, "compiles.txt") == 2 and _count(project, "executions.txt") == 3
    run(build_only=True, build_policy="rebuild")
    assert _count(project, "compiles.txt") == 3 and _count(project, "executions.txt") == 3
    run(build_policy="reuse")
    assert _count(project, "compiles.txt") == 3 and _count(project, "executions.txt") == 4


@pytest.mark.parametrize(
    "flags,policy,build_only",
    [([], "auto", False), (["--rebuild"], "rebuild", False), (["--reuse-build", "--build-only"], "reuse", True)],
)
def test_the_command_line_selects_the_build_policy(
    project: Dict[str, Path], monkeypatch: pytest.MonkeyPatch, flags: list, policy: str, build_only: bool  # type: ignore[type-arg]
) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr("sys.argv", ["discopop", "-p", str(project["root"])] + flags)
    arguments = parse_args()
    assert arguments.build_policy == policy and arguments.build_only is build_only


@pytest.mark.parametrize("flags", [["--rebuild", "--reuse-build"], ["--reuse-build", "--inplace"]])
def test_the_command_line_rejects_contradicting_build_flags(
    project: Dict[str, Path], monkeypatch: pytest.MonkeyPatch, flags: list  # type: ignore[type-arg]
) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr("sys.argv", ["discopop", "-p", str(project["root"])] + flags)
    with pytest.raises(SystemExit):
        parse_args()


def test_listing_and_deleting_builds_on_the_command_line(
    project: Dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from discopop_library.ProjectManager.utilities.CLI.builds import delete_builds_from_cli, show_builds

    arguments = _arguments(project["root"])
    show_builds(arguments)
    assert "No builds" in capsys.readouterr().out
    _build(project)
    show_builds(arguments)
    listing = capsys.readouterr().out
    assert "cfg_seq" in listing and "current" in listing
    (project["root"] / "main.c").write_text("int main() { return 3; }\n")
    show_builds(arguments)
    assert "stale" in capsys.readouterr().out
    arguments.delete_builds = "cfg_seq"
    delete_builds_from_cli(arguments)
    assert "Deleted 1 build(s): cfg_seq" in capsys.readouterr().out
    assert list_builds(arguments.project_dir) == []
