# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Command lines of the tools the ProjectManager runs as subprocesses (pure functions, easy to test)."""

import os
import sys
from typing import Dict, List, Mapping, Optional

from discopop_library.ProjectManager.services.requests import AutotunerRequest, ExplorerRequest, PatchRepairRequest


def explorer_command(request: ExplorerRequest, python: Optional[str] = None) -> List[str]:
    command = [
        python or sys.executable,
        "-m",
        "discopop_explorer",
        #            "--path",
        #            project_path,
        "--enable-patterns",
        request.enable_patterns,
    ]
    command += ["--log", "WARNING"]
    if request.jobs != "auto":
        command += ["-j", request.jobs]
    if request.ignore_dependency_states:
        command.append("--ignore-dependency-states")
    return command


def autotuner_command(request: AutotunerRequest, dot_dp_path: str, python: Optional[str] = None) -> List[str]:
    command = [
        python or sys.executable,
        "-m",
        "discopop_library.EmpiricalAutotuning",
        "--dot-dp-path",
        dot_dp_path,
        "-c",
        request.configuration,
        "-ht",
        request.hotspot_types,
        "-A",
        request.algorithm,
        "--log",
        request.log_level,
    ]
    if request.threads != "auto":
        command += ["-t", request.threads]
    # Emitted only when it changes something, so a default tuning run is the command it was before the
    # repetition option existed.
    if request.repetitions > 1:
        command += ["-xr", str(request.repetitions)]
    if request.mode == "evaluate":
        if request.evaluate_ids:
            command += ["-s", ",".join(request.evaluate_ids)]
    elif request.search_space_ids is not None:
        command += ["--search-space", ",".join(request.search_space_ids)]
    return command


def patch_repair_command(request: PatchRepairRequest, dot_dp_path: str, python: Optional[str] = None) -> List[str]:
    command = [
        python or sys.executable,
        "-m",
        "discopop_library.PatchRepair",
        "--dot-dp-path",
        dot_dp_path,
        "-c",
        request.configuration,
        "-ht",
        request.hotspot_types,
        "--prompts",
        str(request.prompts),
        "--retries",
        str(request.retries),
        "--agent-timeout",
        str(request.agent_timeout),
        "--log",
        request.log_level,
    ]
    if request.backend:
        command += ["--backend", request.backend]
    if request.model:
        command += ["--model", request.model]
    if request.dry_run:
        command.append("--dry-run")
    if request.suggestion_ids is not None:
        command += ["-s", ",".join(request.suggestion_ids)]
    return command


def hotspot_analyzer_command(analyzer_executable: str, input_dir: str) -> List[str]:
    return [analyzer_executable, "--input-dir", input_dir]


def environment_with_interpreter_on_path(environment: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """A copy of ``environment`` (default: the process's) whose PATH starts with the running interpreter's bin
    directory, so that the DiscoPoP tools installed next to it are found."""
    result: Dict[str, str] = dict(os.environ if environment is None else environment)
    interpreter_bin = os.path.dirname(sys.executable)
    if interpreter_bin not in result.get("PATH", ""):
        result["PATH"] = interpreter_bin + os.pathsep + result.get("PATH", "")
    return result
