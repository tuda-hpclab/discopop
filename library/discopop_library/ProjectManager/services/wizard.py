# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the steps of the configuration wizard compute, read and write, without a toolkit.

The wizard windows only collect the user's input and show these results.
"""

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services.configurations import WizardData
from discopop_library.ProjectManager.services.derived_settings import derive_settings
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkFinished
from discopop_library.ProjectManager.utilities.initializeFiles import initial_script_content, initial_settings_content

COMPILE_PLACEHOLDER = "$CXX your_code.cpp -o a.out"
EXECUTE_PLACEHOLDER = "./a.out <args>"

TEST_OK = "ok"
TEST_FAILED = "failed"


def existing_compile_script(project_config_dir: str) -> Optional[str]:
    """The compile.sh of the project if the user already changed it, else None (the wizard offers a placeholder)."""
    compile_sh_path = os.path.join(project_config_dir, "compile.sh")
    if not os.path.exists(compile_sh_path):
        return None
    with open(compile_sh_path, "r") as f:
        existing = f.read()
    if existing.strip() != initial_script_content.strip():
        return existing
    return None


def initial_seq_settings(project_config_dir: str) -> Dict[str, str]:
    """The compilers and flags the compilation settings step starts with; missing keys get their defaults."""
    seq_settings_path = os.path.join(project_config_dir, "seq_settings.json")
    if os.path.exists(seq_settings_path):
        with open(seq_settings_path, "r") as f:
            settings = json.load(f)
    else:
        settings = initial_settings_content
    return {
        "CC": settings.get("CC", "clang"),
        "CXX": settings.get("CXX", "clang++"),
        "CFLAGS": settings.get("CFLAGS", ""),
        "CXXFLAGS": settings.get("CXXFLAGS", ""),
    }


def compute_derived_settings(data: WizardData) -> Dict[str, Dict[str, str]]:
    """The ``dp_settings`` / ``hd_settings`` / ``par_settings`` for the compilation settings of ``data``.

    Also stored in ``data.derived_settings``.
    """
    seq_settings = {"CC": data.cc, "CXX": data.cxx, "CFLAGS": data.cflags, "CXXFLAGS": data.cxxflags}
    derived = derive_settings(seq_settings)
    data.derived_settings = {
        "dp_settings": derived["dp"],
        "hd_settings": derived["hd"],
        "par_settings": derived["par"],
    }
    return data.derived_settings


def save_derived_settings(project_config_dir: str, dp_content: str, hd_content: str, par_content: str) -> None:
    """Write the (possibly edited) derived settings; raises ``json.JSONDecodeError`` before writing anything."""
    parsed = {
        "dp_settings.json": json.loads(dp_content.strip()),
        "hd_settings.json": json.loads(hd_content.strip()),
        "par_settings.json": json.loads(par_content.strip()),
    }
    for filename, settings in parsed.items():
        with open(os.path.join(project_config_dir, filename), "w") as f:
            json.dump(settings, f, indent=2)


def compilation_work(
    arguments: ProjectManagerArguments,
) -> Callable[[WorkContext], Optional[Tuple[int, float, str, str]]]:
    """The work that compiles the project once with the shared compile.sh and seq_settings.json.

    It records no result: a test compilation is no run of a configuration.
    """
    from discopop_library.ProjectManager.configurations.execution import execute_configuration

    args_copy = copy.copy(arguments)
    compile_sh_path = os.path.join(args_copy.project_config_dir, "compile.sh")
    seq_settings_path = os.path.join(args_copy.project_config_dir, "seq_settings.json")

    def compile_once(_ctx: WorkContext) -> Optional[Tuple[int, float, str, str]]:
        return execute_configuration(
            args_copy,
            args_copy.project_root,
            args_copy.project_config_dir,
            seq_settings_path,
            compile_sh_path,
            1,
            args_copy.timeout_compilation,
            store_result=False,
        )

    return compile_once


@dataclass(frozen=True)
class CompilationOutcome:
    """What the test compilation step shows: a status text, whether it succeeded, and the output lines."""

    status: str
    kind: str
    output: List[str] = field(default_factory=list)


def describe_test_compilation(event: WorkFinished) -> CompilationOutcome:
    """Interpret the end of the work of :func:`compilation_work`."""
    if event.error is not None:
        return CompilationOutcome("✗ Failed", TEST_FAILED, [f"Compilation failed: {event.error}\n"])
    if event.result is None:
        return CompilationOutcome("✗ Failed", TEST_FAILED, ["Compilation failed: settings file not found.\n"])
    ret_code, elapsed, stdout, stderr = event.result
    if ret_code == 0:
        outcome = CompilationOutcome("✓ Success", TEST_OK, [f"Compilation succeeded ({elapsed:.2f}s)\n"])
    else:
        outcome = CompilationOutcome(
            f"✗ Failed (exit code: {ret_code})",
            TEST_FAILED,
            [f"Compilation failed (return code: {ret_code}, {elapsed:.2f}s)\n"],
        )
    if stdout:
        outcome.output.append(f"stdout:\n{stdout}\n")
    if stderr:
        outcome.output.append(f"stderr:\n{stderr}\n")
    return outcome
