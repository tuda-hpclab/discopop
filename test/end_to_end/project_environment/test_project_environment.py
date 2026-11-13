# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The project directories (excluded directories inside the project, included ones outside of it) and the checks of
instrumented builds and runs, through the project manager's command line with the real profiler.

The program in src/ consists of src/main.cpp and a header-only "third-party library" third_party/lib.h. With
third_party excluded, only main.cpp may be instrumented; a header outside the project is only instrumented if its
directory is included. A build or a run that loses DOT_DISCOPOP has to fail
instead of reporting success without results (see
discopop_library.ProjectManager.configurations.instrumentation_checks)."""

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any, Dict, List

import pytest

from discopop_library.ProjectManager.services.excluded_directories import save_excluded_directories
from discopop_library.ProjectManager.services.included_directories import save_included_directories

SRC_DIR = pathlib.Path(__file__).parent / "src"

# Builds out of tree in build/, as CMake does, so that a compiler call without DOT_DISCOPOP writes elsewhere.
COMPILE_SH = """#!/bin/bash
mkdir -p build && cd build && $CXX $CXXFLAGS ../src/main.cpp -o prog
"""

# The same build, with DOT_DISCOPOP removed on the way to the compiler.
COMPILE_SH_LOSING_DOT_DISCOPOP = """#!/bin/bash
mkdir -p build && cd build && env -u DOT_DISCOPOP $CXX $CXXFLAGS ../src/main.cpp -o prog
"""

EXECUTE_SH = """#!/bin/bash
build/prog
"""

# Starts the program from another directory without DOT_DISCOPOP: it cannot find its .discopop.
EXECUTE_SH_LOSING_DOT_DISCOPOP = """#!/bin/bash
prog="$PWD/build/prog"
cd build && env -u DOT_DISCOPOP "$prog"
"""


def _write_script(path: pathlib.Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _project(tmp_path: pathlib.Path, compile_sh: str = COMPILE_SH, execute_sh: str = EXECUTE_SH) -> pathlib.Path:
    """A project manager project with the program of src/ and the configuration "tiny"."""
    root = tmp_path / "proj"
    shutil.copytree(SRC_DIR, root)
    _run_project_manager(root, "--init")
    configs = root / ".discopop" / "project" / "configs"
    (configs / "tiny").mkdir()
    _write_script(configs / "compile.sh", compile_sh)
    _write_script(configs / "tiny" / "execute.sh", execute_sh)
    return root


def _run_project_manager(root: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess:  # type: ignore
    return subprocess.run(
        ["discopop_project_manager", "-p", str(root), *arguments],
        capture_output=True,
        text=True,
        timeout=600,
    )


def _project_dir(root: pathlib.Path) -> str:
    return str(root / ".discopop" / "project")


def _results(root: pathlib.Path, script: str) -> List[Dict[str, Any]]:
    """The recorded dp runs of ``script`` of the configuration tiny."""
    with open(root / ".discopop" / "project" / "execution_results.json") as f:
        results: List[Dict[str, Any]] = json.load(f)["tiny"][script]["dp_settings.json"]
    return results


def _file_mapping(dot_discopop: pathlib.Path) -> List[str]:
    path = dot_discopop / "FileMapping.txt"
    return path.read_text().splitlines() if path.exists() else []


def _profile(root: pathlib.Path, *arguments: str) -> subprocess.CompletedProcess:  # type: ignore
    return _run_project_manager(root, "-x", "tiny:dp", "-i", *arguments)


def _only_entry(root: pathlib.Path, script: str) -> Dict[str, Any]:
    entries = _results(root, script)
    assert len(entries) == 1, entries
    return entries[0]


def _output(process: "subprocess.CompletedProcess[str]") -> str:
    return process.stdout + process.stderr


def test_default_scope_instruments_the_whole_project(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    process = _profile(root)
    assert _only_entry(root, "compile.sh")["code"] == 0, _output(process)
    assert _only_entry(root, "execute.sh")["code"] == 0, _output(process)
    mapping = _file_mapping(root / ".discopop")
    assert any(line.endswith("/src/main.cpp") for line in mapping), mapping
    assert any(line.endswith("/third_party/lib.h") for line in mapping), mapping
    assert (root / ".discopop" / "profiler" / "dynamic_dependencies.txt").exists()


def test_an_excluded_directory_is_left_out(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    save_excluded_directories(_project_dir(root), ["third_party"])
    process = _profile(root)
    assert _only_entry(root, "compile.sh")["code"] == 0, _output(process)
    execute = _only_entry(root, "execute.sh")
    assert execute["code"] == 0, _output(process)
    assert execute["project_directories"] == {"included": [], "excluded": ["third_party"]}
    mapping = _file_mapping(root / ".discopop")
    assert any(line.endswith("/src/main.cpp") for line in mapping), mapping
    assert not any("third_party" in line for line in mapping), mapping


def test_command_line_exclusion_applies_to_the_copy_of_the_project(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    process = _run_project_manager(root, "-x", "tiny:dp", "--project-exclude-dirs", "third_party")
    # the copy is the build of the configuration and mode, which is kept
    copies = [path for path in (tmp_path / "proj_discopop_builds").iterdir() if path.name == "tiny_dp"]
    assert len(copies) == 1, _output(process)
    mapping = _file_mapping(copies[0] / ".discopop")
    assert mapping and all(str(copies[0] / "src") + "/" in line for line in mapping), mapping


def _project_with_shared_header(tmp_path: pathlib.Path) -> pathlib.Path:
    """The project with lib.h moved to a directory outside of it, included by its absolute path."""
    root = _project(tmp_path)
    shared = tmp_path / "shared"
    shutil.move(str(root / "third_party"), str(shared))
    main = root / "src" / "main.cpp"
    main.write_text(main.read_text().replace('"../third_party/lib.h"', '"' + str(shared / "lib.h") + '"'))
    return root


def test_a_directory_outside_the_project_is_only_instrumented_if_included(tmp_path: pathlib.Path) -> None:
    root = _project_with_shared_header(tmp_path)
    process = _profile(root)
    assert _only_entry(root, "execute.sh")["code"] == 0, _output(process)
    assert not any("shared" in line for line in _file_mapping(root / ".discopop"))

    save_included_directories(_project_dir(root), str(root), [str(tmp_path / "shared")])
    shutil.rmtree(root / ".discopop" / "profiler")
    (root / ".discopop" / "FileMapping.txt").unlink()
    process = _profile(root)
    assert _results(root, "execute.sh")[-1]["code"] == 0, _output(process)
    mapping = _file_mapping(root / ".discopop")
    assert any(line.endswith("/shared/lib.h") for line in mapping), mapping


def test_everything_excluded_warns(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    save_excluded_directories(_project_dir(root), ["src", "third_party"])
    process = _profile(root)
    compile_entry = _only_entry(root, "compile.sh")
    assert compile_entry["code"] == 0, _output(process)
    assert "No instrumented file lies in the project directory" in compile_entry["stderr"]


def test_a_build_losing_dot_discopop_fails(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, compile_sh=COMPILE_SH_LOSING_DOT_DISCOPOP)
    process = _profile(root)
    compile_entry = _only_entry(root, "compile.sh")
    assert compile_entry["code"] != 0, _output(process)
    assert str(root / "build" / ".discopop") in compile_entry["stderr"]


def test_a_run_losing_dot_discopop_fails(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, execute_sh=EXECUTE_SH_LOSING_DOT_DISCOPOP)
    process = _profile(root)
    assert _only_entry(root, "compile.sh")["code"] == 0, _output(process)
    execute = _only_entry(root, "execute.sh")
    assert execute["code"] != 0, _output(process)
    assert "dynamic_dependencies.txt" in execute["stderr"]


@pytest.mark.parametrize("variable", ["DP_PROJECT_ROOT_DIR", "DOT_DISCOPOP"])
def test_a_project_variable_in_the_settings_is_removed(tmp_path: pathlib.Path, variable: str) -> None:
    root = _project(tmp_path)
    settings_path = root / ".discopop" / "project" / "configs" / "seq_settings.json"
    settings = json.loads(settings_path.read_text())
    settings[variable] = "/somewhere/else"
    settings_path.write_text(json.dumps(settings))
    process = _profile(root)
    assert variable not in json.loads(settings_path.read_text())
    assert "Removed " + variable + "=/somewhere/else" in _output(process)
    assert _only_entry(root, "execute.sh")["code"] == 0, _output(process)


def test_an_obsolete_scope_file_is_reported(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    (root / ".discopop" / "project" / "configs" / "project_environment.json").write_text(
        '{"DP_PROJECT_ROOT_DIR": "src"}'
    )
    process = _profile(root)
    assert "project_environment.json is no longer read" in _output(process)
    assert os.access(root / ".discopop" / "project" / "configs" / "compile.sh", os.X_OK)
