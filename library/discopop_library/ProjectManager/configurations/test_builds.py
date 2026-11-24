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
import shutil
import threading
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.building import BuildOutcome, BuildResult, build_lock, ensure_build
from discopop_library.ProjectManager.configurations.builds import (
    NO_FILE_LIST_NOTE,
    BuildAcceptError,
    BuildInUseError,
    BuildKey,
    BuildPolicy,
    BuildState,
    BuildStatus,
    accept_build,
    accepted_changes_text,
    build_files_path_of,
    build_status,
    build_tree_path_of,
    combine_fingerprint,
    delete_builds,
    list_builds,
    manifest_path_of,
    read_build,
    read_build_files,
    source_fingerprint,
    write_build,
)
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.callpath_pruning import CallpathPruning, save_callpath_pruning
from discopop_library.ProjectManager.services.copy_exclude import save_copy_exclude
from discopop_library.ProjectManager.services.fingerprint_ignore import add_patterns
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


def test_a_dangling_symbolic_link_does_not_fail_the_build(project: Dict[str, Path]) -> None:
    (project["root"] / "dangling").symlink_to(project["root"] / "does_not_exist")
    build = _build(project)
    assert build.result == BuildResult.BUILT and build.tree is not None
    assert (Path(build.tree) / "main.c").exists()
    assert not os.path.lexists(os.path.join(build.tree, "dangling"))
    # the link does not make the build stale either
    assert _build(project).result == BuildResult.REUSED


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
    # the kept tree stays for the next compilation; deleting all builds removes it
    assert os.path.exists(build_tree_path_of(str(project["root"]), KEY))
    delete_builds(_arguments(project["root"]))
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


# ── what the review of the design found ──────────────────────────────────────


def test_a_reused_build_runs_the_current_execute_script(project: Dict[str, Path]) -> None:
    first = _build(project)
    assert first.tree is not None
    execute = project["configs"] / "cfg" / "execute.sh"
    execute.write_text(execute.read_text() + 'echo changed >> "' + str(project["tmp"]) + '/marker.txt"\n')
    second = _build(project)
    # editing a run script neither makes the build stale ...
    assert second.result == BuildResult.REUSED
    # ... nor is the old copy of it run
    assert "changed" in (Path(second.tree) / ".discopop" / "project" / "configs" / "cfg" / "execute.sh").read_text()  # type: ignore[arg-type]


def test_a_helper_file_of_the_configuration_makes_the_build_stale(project: Dict[str, Path]) -> None:
    _build(project)
    (project["configs"] / "cfg" / "flags.mk").write_text("-O2\n")
    assert _build(project).result == BuildResult.BUILT


def test_a_build_starts_without_the_profiling_data_of_the_project(project: Dict[str, Path]) -> None:
    (project["root"] / ".discopop" / "profiler").mkdir()
    (project["root"] / ".discopop" / "profiler" / "dynamic_dependencies.txt").write_text("old")
    outcome = _build(project)
    assert outcome.tree is not None
    assert not (Path(outcome.tree) / ".discopop" / "profiler").exists()


