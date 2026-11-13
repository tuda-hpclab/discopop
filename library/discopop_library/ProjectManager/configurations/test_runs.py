# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the runs: profiling runs of a build keep their results apart, and a run can be put into the project."""

import json
import os
import queue
import threading
from pathlib import Path
from typing import Dict, Iterator

import pytest

from discopop_library.ProjectManager.configurations import runs
from discopop_library.ProjectManager.configurations.builds import list_builds
from discopop_library.ProjectManager.configurations.runs import (
    ActivationError,
    activate_run,
    delete_runs,
    latest_successful_run,
    list_all_runs,
    replace_in_file,
)
from discopop_library.ProjectManager.configurations.test_builds import _arguments
from discopop_library.ProjectManager.services import execution_run
from discopop_library.ProjectManager.services.jobs import WorkContext

COMPILE = """#!/bin/bash
mkdir -p "$DOT_DISCOPOP/profiler"
printf '1\\t%s/main.c\\n' "$DP_PROJECT_ROOT_DIR" > "$DOT_DISCOPOP/FileMapping.txt"
printf '{"file": "%s/main.c"}' "$DP_PROJECT_ROOT_DIR" > "$DOT_DISCOPOP/profiler/ast_dump.json"
echo static > "$DOT_DISCOPOP/profiler/Data.xml"
echo 7 > "$DOT_DISCOPOP/profiler/DP_CUIDCounter.txt"
echo compiled >> "COUNTER"
"""
EXECUTE = """#!/bin/bash
echo "run with $INPUT_MARKER" > "$DOT_DISCOPOP/profiler/dynamic_dependencies.txt"
echo "dot=$DOT_DISCOPOP" >> "COUNTER2"
"""


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Dict[str, Path]]:
    root = tmp_path / "proj"
    configs = root / ".discopop" / "project" / "configs"
    (configs / "cfg").mkdir(parents=True)
    (root / "main.c").write_text("int main() { return 0; }\n")
    (configs / "compile.sh").write_text(COMPILE.replace("COUNTER", str(tmp_path / "compiles.txt")))
    (configs / "cfg" / "execute.sh").write_text(EXECUTE.replace("COUNTER2", str(tmp_path / "executions.txt")))
    for mode in ("seq", "dp", "hd", "par"):
        (configs / (mode + "_settings.json")).write_text(
            json.dumps({"CC": "cc", "CXX": "c++", "CFLAGS": "", "CXXFLAGS": "", "INPUT_MARKER": "A"})
        )
    yield {"root": root, "configs": configs, "tmp": tmp_path}


