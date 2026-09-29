# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Asking the autotuner whether a suggestion's patches compile.

The tuner already builds every candidate in an isolated project copy, so the repair
tool does not reimplement that. It invokes ``discopop_auto_tuner -A 0 --compile-only``
and reads two files back:

* ``auto_tuner/compile_results.json`` -- written fresh by every compile-only run, and
  therefore the authority on what happened in *this* run. It is deleted beforehand so
  a crashed tuner cannot be mistaken for a successful one.
* ``project/execution_results.json`` -- carries the compiler's stdout/stderr per
  requested suggestion. Note that this file lives in the *original* project, not in
  the copy the tuner deletes: ``CodeConfiguration.compile_only`` builds its
  ``ProjectManagerArguments`` with the original project root, so the diagnostics
  survive the cleanup.
"""

from dataclasses import dataclass, field
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.ProjectManager.configurations.compile_script import COMPILE_SCRIPT_NAME

logger = logging.getLogger("PatchRepair").getChild("compilation")

COMPILE_RESULTS_FILE = "compile_results.json"

# The reference configuration applies no suggestions at all; the tuner records it with
# an empty requested-suggestion list.
REFERENCE_KEY: List[int] = []

# Passed as -ht when the run is restricted to explicit ids.
ALL_HOTSPOT_TYPES = "yes,no,maybe"


@dataclass
class CompileOutcome:
    """What the compiler said about one suggestion."""

    suggestion_id: int
    built: bool
    # Empty when the suggestion's patches could not be applied at all: there was no
    # build to produce diagnostics, and the cause is the patch, not the compiler.
    stderr: str = ""
    stdout: str = ""
    applied: bool = True

    def first_error(self) -> str:
        for line in self.stderr.splitlines():
            if "error" in line.lower():
                return line.strip()
        return self.stderr.strip().splitlines()[0].strip() if self.stderr.strip() else ""


@dataclass
class CompileReport:
    """The outcome of one compile-only autotuner run."""

    # False when the unmodified project does not build. Every candidate failure is then
    # inconclusive -- nothing can be blamed on a patch -- so callers must stop.
    reference_built: bool
    outcomes: Dict[int, CompileOutcome] = field(default_factory=dict)

    def failing(self) -> List[int]:
        return sorted(sid for sid, outcome in self.outcomes.items() if not outcome.built)

    def building(self) -> List[int]:
        return sorted(sid for sid, outcome in self.outcomes.items() if outcome.built)


class CompileCheckError(RuntimeError):
    """The compile check could not be performed at all."""


def run_compile_check(
    arguments: PatchRepairArguments,
    suggestion_ids: Optional[Sequence[int]] = None,
    timeout: Optional[float] = None,
) -> CompileReport:
    """Build the given suggestions, each on its own, and report what compiled.

    ``suggestion_ids`` of ``None`` means "every suggestion the tuner would consider";
    a list restricts the run via ``--search-space``. Passing a single id is how a
    repair attempt is verified.
    """
    # The candidates were already selected by hotspot type (or named via --suggestions,
    # which overrides that filter), so a restricted run must not filter them again: the
    # tuner would silently skip an explicitly named "no" suggestion or an unclassified
    # one, and it would never be built or reported.
    hotspot_types = arguments.hotspot_types if suggestion_ids is None else ALL_HOTSPOT_TYPES
    auto_tuner_dir = os.path.join(arguments.dot_dp_path, "auto_tuner")
    compile_results_path = os.path.join(auto_tuner_dir, COMPILE_RESULTS_FILE)
    # A stale file from an earlier run must never be read as this run's answer.
    if os.path.exists(compile_results_path):
        os.remove(compile_results_path)

    command = [
        sys.executable,
        "-m",
        "discopop_library.EmpiricalAutotuning",
        "--dot-dp-path",
        arguments.dot_dp_path,
        "-c",
        arguments.configuration,
        "-A",
        "0",
        "--compile-only",
        "-ht",
        hotspot_types,
        "-t",
        str(arguments.thread_count),
        "--log",
        arguments.log_level,
    ]
    if suggestion_ids is not None:
        command.extend(["--search-space", ",".join(str(sid) for sid in suggestion_ids)])

    logger.debug("Running compile check: " + " ".join(command))
    result = subprocess.run(
        command,
        cwd=arguments.dot_dp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        timeout=timeout,
    )
    if not os.path.exists(compile_results_path):
        raise CompileCheckError(
            "The compile check did not produce "
            + compile_results_path
            + " (autotuner exit code "
            + str(result.returncode)
            + ").\n"
            + result.stdout[-4000:]
        )

    try:
        with open(compile_results_path, "r") as f:
            compile_results = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        # A partially written file (the tuner was killed mid-write) is no answer either.
        raise CompileCheckError("Could not read " + compile_results_path + ": " + str(error))

    diagnostics = read_compile_diagnostics(arguments)
    report = CompileReport(reference_built=bool(compile_results.get("reference_built", True)))

    for key, built in (("built", True), ("failed", False)):
        for entry in compile_results.get(key, []):
            if list(entry) == REFERENCE_KEY:
                continue
            # -A 0 measures one suggestion at a time, so an entry names exactly one id.
            for suggestion_id in entry:
                stdout, stderr = diagnostics.get(int(suggestion_id), ("", ""))
                report.outcomes[int(suggestion_id)] = CompileOutcome(
                    suggestion_id=int(suggestion_id), built=built, stdout=stdout, stderr=stderr
                )

    for entry in compile_results.get("not_applied", []):
        for suggestion_id in entry:
            report.outcomes[int(suggestion_id)] = CompileOutcome(
                suggestion_id=int(suggestion_id), built=False, applied=False
            )

    return report


def read_compile_diagnostics(arguments: PatchRepairArguments) -> Dict[int, "tuple[str, str]"]:
    """``suggestion id -> (stdout, stderr)`` of the most recent build of that suggestion.

    Only entries produced by a compile script are considered: an ``execute.sh`` entry
    for the same suggestion describes the run, not the build, and its stderr would send
    an agent looking for a compiler error that is not there.
    """
    results_path = os.path.join(arguments.dot_dp_path, "project", "execution_results.json")
    diagnostics: Dict[int, "tuple[str, str]"] = {}
    if not os.path.exists(results_path):
        return diagnostics
    try:
        with open(results_path, "r") as f:
            execution_results = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read " + results_path + "; continuing without compiler diagnostics.")
        return diagnostics

    configuration_results = execution_results.get(arguments.configuration, {})
    for script_name, per_settings in configuration_results.items():
        if not _is_compile_script(script_name):
            continue
        for entries in per_settings.values():
            for entry in entries:
                requested = entry.get("requested_suggestions") or []
                if len(requested) != 1:
                    continue
                diagnostics[int(requested[0])] = (entry.get("stdout", ""), entry.get("stderr", ""))
    return diagnostics


def _is_compile_script(script_name: str) -> bool:
    """Whether an execution_results.json key names the build, not a run.

    A per-configuration override keeps the same file name (see
    ``resolve_compile_script_path``), so an exact match is right here. It also excludes
    ``compile_validate.sh``, which builds the validation binary rather than the one
    whose failure is being repaired.
    """
    return os.path.basename(script_name) == COMPILE_SCRIPT_NAME