def test_ignored_files_of_a_git_work_tree_do_not_make_a_build_stale(project: Dict[str, Path]) -> None:
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = project["root"]
    (root / ".gitignore").write_text("*.o\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _build(project)
    (root / "main.o").write_text("object")
    assert _build(project).result == BuildResult.REUSED
    (root / "main.c").unlink()
    # a deleted file is a change (the compilation of the rest fails here, which is not the point)
    assert _build(project).result != BuildResult.REUSED


def test_a_build_that_is_used_cannot_be_deleted(project: Dict[str, Path]) -> None:
    _build(project)
    arguments = _arguments(project["root"])
    with build_lock(arguments, KEY):
        assert delete_builds(arguments) == []
    assert delete_builds(arguments) == ["cfg_seq"]


def test_waiting_for_a_build_can_be_stopped(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.building import BuildLockAborted

    arguments = _arguments(project["root"])
    waited = []
    with build_lock(arguments, KEY):
        with pytest.raises(BuildLockAborted):
            with build_lock(arguments, KEY, should_abort=lambda: True, on_wait=lambda: waited.append(1)):
                pass  # pragma: no cover
    assert waited == [1]


def test_a_validation_build_in_the_tree_invalidates_the_build(project: Dict[str, Path]) -> None:
    (project["configs"] / "compile_validate.sh").write_text("#!/bin/bash\ncp main.c validate.out\n")
    (project["configs"] / "cfg" / "validate.sh").write_text("#!/bin/bash\ntest -f validate.out\n")
    arguments = _arguments(project["root"])

    def run() -> None:
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
        )
        execution_run.run_execution(arguments, request, WorkContext(queue.Queue(), threading.Event()))

    run()
    assert _count(project, "compiles.txt") == 1
    # the validation build changed the tree, so the next run compiles again
    run()
    assert _count(project, "compiles.txt") == 2


def test_a_member_runs_in_the_build_of_its_owner_and_is_compiled_once(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.build_sharing import build_inputs_for, set_build_from
    from discopop_library.ProjectManager.configurations.running import execute_in_build

    configs = str(project["configs"])
    (project["configs"] / "other").mkdir()
    (project["configs"] / "other" / "execute.sh").write_text(
        f'#!/bin/bash\necho other >> "{project["tmp"]}/executions.txt"\ntest -f prog.out\n'
    )
    set_build_from(configs, "other", "cfg")
    owner_build = _build(project)
    assert owner_build.record is not None

    inputs = build_inputs_for(configs, "other")
    member_build = _build(project, key=BuildKey(inputs.build_config, "seq"))
    assert member_build.result == BuildResult.REUSED and _count(project, "compiles.txt") == 1

    arguments = _arguments(project["root"])
    result, _run = execute_in_build(
        arguments,
        owner_build.record,
        str(project["configs"] / "other"),
        str(project["configs"] / "seq_settings.json"),
        1,
        None,
        None,
        1,
    )
    assert result is not None and result[0] == 0
    assert _count(project, "executions.txt") == 1
    assert [record.build_id for record in list_builds(str(project["root"] / ".discopop" / "project"))] == ["cfg_seq"]


def _run_execute_stage(project: Dict[str, Path], configuration: str, **kw: object) -> None:
    request = execution_run.ExecutionRequest(
        configuration=configuration,
        modes=("seq",),
        inplace=False,
        skip_cleanup=False,
        thread_count=4,
        label_prefix="",
        timeout_execution=0,
        timeout_compilation=0,
        timeout_validation=0,
        repetitions=1,
        log_level="WARNING",
        suggestion_ids=(),
        **kw,  # type: ignore[arg-type]
    )
    execution_run.run_execution(_arguments(project["root"]), request, WorkContext(queue.Queue(), threading.Event()))


def _share_with_member(project: Dict[str, Path], owner_override: bool) -> None:
    from discopop_library.ProjectManager.configurations.build_sharing import set_build_from

    if owner_override:
        # the owner compiles with a script of its own, which differs from the shared one
        (project["configs"] / "cfg" / "compile.sh").write_text(
            f'#!/bin/bash\necho owner_override >> "{project["tmp"]}/compiles.txt"\ncp main.c prog.out\n'
        )
    (project["configs"] / "other").mkdir()
    (project["configs"] / "other" / "execute.sh").write_text(
        f'#!/bin/bash\necho other >> "{project["tmp"]}/executions.txt"\ntest -f prog.out\n'
    )
    set_build_from(str(project["configs"]), "other", "cfg")


def test_a_member_is_compiled_with_the_script_of_its_owner(project: Dict[str, Path]) -> None:
    _share_with_member(project, owner_override=True)
    _run_execute_stage(project, "other")
    # the script of the owner ran, not the shared compile.sh the member would resolve to by itself
    assert (project["tmp"] / "compiles.txt").read_text().split() == ["owner_override"]
    assert _count(project, "executions.txt") == 1
    # the owner reuses the build, the member's results are recorded under the member
    _run_execute_stage(project, "cfg")
    assert _count(project, "compiles.txt") == 1 and _count(project, "executions.txt") == 2
    assert [r.build_id for r in list_builds(str(project["root"] / ".discopop" / "project"))] == ["cfg_seq"]
    with open(project["root"] / ".discopop" / "project" / "execution_results.json") as f:
        results = json.load(f)
    assert set(results) == {"cfg", "other"}


def test_a_member_is_validated_in_the_shared_build_without_compiling_again(project: Dict[str, Path]) -> None:
    _share_with_member(project, owner_override=False)
    (project["configs"] / "other" / "validate.sh").write_text(
        f'#!/bin/bash\necho validated >> "{project["tmp"]}/validations.txt"\ntest -f prog.out\n'
    )
    _run_execute_stage(project, "other")
    _run_execute_stage(project, "other")
    assert _count(project, "validations.txt") == 2
    assert _count(project, "compiles.txt") == 1


def _hotspots(project: Dict[str, Path], hotness: str = "YES") -> None:
    directory = project["root"] / ".discopop" / "hotspot_detection"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Hotspots.json").write_text(json.dumps({"code_regions": [{"hotness": hotness}]}))


def _enable_pruning(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.services import callpath_pruning

    callpath_pruning.save_callpath_pruning(
        str(project["root"] / ".discopop" / "project"), callpath_pruning.CallpathPruning(enabled=True)
    )


def test_the_fingerprint_of_a_dp_build_contains_the_call_path_pruning_only_for_dp(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.builds import compute_fingerprint_parts

    arguments = _arguments(project["root"])
    settings = str(project["configs"] / "dp_settings.json")
    assert "callpath_pruning" in compute_fingerprint_parts(
        arguments, BuildKey("cfg", "dp"), str(project["compile"]), settings
    )
    for mode in ("seq", "hd", "par"):
        parts = compute_fingerprint_parts(arguments, BuildKey("cfg", mode), str(project["compile"]), settings)
        assert "callpath_pruning" not in parts


def test_a_dp_build_is_stale_when_pruning_is_switched_on_or_the_hotspots_change(project: Dict[str, Path]) -> None:
    dp = BuildKey("cfg", "dp")
    _hotspots(project)
    assert _build(project, key=dp).result == BuildResult.BUILT
    assert _build(project, key=dp).result == BuildResult.REUSED
    _enable_pruning(project)  # pruning on: other compilation
    assert _build(project, key=dp).result == BuildResult.BUILT
    assert _build(project, key=dp).result == BuildResult.REUSED
    _hotspots(project, hotness="MAYBE")  # other hotspot results: other pruning
    assert _build(project, key=dp).result == BuildResult.BUILT
    assert _build(project, key=dp).result == BuildResult.REUSED


def test_hotspot_results_do_not_matter_to_a_dp_build_without_pruning(project: Dict[str, Path]) -> None:
    dp = BuildKey("cfg", "dp")
    assert _build(project, key=dp).result == BuildResult.BUILT
    _hotspots(project)
    assert _build(project, key=dp).result == BuildResult.REUSED


# ── what changed since a build, ignore patterns, accepting changes ─────────────


def _status(project: Dict[str, Path], key: BuildKey = KEY) -> BuildStatus:
    return build_status(
        _arguments(project["root"]),
        key,
        str(project["compile"]),
        str(project["configs"] / (key.mode + "_settings.json")),
    )


def _project_dir(project: Dict[str, Path]) -> str:
    return str(project["root"] / ".discopop" / "project")


def test_the_hash_of_the_files_is_unchanged_so_existing_builds_stay_current(project: Dict[str, Path]) -> None:
    import hashlib

    root = str(project["root"])
    (project["root"] / "sub").mkdir()
    (project["root"] / "sub" / "a.h").write_text("x\n")
    legacy = hashlib.sha256()
    lines = []
    for name in ("main.c", "sub/a.h"):
        stat = os.lstat(os.path.join(root, name))
        lines.append(name + "\0" + str(stat.st_size) + "\0" + str(stat.st_mtime_ns))
    for line in sorted(lines):
        legacy.update(line.encode() + b"\n")
    assert source_fingerprint(root) == legacy.hexdigest()


def test_a_stale_build_names_the_changed_files(project: Dict[str, Path]) -> None:
    (project["root"] / "gone.h").write_text("\n")
    _build(project)
    (project["root"] / "main.c").write_text("int main() { return 1; }\n")
    (project["root"] / "dp_build").mkdir()
    (project["root"] / "dp_build" / "build.ninja").write_text("cache\n")
    (project["root"] / "gone.h").unlink()

    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None
    assert status.changes.parts == ("sources",)
    files = status.changes.files
    assert files is not None and not files.approximate
    assert files.modified == ("main.c",)
    assert files.added == ("dp_build/build.ninja",)
    assert files.removed == ("gone.h",)
    assert status.reason.startswith("Changed since the build: sources.")
    assert "3 files changed (1 modified, 1 added, 1 removed)" in status.reason


def test_a_configured_build_directory_is_neither_copied_nor_counted(project: Dict[str, Path]) -> None:
    _build(project)
    # an in-place compilation of the project after the build: an out-of-source CMake build directory
    build_dir = project["root"] / "build"
    (build_dir / "CMakeFiles").mkdir(parents=True)
    (build_dir / "CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=" + str(project["root"]) + "\n")
    (build_dir / "prog").write_text("binary\n")
    assert _status(project).state == BuildState.CURRENT

    messages: List[str] = []
    arguments = _arguments(project["root"])
    with build_lock(arguments, KEY):
        outcome = ensure_build(
            arguments,
            KEY,
            str(project["configs"] / "cfg"),
            str(project["configs"] / "seq_settings.json"),
            str(project["compile"]),
            1,
            BuildPolicy.REBUILD,
            message=messages.append,
        )
    assert outcome.result == BuildResult.BUILT and outcome.tree is not None
    assert not (Path(outcome.tree) / "build").exists()
    assert any("Not copied: configured build directories" in text and "build" in text for text in messages)


def test_a_build_directory_deleted_after_the_build_does_not_make_it_stale(project: Dict[str, Path]) -> None:
    build_dir = project["root"] / "build"
    (build_dir / "CMakeFiles").mkdir(parents=True)
    (build_dir / "CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=" + str(project["root"]) + "\n")
    (build_dir / "prog").write_text("binary\n")
    _build(project)
    shutil.rmtree(build_dir)
    assert _status(project).state == BuildState.CURRENT
    # sources in a directory of that name count again
    (project["root"] / "build").mkdir()
    (project["root"] / "build" / "extra.c").write_text("\n")
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None and status.changes.files is not None
    assert status.changes.files.added == ("build/extra.c",)


def test_the_copy_exclude_list_is_part_of_the_fingerprint(project: Dict[str, Path]) -> None:
    (project["root"] / "data").mkdir()
    (project["root"] / "data" / "input.bin").write_text("large\n")
    _build(project)
    assert _status(project).state == BuildState.CURRENT

    save_copy_exclude(_project_dir(project), ["data"])
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None
    assert "copy_exclude" in status.changes.parts

    outcome = _build(project)
    assert outcome.result == BuildResult.BUILT and outcome.tree is not None
    assert not (Path(outcome.tree) / "data").exists()
    # a change of what is left out no longer matters
    (project["root"] / "data" / "input.bin").write_text("other\n")
    assert _status(project).state == BuildState.CURRENT


def test_an_ignore_pattern_added_after_the_build_makes_it_current(project: Dict[str, Path]) -> None:
    _build(project)
    (project["root"] / "dp_build").mkdir()
    (project["root"] / "dp_build" / "build.ninja").write_text("cache\n")
    assert _status(project).state == BuildState.STALE

    add_patterns(_project_dir(project), ["dp_build/"])
    assert _status(project).state == BuildState.CURRENT
    assert _build(project).result == BuildResult.REUSED
    # a change elsewhere still counts
    (project["root"] / "main.c").write_text("int main() { return 2; }\n")
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None and status.changes.files is not None
    assert status.changes.files.paths == ("main.c",)


def test_a_build_without_a_file_list_reports_the_files_newer_than_the_build(project: Dict[str, Path]) -> None:
    # the build directory existed when the build was compiled (an in-place compilation before), as in practice
    (project["root"] / "dp_build").mkdir()
    (project["root"] / "dp_build" / "build.ninja").write_text("old\n")
    _build(project)
    os.remove(build_files_path_of(_project_dir(project), KEY))
    record = read_build(_project_dir(project), KEY)
    assert record is not None
    (project["root"] / "dp_build" / "build.ninja").write_text("\n")
    os.utime(project["root"] / "dp_build" / "build.ninja", (record.built_at + 10, record.built_at + 10))

    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None and status.changes.files is not None
    assert status.changes.files.approximate and status.changes.files.modified == ("dp_build/build.ninja",)
    assert "1 file is newer than the build: dp_build/ (1)." in status.reason

    # its recorded hash covers every file: a pattern does not help, which is said
    add_patterns(_project_dir(project), ["dp_build/"])
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None and status.changes.files is not None
    assert status.changes.files.modified == ("dp_build/build.ninja",)
    assert NO_FILE_LIST_NOTE in status.reason
    # accepted once, the pattern applies
    accept_build(
        _arguments(project["root"]), KEY, str(project["compile"]), str(project["configs"] / "seq_settings.json")
    )
    (project["root"] / "dp_build" / "build.ninja").write_text("changed\n")
    assert _status(project).state == BuildState.CURRENT


def test_a_file_list_of_another_manifest_is_not_used(project: Dict[str, Path]) -> None:
    """An older version rebuilding the build writes a new manifest and leaves the file list of the old one."""
    _build(project)
    record = read_build(_project_dir(project), KEY)
    assert record is not None
    record.fingerprint_parts["sources"] = "the files when an older version compiled it again"
    record.fingerprint = combine_fingerprint(record.fingerprint_parts)
    write_build(_project_dir(project), record)
    (project["root"] / "dp_build").mkdir()
    (project["root"] / "dp_build" / "a").write_text("\n")
    add_patterns(_project_dir(project), ["dp_build/"])
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None and status.changes.files is not None
    assert status.changes.files.approximate


def test_a_change_of_the_call_path_pruning_cannot_be_accepted(project: Dict[str, Path]) -> None:
    dp = BuildKey("cfg", "dp")
    _build(project, key=dp)
    hotspots = project["root"] / ".discopop" / "hotspot_detection"
    hotspots.mkdir(parents=True)
    (hotspots / "Hotspots.json").write_text(json.dumps({"code_regions": [{"hotness": "YES"}]}))
    save_callpath_pruning(_project_dir(project), CallpathPruning(enabled=True))
    status = _status(project, dp)
    assert status.state == BuildState.STALE and status.changes is not None
    assert "callpath_pruning" in status.changes.parts
    assert "the build was not pruned, but would be now" in status.reason
    with pytest.raises(BuildAcceptError):
        accept_build(
            _arguments(project["root"]), dp, str(project["compile"]), str(project["configs"] / "dp_settings.json")
        )
    assert _status(project, dp).state == BuildState.STALE


def test_accepting_the_changes_makes_the_build_current_and_is_noted(project: Dict[str, Path]) -> None:
    _build(project)
    (project["root"] / "notes.txt").write_text("irrelevant\n")
    arguments = _arguments(project["root"])
    settings = str(project["configs"] / "seq_settings.json")

    before = accept_build(arguments, KEY, str(project["compile"]), settings)
    assert before.state == BuildState.STALE
    assert _status(project).state == BuildState.CURRENT
    files = read_build_files(_project_dir(project), KEY)
    assert files is not None and len(files.accepted) == 1
    assert files.accepted[0]["parts"] == ["sources"] and files.accepted[0]["files"] == ["notes.txt"]
    assert "accepted" in accepted_changes_text(_project_dir(project), KEY)

    reused = _build(project)
    assert reused.result == BuildResult.REUSED
    assert _count(project, "compiles.txt") == 1
    # nothing left to accept
    assert accept_build(arguments, KEY, str(project["compile"]), settings).state == BuildState.CURRENT


def test_a_build_in_use_cannot_be_accepted(project: Dict[str, Path]) -> None:
    _build(project)
    (project["root"] / "notes.txt").write_text("irrelevant\n")
    arguments = _arguments(project["root"])
    with build_lock(arguments, KEY):
        with pytest.raises(BuildInUseError):
            accept_build(arguments, KEY, str(project["compile"]), str(project["configs"] / "seq_settings.json"))
    assert _status(project).state == BuildState.STALE


def test_a_rebuild_and_a_deletion_remove_the_file_list(project: Dict[str, Path]) -> None:
    _build(project)
    path = build_files_path_of(_project_dir(project), KEY)
    (project["root"] / "notes.txt").write_text("x\n")
    accept_build(
        _arguments(project["root"]), KEY, str(project["compile"]), str(project["configs"] / "seq_settings.json")
    )
    _build(project, policy=BuildPolicy.REBUILD)
    files = read_build_files(_project_dir(project), KEY)
    # a new build starts without the accepted changes of the old one
    assert files is not None and files.accepted == [] and "notes.txt" in files.sources
    delete_builds(_arguments(project["root"]))
    assert not os.path.exists(path)


def test_the_file_lists_are_no_builds_and_unknown_manifest_fields_are_ignored(project: Dict[str, Path]) -> None:
    _build(project)
    manifest = manifest_path_of(_project_dir(project), KEY)
    with open(manifest) as file:
        data = json.load(file)
    data["added_by_a_later_version"] = 1
    with open(manifest, "w") as file:
        json.dump(data, file)
    assert [record.build_id for record in list_builds(_project_dir(project))] == ["cfg_seq"]
    assert read_build(_project_dir(project), KEY) is not None


def test_the_fingerprint_contains_the_openmp_handling_only_when_the_flags_are_removed_in_instrumented_modes(
    project: Dict[str, Path],
) -> None:
    from discopop_library.ProjectManager.configurations.builds import compute_fingerprint_parts
    from discopop_library.ProjectManager.services import openmp_handling

    settings = str(project["configs"] / "dp_settings.json")
    for mode in ("seq", "par", "dp", "hd"):
        parts = compute_fingerprint_parts(
            _arguments(project["root"]), BuildKey("cfg", mode), str(project["compile"]), settings
        )
        assert "openmp" not in parts  # builds of before the setting stay current while the flags are kept
    openmp_handling.save_openmp_handling(_project_dir(project), openmp_handling.OpenMPHandling(strip=True))
    for mode in ("seq", "par", "dp", "hd"):
        parts = compute_fingerprint_parts(
            _arguments(project["root"]), BuildKey("cfg", mode), str(project["compile"]), settings
        )
        assert ("openmp" in parts) == (mode in ("dp", "hd"))


def test_a_dp_build_is_stale_when_the_openmp_flags_are_removed_and_the_change_cannot_be_accepted(
    project: Dict[str, Path],
) -> None:
    from discopop_library.ProjectManager.services import openmp_handling

    dp = BuildKey("cfg", "dp")
    assert _build(project, key=dp).result == BuildResult.BUILT
    assert _build(project, key=dp).result == BuildResult.REUSED
    openmp_handling.save_openmp_handling(_project_dir(project), openmp_handling.OpenMPHandling(strip=True))
    status = _status(project, dp)
    assert status.state == BuildState.STALE and status.changes is not None
    assert "openmp" in status.changes.parts
    assert "the OpenMP flags are now removed" in status.reason
    with pytest.raises(BuildAcceptError):
        accept_build(
            _arguments(project["root"]), dp, str(project["compile"]), str(project["configs"] / "dp_settings.json")
        )
    assert _build(project, key=dp).result == BuildResult.BUILT


def test_every_part_of_the_fingerprint_is_classified(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.builds import (
        CONTENT_PARTS,
        ENVIRONMENT_PARTS,
        TREE_PART,
        compute_fingerprint_parts,
    )
    from discopop_library.ProjectManager.services import openmp_handling
    from discopop_library.ProjectManager.services.included_directories import save_included_directories

    assert not CONTENT_PARTS & ENVIRONMENT_PARTS
    # switch on every optional part
    openmp_handling.save_openmp_handling(_project_dir(project), openmp_handling.OpenMPHandling(strip=True))
    save_callpath_pruning(_project_dir(project), CallpathPruning(enabled=True))
    shared = project["tmp"] / "shared"
    shared.mkdir()
    (shared / "lib.c").write_text("\n")
    save_included_directories(_project_dir(project), str(project["root"]), [str(shared)])
    save_copy_exclude(_project_dir(project), ["data"])
    (project["configs"] / "compile_incremental.sh").write_text("#!/bin/bash\n")
    seen = set()
    for mode in ("seq", "par", "dp", "hd"):
        for suggestions in ((), ("1",)):
            arguments = _arguments(project["root"])
            seen |= set(
                compute_fingerprint_parts(
                    arguments,
                    BuildKey("cfg", mode, suggestions),
                    str(project["compile"]),
                    str(project["configs"] / (mode + "_settings.json")),
                )
            )
    assert seen | {TREE_PART} == CONTENT_PARTS | ENVIRONMENT_PARTS  # TREE_PART is found, not computed


def test_the_role_is_part_of_the_id_and_survives_the_manifest(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.builds import ROLE_VALIDATE, key_of

    assert BuildKey("cfg", "par").build_id == "cfg_par"
    assert BuildKey("cfg", "par", (), ROLE_VALIDATE).build_id == "cfg_par_validate"
    outcome = _build(project, key=BuildKey("cfg", "seq", (), ROLE_VALIDATE))
    assert outcome.result == BuildResult.BUILT and outcome.record is not None
    (record,) = list_builds(_project_dir(project))
    assert key_of(record) == BuildKey("cfg", "seq", (), ROLE_VALIDATE)
    # a manifest of before the role (no field) is a build of the runs of its mode
    data = json.loads(Path(manifest_path_of(_project_dir(project), key_of(record))).read_text())
    del data["role"]
    (Path(_project_dir(project)) / "builds" / "cfg_seq.json").write_text(json.dumps(dict(data, build_id="cfg_seq")))
    old = read_build(_project_dir(project), BuildKey("cfg", "seq"))
    assert old is not None and old.role == "" and key_of(old) == BuildKey("cfg", "seq")


def test_only_content_changes_leave_the_environment_alone(project: Dict[str, Path]) -> None:
    _build(project)
    (project["root"] / "main.c").write_text("int main() { return 3; }\n")
    status = _status(project)
    assert status.changes is not None and status.changes.content_only
    project["compile"].write_text(project["compile"].read_text() + "\n# changed\n")
    status = _status(project)
    assert status.changes is not None and not status.changes.content_only


def _build_with_messages(project: Dict[str, Path], policy: BuildPolicy = BuildPolicy.AUTO) -> Tuple[BuildOutcome, str]:
    messages: List[str] = []
    arguments = _arguments(project["root"])
    with build_lock(arguments, KEY):
        outcome = ensure_build(
            arguments,
            KEY,
            str(project["configs"] / "cfg"),
            str(project["configs"] / "seq_settings.json"),
            str(project["compile"]),
            1,
            policy,
            message=messages.append,
        )
    return outcome, "".join(messages)


def test_a_kept_tree_is_updated_in_place_like_a_fresh_copy(project: Dict[str, Path]) -> None:
    (project["root"] / "other.c").write_text("int other;\n")
    first, text = _build_with_messages(project)
    assert first.result == BuildResult.BUILT and first.tree is not None and "Copying project" in text
    tree = Path(first.tree)
    (tree / "leftover.o").write_text("output of the last compilation\n")
    (tree / ".discopop" / "stale.txt").write_text("\n")
    other_written = os.stat(tree / "other.c").st_mtime_ns

    (project["root"] / "main.c").write_text("int main() { return 4; }\n")
    second, text = _build_with_messages(project)

    assert second.result == BuildResult.BUILT and second.tree == first.tree
    assert "Updating the build tree" in text and "Changed files written: 1" in text
    assert (tree / "main.c").read_text() == "int main() { return 4; }\n"
    assert (tree / "prog.out").exists()  # compiled again
    assert not (tree / "leftover.o").exists() and not (tree / ".discopop" / "stale.txt").exists()
    assert os.stat(tree / "other.c").st_mtime_ns == other_written
    assert _count(project, "compiles.txt") == 2
    assert _status(project).state == BuildState.CURRENT


def test_a_tree_in_an_unknown_state_is_copied_anew(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.builds import invalidate_build
    from discopop_library.ProjectManager.configurations.tree_sync import SYNCING, read_tree_state, set_tree_state

    _build_with_messages(project)
    state = read_tree_state(_project_dir(project), KEY.build_id)
    assert state is not None and state.state == "clean" and "main.c" in state.synced

    set_tree_state(_project_dir(project), KEY.build_id, SYNCING)  # interrupted
    assert "Copying project" in _build_with_messages(project, BuildPolicy.REBUILD)[1]

    invalidate_build(_project_dir(project), KEY)  # a validation build changed the outputs: synced, compiled in full
    outcome, text = _build_with_messages(project)
    assert outcome.result == BuildResult.BUILT and "Updating the build tree" in text


def test_a_failed_compilation_marks_the_tree_dirty(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.tree_sync import DIRTY, read_tree_state

    _build_with_messages(project)
    project["compile"].write_text("#!/bin/bash\nexit 1\n")
    outcome, _ = _build_with_messages(project)
    assert outcome.result == BuildResult.COMPILE_FAILED
    state = read_tree_state(_project_dir(project), KEY.build_id)
    assert state is not None and state.state == DIRTY


def test_the_data_runs_link_to_stays_when_the_tree_is_built_again(project: Dict[str, Path]) -> None:
    first, _ = _build_with_messages(project)
    assert first.tree is not None
    data = Path(first.tree) / ".discopop" / "static.txt"
    data.write_text("data of build 1\n")
    run_copy = project["tmp"] / "run_static.txt"
    os.link(data, run_copy)  # as configurations/runs.py links the static data of a build into a run

    (project["root"] / "main.c").write_text("int main() { return 5; }\n")
    _build_with_messages(project)

    assert run_copy.read_text() == "data of build 1\n"


def _add_suggestions(project: Dict[str, Path]) -> None:
    """Suggestion 1 patches main.c, 2 patches other.c, 9 does not apply."""
    import subprocess

    root, dot = project["root"], project["root"] / ".discopop"
    (root / "other.c").write_text("int other = 0;\n")
    (dot / "FileMapping.txt").write_text("1\t" + str(root / "main.c") + "\n2\t" + str(root / "other.c") + "\n")
    (dot / "line_mapping.json").write_text(json.dumps({"1": {"1": 1}, "2": {"1": 1}}))
    patched = {"1": ("main.c", 1, "int main() { return 7; }\n"), "2": ("other.c", 2, "int other = 2;\n")}
    patched["9"] = ("main.c", 1, "something else\n")
    for suggestion, (name, file_id, text) in patched.items():
        original = root / name
        modified = project["tmp"] / (name + "." + suggestion)
        modified.write_text(text)
        if suggestion == "9":
            original = project["tmp"] / "not_main.c"
            original.write_text("unrelated\n")
        diff = subprocess.run(["diff", "-Naru", str(original), str(modified)], stdout=subprocess.PIPE).stdout
        (dot / "patch_generator" / suggestion).mkdir(parents=True)
        (dot / "patch_generator" / suggestion / (str(file_id) + ".patch")).write_bytes(diff)


def _build_suggestions(project: Dict[str, Path], suggestions: Tuple[str, ...]) -> Tuple[BuildOutcome, str]:
    messages: List[str] = []
    arguments = _arguments(project["root"], apply_suggestions=",".join(suggestions) if suggestions else None)
    key = BuildKey("cfg", "seq", suggestions)
    with build_lock(arguments, key):
        outcome = ensure_build(
            arguments,
            key,
            str(project["configs"] / "cfg"),
            str(project["configs"] / "seq_settings.json"),
            str(project["compile"]),
            1,
            BuildPolicy.AUTO,
            message=messages.append,
        )
    return outcome, "".join(messages)


def test_the_builds_of_all_suggestion_sets_share_one_kept_tree(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.tree_sync import read_tree_state

    _add_suggestions(project)
    project_dir = _project_dir(project)

    first, text = _build_suggestions(project, ("1",))
    assert first.result == BuildResult.BUILT and first.tree is not None
    tree = Path(first.tree)
    assert tree.name == "cfg_seq" and "Copying project" in text
    assert (tree / "main.c").read_text() == "int main() { return 7; }\n"
    assert (tree / "prog.out").read_text() == "int main() { return 7; }\n"
    assert first.application_result is not None and first.application_result.applied == ["1"]
    assert (project["root"] / "main.c").read_text() == "int main() { return 0; }\n"  # the project is untouched
    assert _status(project, BuildKey("cfg", "seq", ("1",))).state == BuildState.CURRENT
    other_written = os.stat(tree / "other.c").st_mtime_ns

    second, text = _build_suggestions(project, ("2",))
    assert second.result == BuildResult.BUILT and second.tree == first.tree
    assert "Updating the build tree" in text and "Changed files written: 2" in text
    assert (tree / "main.c").read_text() == "int main() { return 0; }\n"  # the original is back
    assert (tree / "other.c").read_text() == "int other = 2;\n"
    assert os.stat(tree / "other.c").st_mtime_ns != other_written
    state = read_tree_state(project_dir, "cfg_seq")
    assert state is not None and state.applied == ["2"]
    # one build per tree: the build of suggestion 1 is gone, its id is free
    assert [r.build_id for r in list_builds(project_dir)] == [BuildKey("cfg", "seq", ("2",)).build_id]
    assert _status(project, BuildKey("cfg", "seq", ("1",))).state == BuildState.NONE
    (record,) = list_builds(project_dir)
    assert record.suggestions == ["2"]  # runs of it record the suggestions (activate_run refuses them)

    third, _ = _build_suggestions(project, ())
    assert third.result == BuildResult.BUILT and third.tree == first.tree
    assert (tree / "other.c").read_text() == "int other = 0;\n"
    assert _status(project, BuildKey("cfg", "seq", ("2",))).state == BuildState.NONE
    assert _status(project).state == BuildState.CURRENT


def test_a_failed_application_leaves_the_kept_tree_alone(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.tree_sync import read_tree_state

    _add_suggestions(project)
    first, _ = _build_suggestions(project, ("1",))
    assert first.tree is not None
    before = read_tree_state(_project_dir(project), "cfg_seq")

    failed, _ = _build_suggestions(project, ("9",))

    assert failed.result == BuildResult.APPLICATION_FAILED
    assert (Path(first.tree) / "main.c").read_text() == "int main() { return 7; }\n"
    assert read_tree_state(_project_dir(project), "cfg_seq") == before
    assert not Path(first.tree + ".scratch").exists()
    assert _status(project, BuildKey("cfg", "seq", ("1",))).state == BuildState.CURRENT


def test_a_build_whose_tree_holds_another_build_is_stale_and_cannot_be_accepted(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.tree_sync import TreeState, write_tree_state

    _build(project)
    write_tree_state(_project_dir(project), "cfg_seq", TreeState({}, ["5"], "clean"))
    status = _status(project)
    assert status.state == BuildState.STALE and status.changes is not None
    assert status.changes.parts == ("tree",) and "suggestions 5" in status.reason
    arguments = _arguments(project["root"])
    with pytest.raises(BuildAcceptError):
        accept_build(arguments, KEY, str(project["compile"]), str(project["configs"] / "seq_settings.json"))


def test_the_builds_of_one_tree_share_its_lock(project: Dict[str, Path]) -> None:
    from discopop_library.ProjectManager.configurations.builds import ROLE_VALIDATE, build_lock_path_of

    project_dir = _project_dir(project)
    one, other = BuildKey("cfg", "par", ("1",)), BuildKey("cfg", "par", ("2", "3"))
    assert build_lock_path_of(project_dir, one) == build_lock_path_of(project_dir, other)
    assert build_lock_path_of(project_dir, one) == build_lock_path_of(project_dir, BuildKey("cfg", "par"))
    assert build_lock_path_of(project_dir, one) != build_lock_path_of(project_dir, BuildKey("cfg", "seq"))
    assert build_lock_path_of(project_dir, one) != build_lock_path_of(
        project_dir, BuildKey("cfg", "par", (), ROLE_VALIDATE)
    )


def _incremental_project(project: Dict[str, Path], incremental: str) -> None:
    """compile.sh and compile_incremental.sh note in kinds.txt which ran, with DP_BUILD_KIND."""
    kinds = project["tmp"] / "kinds.txt"
    project["compile"].write_text(f'#!/bin/bash\necho "full $DP_BUILD_KIND" >> "{kinds}"\ncp main.c prog.out\n')
    (project["configs"] / "compile_incremental.sh").write_text(
        f'#!/bin/bash\necho "incremental $DP_BUILD_KIND" >> "{kinds}"\n' + incremental
    )


def _kinds(project: Dict[str, Path]) -> List[str]:
    return (project["tmp"] / "kinds.txt").read_text().splitlines()


def test_a_kept_tree_is_compiled_again_incrementally(project: Dict[str, Path]) -> None:
    _incremental_project(project, "cp main.c prog.out\n")
    first, _ = _build_with_messages(project)
    assert first.record is not None and first.record.build_kind == "full"

    (project["root"] / "main.c").write_text("int main() { return 6; }\n")
    second, text = _build_with_messages(project)

    assert second.result == BuildResult.BUILT and second.record is not None
    assert "Compiling incrementally (compile_incremental.sh)" in text
    assert _kinds(project) == ["full full", "incremental incremental"]
    assert second.record.build_kind == "incremental"
    assert (Path(second.tree or "") / "prog.out").read_text() == "int main() { return 6; }\n"
    # --rebuild compiles in full
    _build_with_messages(project, BuildPolicy.REBUILD)
    assert _kinds(project)[-1] == "full full"


def test_an_incremental_build_that_rebuilt_nothing_falls_back_to_a_full_build(project: Dict[str, Path]) -> None:
    # like the outer build of a superbuild: succeeds, writes nothing
    _incremental_project(project, "true\n")
    _build_with_messages(project)
    (project["root"] / "main.c").write_text("int main() { return 8; }\n")

    outcome, text = _build_with_messages(project)

    assert outcome.result == BuildResult.BUILT and outcome.record is not None
    assert "wrote no file although 1 file(s) of the project changed" in text
    assert _kinds(project) == ["full full", "incremental incremental", "full full"]
    assert outcome.record.build_kind == "full"
    assert (Path(outcome.tree or "") / "prog.out").read_text() == "int main() { return 8; }\n"


def test_a_failing_incremental_build_falls_back_to_a_full_build(project: Dict[str, Path]) -> None:
    _incremental_project(project, "exit 2\n")
    _build_with_messages(project)
    (project["root"] / "main.c").write_text("int main() { return 9; }\n")

    outcome, text = _build_with_messages(project)

    assert outcome.result == BuildResult.BUILT and "compile_incremental.sh failed" in text
    assert _kinds(project)[-1] == "full full"


def test_only_a_tree_compiled_in_the_same_environment_and_mode_is_compiled_incrementally(
    project: Dict[str, Path],
) -> None:
    from discopop_library.ProjectManager.configurations.builds import invalidate_build

    _incremental_project(project, "cp main.c prog.out\n")
    _build_with_messages(project)
    # another settings file: in full
    (project["configs"] / "seq_settings.json").write_text(
        json.dumps({"CC": "cc", "CXX": "c++", "CFLAGS": "-O1", "CXXFLAGS": ""})
    )
    _build_with_messages(project)
    assert _kinds(project)[-1] == "full full"
    # a validation build changed the outputs: in full
    invalidate_build(_project_dir(project), KEY)
    (project["root"] / "main.c").write_text("int main() { return 10; }\n")
    _build_with_messages(project)
    assert _kinds(project)[-1] == "full full"
    # now incrementally
    (project["root"] / "main.c").write_text("int main() { return 11; }\n")
    _build_with_messages(project)
    assert _kinds(project)[-1] == "incremental incremental"
    # instrumented modes are always compiled in full
    dp_key = BuildKey("cfg", "dp")
    for _ in range(2):
        (project["root"] / "main.c").write_text("int main() { return %d; }\n" % (20 + _))
        _build(project, key=dp_key)
    assert _kinds(project)[-2:] == ["full full", "full full"]
