# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The instrumentation scope and the checks of instrumented builds and runs, through the project manager's
command line with the real profiler.

The program in src/ consists of src/main.cpp and a header-only "third-party library" third_party/lib.h. With
the scope src, only main.cpp may be instrumented. A build or a run that loses DOT_DISCOPOP has to fail
instead of reporting success without results (see
discopop_library.ProjectManager.configurations.instrumentation_checks)."""

import json
import os
import pathlib
import shutil
import subprocess
from typing import Any, Dict, List, Optional

import pytest

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


def _set_scope(root: pathlib.Path, scope: str) -> None:
    path = root / ".discopop" / "project" / "configs" / "project_environment.json"
    path.write_text(json.dumps({"DP_PROJECT_ROOT_DIR": scope}))


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


def test_scope_leaves_the_third_party_code_out(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    _set_scope(root, "src")
    process = _profile(root)
    assert _only_entry(root, "compile.sh")["code"] == 0, _output(process)
    execute = _only_entry(root, "execute.sh")
    assert execute["code"] == 0, _output(process)
    assert execute["instrumentation_scope"] == "src"
    mapping = _file_mapping(root / ".discopop")
    assert any(line.endswith("/src/main.cpp") for line in mapping), mapping
    assert not any("third_party" in line for line in mapping), mapping


def test_command_line_scope_applies_to_the_copy_of_the_project(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    process = _run_project_manager(root, "-x", "tiny:dp", "--skip-cleanup", "--dp-project-root-dir", "src")
    copies = [path for path in tmp_path.iterdir() if path.name.startswith("tiny_dp_settings.json_proj")]
    assert len(copies) == 1, _output(process)
    mapping = _file_mapping(copies[0] / ".discopop")
    assert mapping and all(str(copies[0] / "src") + "/" in line for line in mapping), mapping


def test_a_scope_matching_nothing_warns(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    (root / "empty").mkdir()
    _set_scope(root, "empty")
    process = _profile(root)
    compile_entry = _only_entry(root, "compile.sh")
    assert compile_entry["code"] == 0, _output(process)
    assert "No instrumented file lies below the instrumentation scope" in compile_entry["stderr"]


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


def _compile_only_scope_warning(stderr: str) -> Optional[str]:
    lines = [line for line in stderr.splitlines() if "DP_RUN_ROOT_DIR" in line]
    return lines[0] if lines else None


def test_a_script_using_the_old_meaning_of_the_scope_variable_warns(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path, compile_sh=COMPILE_SH.replace("../src/main.cpp", '"$DP_PROJECT_ROOT_DIR"main.cpp'))
    _set_scope(root, "src")
    process = _profile(root)
    compile_entry = _only_entry(root, "compile.sh")
    assert compile_entry["code"] == 0, _output(process)
    assert _compile_only_scope_warning(compile_entry["stderr"]) is not None, compile_entry["stderr"]


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


def test_init_writes_the_default_scope(tmp_path: pathlib.Path) -> None:
    root = _project(tmp_path)
    path = root / ".discopop" / "project" / "configs" / "project_environment.json"
    assert json.loads(path.read_text()) == {"DP_PROJECT_ROOT_DIR": "."}
    assert os.access(root / ".discopop" / "project" / "configs" / "compile.sh", os.X_OK)
