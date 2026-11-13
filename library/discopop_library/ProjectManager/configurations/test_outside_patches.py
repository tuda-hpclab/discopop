# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Suggestions that patch files outside the project: the project manager's copies, "auto" / "prm" and the rollback."""

import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest import mock

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    get_application_result,
    restore_outside_patches,
)
from discopop_library.ProjectManager.configurations.deletion import delete_configuration
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.jobs import WorkContext

ORIGINAL = "int main() {\n  int i = 0;\n  return i;\n}\n"
PATCHED = "int main() {\n  int i = 1;\n  return i;\n}\n"


def _arguments(project_root: Path, apply_suggestions: Optional[str], allow: bool = False) -> ProjectManagerArguments:
    return ProjectManagerArguments(
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
        apply_suggestions=apply_suggestions,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        allow_patching_outside_project=allow,
    )


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Dict[str, Path]]:
    """Suggestion 1 patches ``proj/main.c``, suggestion 2 patches ``shared/main.c`` outside of the project."""
    root = tmp_path / "proj"
    shared = tmp_path / "shared"
    # a sibling whose name starts with the name of the project must keep its path in the copy
    sibling = tmp_path / "proj2"
    for directory in (root, shared, sibling):
        directory.mkdir()
    inside, outside, other = root / "main.c", shared / "main.c", sibling / "main.c"
    modified = tmp_path / "modified.c"
    modified.write_text(PATCHED)
    dot = root / ".discopop"
    (dot / "patch_generator" / "1").mkdir(parents=True)
    (dot / "patch_generator" / "2").mkdir()
    (dot / "project" / "configs").mkdir(parents=True)
    with open(dot / "FileMapping.txt", "w") as f:
        f.write(f"1\t{inside}\n2\t{outside}\n3\t{other}\n")
    for source, file_id, suggestion_id in ((inside, 1, "1"), (outside, 2, "2")):
        source.write_text(ORIGINAL)
        diff = subprocess.run(["diff", "-Naru", str(source), str(modified)], stdout=subprocess.PIPE).stdout
        (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_bytes(diff)
    other.write_text(ORIGINAL)
    (dot / "line_mapping.json").write_text(json.dumps({"1": {"1": 1, "2": 2, "3": 3, "4": 4}, "2": {"1": 1}}))
    yield {"root": root, "inside": inside, "outside": outside, "other": other, "dot": dot}


def _write_results(dot: Path, tool_directory: str, suggestions: list) -> None:  # type: ignore[type-arg]
    path = dot / tool_directory / "results.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"cfg": {"applied_suggestions": suggestions}}))


def test_the_copy_keeps_the_paths_of_directories_that_only_look_like_the_project(project: Dict[str, Path]) -> None:
    copy = copy_configuration(_arguments(project["root"], None), "cfg", "settings")
    mapping = Path(copy, ".discopop", "FileMapping.txt").read_text().splitlines()
    assert mapping == [f"1\t{copy}/main.c", f"2\t{project['outside']}", f"3\t{project['other']}"]


def test_an_explicit_application_refuses_outside_targets_by_default(project: Dict[str, Path]) -> None:
    copy = copy_configuration(_arguments(project["root"], "1,2"), "cfg", "settings")
    result = get_application_result(copy)
    assert result is not None
    assert result.applied == ["1"] and result.refused == ["2"] and result.failure
    assert project["outside"].read_text() == ORIGINAL
    assert (Path(copy) / "main.c").read_text() == PATCHED
    # the original project is never touched
    assert project["inside"].read_text() == ORIGINAL


def test_the_permission_applies_outside_targets_and_the_rollback_restores_them(project: Dict[str, Path]) -> None:
    arguments = _arguments(project["root"], "2", allow=True)
    copy = copy_configuration(arguments, "cfg", "settings")
    result = get_application_result(copy)
    assert result is not None and result.applied == ["2"] and result.complete
    assert project["outside"].read_text() == PATCHED

    assert restore_outside_patches(copy) == ["2"]
    assert project["outside"].read_text() == ORIGINAL
    # idempotent: a second call finds nothing applied any more
    assert restore_outside_patches(copy) == []
    assert project["outside"].read_text() == ORIGINAL

    # the next copy can apply it again, which it could not if the file were still patched
    copy = copy_configuration(arguments, "cfg", "settings")
    assert project["outside"].read_text() == PATCHED
    delete_configuration(arguments, copy)
    assert project["outside"].read_text() == ORIGINAL
    assert not os.path.exists(copy)


def test_the_rollback_leaves_suggestions_inside_the_project_alone(project: Dict[str, Path]) -> None:
    copy = copy_configuration(_arguments(project["root"], "1,2", allow=True), "cfg", "settings")
    assert restore_outside_patches(copy) == ["2"]
    assert project["outside"].read_text() == ORIGINAL
    assert (Path(copy) / "main.c").read_text() == PATCHED


def test_a_rollback_without_an_application_does_nothing(project: Dict[str, Path]) -> None:
    copy = copy_configuration(_arguments(project["root"], None), "cfg", "settings")
    assert restore_outside_patches(copy) == []
    assert restore_outside_patches(str(project["root"] / "missing")) == []


@pytest.mark.parametrize("keyword,directory", [("auto", "auto_tuner"), ("prm", "parallel_region_merger")])
def test_auto_and_prm_skip_outside_suggestions_even_if_allowed(
    project: Dict[str, Path], keyword: str, directory: str, caplog: pytest.LogCaptureFixture
) -> None:
    _write_results(project["dot"], directory, ["1", "2"])
    with caplog.at_level("WARNING", logger="ConfigurationManager"):
        copy = copy_configuration(_arguments(project["root"], keyword, allow=True), "cfg", "settings")
    result = get_application_result(copy)
    assert result is not None
    # suggestion 2 is neither applied nor reported as failed: it is not part of the selection
    assert result.requested == ["1"] and result.applied == ["1"] and result.complete
    assert project["outside"].read_text() == ORIGINAL
    assert "skipping 1 suggestion(s) that patch files outside the project" in caplog.text
    assert "suggestion 2:" in caplog.text


# ── a run of the Execute stage ───────────────────────────────────────────────


def _run(project: Dict[str, Path], allow: bool, skip_cleanup: bool, behaviour: str) -> Dict[str, object]:
    """Run the manual selection of suggestion 2 in mode seq; ``behaviour``: ok, compile_fails, stopped.

    Returns what the fake build saw of the file outside the project, and the failures reported by the run.
    """
    configs = project["dot"] / "project" / "configs"
    (configs / "cfg").mkdir(exist_ok=True)
    (configs / "cfg" / "compile.sh").write_text("true\n")
    (configs / "cfg" / "execute.sh").write_text("true\n")
    (configs / "seq_settings.json").write_text("{}")
    arguments = _arguments(project["root"], None)
    request = execution_run.ExecutionRequest(
        configuration="cfg",
        modes=("seq",),
        inplace=False,
        skip_cleanup=skip_cleanup,
        thread_count=1,
        label_prefix="",
        timeout_execution=0,
        timeout_compilation=0,
        timeout_validation=0,
        repetitions=1,
        log_level="WARNING",
        suggestion_ids=("2",),
        allow_patching_outside_project=allow,
    )
    cancel = threading.Event()
    ctx = WorkContext(queue.Queue(), cancel)
    seen: List[str] = []

    def fake_execute(*args: Any, **kwargs: Any) -> Optional[Tuple[int, float, str, str]]:
        seen.append(project["outside"].read_text())
        if behaviour == "compile_fails":
            return None
        if behaviour == "stopped":
            cancel.set()
        return (0, 0.1, "", "")

    with mock.patch.object(execution_run, "execute_configuration", fake_execute):
        failures = execution_run.run_execution(arguments, request, ctx)
    return {"seen": seen, "failures": failures}


@pytest.mark.parametrize("skip_cleanup", [False, True])
@pytest.mark.parametrize("behaviour", ["ok", "compile_fails", "stopped"])
def test_a_run_restores_the_files_outside_the_project_however_it_ends(
    project: Dict[str, Path], behaviour: str, skip_cleanup: bool
) -> None:
    outcome = _run(project, allow=True, skip_cleanup=skip_cleanup, behaviour=behaviour)
    # the build ran against the patched file ...
    assert outcome["seen"][0] == PATCHED  # type: ignore[index]
    # ... and the shared original is back as it was
    assert project["outside"].read_text() == ORIGINAL


def test_a_run_without_the_permission_does_not_run_and_does_not_touch_the_file(project: Dict[str, Path]) -> None:
    outcome = _run(project, allow=False, skip_cleanup=False, behaviour="ok")
    assert outcome["seen"] == []
    failures = outcome["failures"]
    assert len(failures) == 1 and failures[0][1].refused == ["2"]  # type: ignore[index, arg-type]
    assert project["outside"].read_text() == ORIGINAL


@pytest.mark.parametrize("flag,expected", [([], False), (["--allow-patching-outside-project"], True)])
def test_the_command_line_flag_allows_patching_outside_the_project(
    project: Dict[str, Path], monkeypatch: pytest.MonkeyPatch, flag: list, expected: bool  # type: ignore[type-arg]
) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr("sys.argv", ["discopop", "-p", str(project["root"]), "--apply-suggestions", "2"] + flag)
    arguments = parse_args()
    assert arguments.apply_suggestions == "2" and arguments.allow_patching_outside_project is expected
    # without the flag, the copy of the run refuses the suggestion (see above): the default is the safe one
    copy = copy_configuration(arguments, "cfg", "settings")
    result = get_application_result(copy)
    assert result is not None and (result.applied == ["2"]) is expected and (result.refused == ["2"]) is not expected
    restore_outside_patches(copy)
    assert project["outside"].read_text() == ORIGINAL
