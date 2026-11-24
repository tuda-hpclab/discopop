# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Autotuner candidates compiled one after the other in the kept build tree of their mode."""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List

import pytest

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration


@pytest.fixture
def project(tmp_path: Path) -> Dict[str, Path]:
    """A project whose build copies main.c to prog.out (counting full and incremental builds) and whose execute.sh
    prints prog.out; suggestion 1 patches main.c, 2 patches other.c."""
    root = tmp_path / "proj"
    dot = root / ".discopop"
    configs = dot / "project" / "configs"
    (configs / "cfg").mkdir(parents=True)
    for name in ("profiler", "explorer"):
        (dot / name).mkdir()
    (root / "main.c").write_text("main 0\n")
    (root / "other.c").write_text("other 0\n")
    log = tmp_path / "builds.txt"
    (configs / "compile.sh").write_text(f'#!/bin/bash\necho full >> "{log}"\ncat main.c other.c > prog.out\n')
    (configs / "compile_incremental.sh").write_text(
        f'#!/bin/bash\necho incremental >> "{log}"\ncat main.c other.c > prog.out\n'
    )
    (configs / "cfg" / "execute.sh").write_text("#!/bin/bash\ncat prog.out\n")
    for mode in ("seq", "par", "hd", "dp"):
        (configs / (mode + "_settings.json")).write_text(json.dumps({"CC": "cc", "CXX": "c++"}))
    (dot / "FileMapping.txt").write_text("1\t" + str(root / "main.c") + "\n2\t" + str(root / "other.c") + "\n")
    (dot / "line_mapping.json").write_text(json.dumps({"1": {"1": 1}, "2": {"1": 1}}))
    for suggestion, (name, file_id, text) in {"1": ("main.c", 1, "main 1\n"), "2": ("other.c", 2, "other 2\n")}.items():
        modified = tmp_path / (name + ".patched")
        modified.write_text(text)
        diff = subprocess.run(["diff", "-Naru", str(root / name), str(modified)], stdout=subprocess.PIPE).stdout
        (dot / "patch_generator" / suggestion).mkdir(parents=True)
        (dot / "patch_generator" / suggestion / (str(file_id) + ".patch")).write_bytes(diff)
    return {"root": root, "dot": dot, "log": log, "tmp": tmp_path}


def _arguments(project: Dict[str, Path], **overrides: object) -> AutotunerArguments:
    values: Dict[str, object] = dict(
        log_level="WARNING",
        write_log=False,
        dot_dp_path=str(project["dot"]),
        skip_cleanup=False,
        sanitize=False,
        configuration="cfg",
        suggestions=None,
        allow_plots=False,
        thread_count=1,
    )
    values.update(overrides)
    return AutotunerArguments(**values)  # type: ignore[arg-type]


def _candidate(project: Dict[str, Path], arguments: AutotunerArguments, suggestions: List[int]) -> CodeConfiguration:
    reference = CodeConfiguration(str(project["root"]), str(project["dot"]), "par_settings.json")
    candidate = reference.create_copy(arguments, "par_settings.json", lambda: 1)
    application = candidate.apply_suggestions(arguments, suggestions)
    assert application is None or not application.failure
    candidate.execute(arguments, timeout=None, thread_count=1)
    candidate.deleteFolder()
    return candidate


def test_candidates_share_the_kept_tree_and_are_compiled_incrementally(project: Dict[str, Path]) -> None:
    arguments = _arguments(project)
    first = _candidate(project, arguments, [1])
    second = _candidate(project, arguments, [2])
    third = _candidate(project, arguments, [1, 2])

    tree = project["tmp"] / "proj_discopop_builds" / "cfg_par"
    assert first.root_path == second.root_path == third.root_path == str(tree)
    assert tree.is_dir()  # deleteFolder keeps the tree for the next candidate
    assert project["log"].read_text().splitlines() == ["full", "incremental", "incremental"]
    assert (tree / "prog.out").read_text() == "main 1\nother 2\n"
    for candidate in (first, second, third):
        assert candidate.execution_result is not None and candidate.execution_result.result_valid
    assert "[1, 2]" in third.label
    # the project itself is never patched, and no copy per candidate was made
    assert (project["root"] / "main.c").read_text() == "main 0\n"
    assert sorted(os.listdir(project["tmp"] / "proj_discopop_builds")) == ["cfg_par"]


def test_without_kept_trees_every_candidate_gets_a_copy(project: Dict[str, Path]) -> None:
    arguments = _arguments(project, kept_build_trees=False)
    candidate = _candidate(project, arguments, [1])
    assert candidate.kept_key is None and not os.path.exists(candidate.root_path)  # deleted after its run
    assert project["log"].read_text().splitlines() == ["full"]
    assert candidate.execution_result is not None and candidate.execution_result.result_valid


def test_hd_candidates_and_skip_cleanup_keep_copies_of_their_own(project: Dict[str, Path]) -> None:
    from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import uses_kept_build_trees

    arguments = _arguments(project)
    assert uses_kept_build_trees(arguments, "par_settings.json")
    assert uses_kept_build_trees(arguments, "seq_settings.json")
    assert not uses_kept_build_trees(arguments, "hd_settings.json")
    assert not uses_kept_build_trees(_arguments(project, skip_cleanup=True), "par_settings.json")


def test_a_failed_build_in_the_kept_tree_is_a_compilation_failure(project: Dict[str, Path]) -> None:
    """As for a copy of its own (compile_only): a reference configuration that does not build stops the search with
    "does not build" (Autotuner.reference_failure_reason), not with a misleading return code."""
    from discopop_library.EmpiricalAutotuning.Autotuner import reference_failure_reason

    configs = project["dot"] / "project" / "configs"
    for script in ("compile.sh", "compile_incremental.sh"):
        (configs / script).write_text("#!/bin/bash\nexit 1\n")
    reference = CodeConfiguration(str(project["root"]), str(project["dot"]), "seq_settings.json")
    candidate = reference.create_copy(_arguments(project), "seq_settings.json", lambda: 1)
    candidate.execute(_arguments(project), timeout=None, thread_count=1, is_initial=True)
    candidate.deleteFolder()

    assert candidate.kept_key is not None
    result = candidate.execution_result
    assert result is not None and result.compilation_failed and not result.result_valid
    assert reference_failure_reason(result) == "it does not build (see the compiler output above)"