def _run(project: Dict[str, Path], mode: str = "dp", **kw: object) -> None:
    arguments = _arguments(project["root"])
    request = execution_run.ExecutionRequest(
        configuration="cfg",
        modes=(mode,),
        inplace=False,
        skip_cleanup=False,
        thread_count=2,
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


def test_every_profiling_run_keeps_its_results_in_a_directory_of_its_own(project: Dict[str, Path]) -> None:
    _run(project)
    (project["configs"] / "dp_settings.json").write_text(
        json.dumps({"CC": "cc", "CXX": "c++", "CFLAGS": "", "CXXFLAGS": "", "INPUT_MARKER": "B"})
    )
    _run(project)
    arguments = _arguments(project["root"])

    # the settings are an input of the compilation: B compiled again, so there are two builds' worth of data;
    # the point here is that the runs of one build never share a directory
    runs_found = list_all_runs(arguments)
    assert len(runs_found) == 2
    assert len({run.dot_discopop for run in runs_found}) == 2
    assert all(run.return_code == 0 for run in runs_found)
    (build,) = list_builds(arguments.project_dir)
    assert not (Path(build.tree) / ".discopop" / "profiler" / "dynamic_dependencies.txt").exists()
    # building again does not delete the runs of the build before
    assert all(os.path.isdir(run.dot_discopop) for run in runs_found)


def test_two_runs_of_one_build_do_not_overwrite_each_other_and_share_the_static_data(project: Dict[str, Path]) -> None:
    _run(project)
    execute = project["configs"] / "cfg" / "execute.sh"
    execute.write_text(execute.read_text().replace("run with", "second run with"))
    _run(project)
    assert (project["tmp"] / "compiles.txt").read_text().count("compiled") == 1

    arguments = _arguments(project["root"])
    first, second = list_all_runs(arguments)
    assert first.build_id == second.build_id and first.run_id != second.run_id
    assert (Path(first.dot_discopop) / "profiler" / "dynamic_dependencies.txt").read_text() == "run with A\n"
    assert (Path(second.dot_discopop) / "profiler" / "dynamic_dependencies.txt").read_text() == "second run with A\n"
    first_static = os.stat(Path(first.dot_discopop) / "profiler" / "Data.xml")
    second_static = os.stat(Path(second.dot_discopop) / "profiler" / "Data.xml")
    # the static data is shared, the files a run changes are not
    assert first_static.st_ino == second_static.st_ino
    assert (
        os.stat(Path(first.dot_discopop) / "profiler" / "DP_CUIDCounter.txt").st_ino
        != os.stat(Path(second.dot_discopop) / "profiler" / "DP_CUIDCounter.txt").st_ino
    )
    # the program ran with the directory of its run
    assert f"dot={second.dot_discopop}" in (project["tmp"] / "executions.txt").read_text()


def test_the_measurement_names_the_build_and_the_run(project: Dict[str, Path]) -> None:
    _run(project)
    arguments = _arguments(project["root"])
    (run,) = list_all_runs(arguments)
    with open(Path(arguments.project_dir) / "execution_results.json") as f:
        results = json.load(f)["cfg"]
    (execute,) = results["execute.sh"]["dp_settings.json"]
    assert execute["run_id"] == run.run_id and execute["build_id"] == "cfg_dp"
    (compile_entry,) = results["compile.sh"]["dp_settings.json"]
    assert compile_entry["build_id"] == "cfg_dp" and "run_id" not in compile_entry


def test_runs_of_other_modes_than_the_profiling_ones_have_no_run_directory(project: Dict[str, Path]) -> None:
    (project["configs"] / "cfg" / "execute.sh").write_text("#!/bin/bash\ntrue\n")
    _run(project, mode="seq")
    assert list_all_runs(_arguments(project["root"])) == []


def test_activating_a_run_puts_its_data_into_the_project(project: Dict[str, Path]) -> None:
    _run(project)
    arguments = _arguments(project["root"])
    (run,) = list_all_runs(arguments)
    assert latest_successful_run(arguments) == run
    # earlier data of the project is replaced, and so are the results derived from it left alone
    (project["root"] / ".discopop" / "profiler").mkdir()
    (project["root"] / ".discopop" / "profiler" / "old.txt").write_text("old")
    (project["root"] / ".discopop" / "explorer").mkdir()

    assert sorted(activate_run(arguments, run)) == [
        "FileMapping.txt",
        "instrumented_project_directories.json",
        "profiler",
    ]
    dot = project["root"] / ".discopop"
    assert not (dot / "profiler" / "old.txt").exists()
    assert (dot / "profiler" / "dynamic_dependencies.txt").read_text() == "run with A\n"
    assert (dot / "explorer").is_dir()
    # the paths are those of the project, not of the build tree
    assert (dot / "FileMapping.txt").read_text() == f"1\t{project['root']}/main.c\n"
    assert json.loads((dot / "profiler" / "ast_dump.json").read_text()) == {"file": f"{project['root']}/main.c"}
    assert json.loads((dot / "active_run.json").read_text())["run_id"] == run.run_id
    # the run itself is untouched
    assert "_discopop_builds" in (Path(run.dot_discopop) / "FileMapping.txt").read_text()
    # data of the project is a copy: changing it does not change the run
    (dot / "profiler" / "dynamic_dependencies.txt").write_text("changed")
    assert (Path(run.dot_discopop) / "profiler" / "dynamic_dependencies.txt").read_text() == "run with A\n"


def test_a_run_that_failed_or_whose_build_has_suggestions_cannot_be_activated(project: Dict[str, Path]) -> None:
    _run(project)
    arguments = _arguments(project["root"])
    (run,) = list_all_runs(arguments)
    failed = runs.RunRecord(**{**run.__dict__, "return_code": 1})
    with pytest.raises(ActivationError, match="successfully"):
        activate_run(arguments, failed)
    unfinished = runs.RunRecord(**{**run.__dict__, "return_code": None})
    with pytest.raises(ActivationError):
        activate_run(arguments, unfinished)
    with_suggestions = runs.RunRecord(**{**run.__dict__, "suggestions": ["3"]})
    with pytest.raises(ActivationError, match="suggestions"):
        activate_run(arguments, with_suggestions)
    assert not (project["root"] / ".discopop" / "profiler").exists()


def test_deleting_runs(project: Dict[str, Path]) -> None:
    _run(project)
    _run(project)
    arguments = _arguments(project["root"])
    first, second = list_all_runs(arguments)
    assert delete_runs(arguments, [first.run_id, "unknown"]) == [first.run_id]
    assert not os.path.exists(first.dot_discopop) and os.path.isdir(second.dot_discopop)
    assert delete_runs(arguments) == [second.run_id]
    # the build and the project stay
    assert len(list_builds(arguments.project_dir)) == 1 and (project["root"] / "main.c").exists()


@pytest.mark.parametrize("chunk", [1, 3, 7, 16, 1000])
def test_replacing_paths_works_across_the_boundaries_of_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk: int
) -> None:
    monkeypatch.setattr(runs, "_CHUNK_SIZE", chunk)
    old, new = "/b/tree_xyz", "/p"
    content = ("a" * 5 + old + "b" * 11 + old + old + "c" + old[:-1] + "." + old).encode()
    source, destination = tmp_path / "in", tmp_path / "out"
    source.write_bytes(content)
    assert replace_in_file(str(source), str(destination), old, new) is True
    assert destination.read_bytes() == content.replace(old.encode(), new.encode())
    source.write_bytes(b"nothing to replace /b/tree")
    assert replace_in_file(str(source), str(destination), old, new) is False
    assert destination.read_bytes() == b"nothing to replace /b/tree"


@pytest.mark.parametrize(
    "flags,expected",
    [(["--list-runs"], "list_runs"), (["--delete-runs", "a,b"], "delete_runs"), (["--activate-run"], "activate_run")],
)
def test_the_command_line_has_the_run_options(
    project: Dict[str, Path], monkeypatch: pytest.MonkeyPatch, flags: list, expected: str  # type: ignore[type-arg]
) -> None:
    from discopop_library.ProjectManager.__main__ import parse_args

    monkeypatch.setattr("sys.argv", ["discopop", "-p", str(project["root"])] + flags)
    assert getattr(parse_args(), expected) not in (None, False)


def test_listing_deleting_and_activating_runs_on_the_command_line(
    project: Dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from discopop_library.ProjectManager.utilities.CLI.runs import (
        activate_run_from_cli,
        delete_runs_from_cli,
        show_runs,
    )

    arguments = _arguments(project["root"])
    show_runs(arguments)
    assert "No runs" in capsys.readouterr().out
    _run(project)
    show_runs(arguments)
    assert "cfg_dp" in capsys.readouterr().out
    arguments.activate_run = "latest"
    activate_run_from_cli(arguments)
    assert "Activated the run" in capsys.readouterr().out
    show_runs(arguments)
    assert "yes" in capsys.readouterr().out
    arguments.delete_runs = "all"
    delete_runs_from_cli(arguments)
    assert "Deleted 1 run(s)" in capsys.readouterr().out
