# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the editors of the GUI (the Editor tab and the compilation editor) know about the files they edit.

The names and tooltips of the files, the placeholders shown instead of a file that does not exist, the formatting of
JSON settings, the summary of the execution time setting, the output of the last recorded run and the test
compilation. Without a toolkit, shared by the Tk and the Qt GUI.
"""

import copy
import json
import os
from typing import Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import VALIDATION_COMPILE_SCRIPT_NAME
from discopop_library.ProjectManager.configurations.execution_time import EXECUTION_TIME_DISABLED

# the shared files of the compilation editor, in the order of its tabs
COMPILATION_FILES = [
    "compile.sh",
    VALIDATION_COMPILE_SCRIPT_NAME,
    "seq_settings.json",
    "dp_settings.json",
    "hd_settings.json",
    "par_settings.json",
]
BASE_FILES = ["compile.sh", "execute.sh", "seq_settings.json"]
DERIVED_FILES = ["dp_settings.json", "hd_settings.json", "par_settings.json"]
# Shared scripts that are absent by default and created on demand.
OPTIONAL_FILES = [VALIDATION_COMPILE_SCRIPT_NAME]

OPTIONAL_FILE_PLACEHOLDERS = {
    VALIDATION_COMPILE_SCRIPT_NAME: (
        "# This project has no shared compile_validate.sh.\n"
        "# validate.sh runs against the build produced by compile.sh.\n"
        "# Click 'Add' above to build separately for validation: the script is compiled\n"
        "# after the timed execute.sh run and before validate.sh, so it never affects the\n"
        "# measured runtime. It applies to every configuration that does not define its own\n"
        "# compile_validate.sh override, and is ignored for configurations without a\n"
        "# validate.sh.\n"
    )
}

TAB_TOOLTIPS = {
    "compile.sh": "Compilation instructions",
    VALIDATION_COMPILE_SCRIPT_NAME: "Optional: separate compilation instructions for validate.sh runs",
    "execute.sh": "Execution instructions",
    "seq_settings.json": "Settings for sequential execution",
    "dp_settings.json": "Settings for DiscoPoP instrumented execution",
    "hd_settings.json": "Settings for DiscoPoP hotspot detection instrumented execution",
    "par_settings.json": "Settings for the execution of the parallelized source code",
}

DERIVE_TOOLTIP_SUFFIX = "\n\nUse 'Derive Settings' to generate this file from seq_settings.json"

# shown (read-only) in the editor of a per-configuration file that does not exist
COMPILE_OVERRIDE_PLACEHOLDER = (
    "# This configuration has no compile.sh override.\n"
    "# The shared compile.sh is used to compile it instead.\n"
    "# Click 'Add Override' above to create one for this configuration only.\n"
)
VALIDATE_SCRIPT_PLACEHOLDER = (
    "# This configuration has no validate.sh.\n"
    "# execute.sh alone determines correctness (its exit code).\n"
    "# Click 'Add validate.sh' above to separate output validation from\n"
    "# the timed execute.sh run: validate.sh re-runs the code and validates\n"
    "# its output; a run then counts as correct only if BOTH execute.sh and\n"
    "# validate.sh exit 0.\n"
)
VALIDATION_COMPILE_OVERRIDE_PLACEHOLDER = (
    "# This configuration has no compile_validate.sh override.\n"
    "# validate.sh runs against the build produced by the compile script that\n"
    "# execute.sh also uses.\n"
    "# Click 'Add Override' above to build separately for validation: the override\n"
    "# is compiled after the timed execute.sh run and before validate.sh, so it\n"
    "# never affects the measured runtime. It is ignored while no validate.sh exists.\n"
)

COMPILE_SCRIPT_WARNING_TITLE = "Compilation Script Warning"
COMPILE_SCRIPT_WARNING = (
    "The compilation script does not use CC or CXX environment variables.\n\n"
    "The compilation script should make use of CC or CXX for compatibility "
    "with the DiscoPoP framework."
)


def format_json_content(content: str) -> str:
    """``content`` as indented JSON; text that is not valid JSON is returned unchanged."""
    try:
        return json.dumps(json.loads(content), indent=2)
    except (json.JSONDecodeError, ValueError):
        return content


def uses_compiler_variables(script: str) -> bool:
    """Whether a compile script mentions ``CC`` or ``CXX``, as the framework needs to substitute its compilers."""
    return "CC" in script or "CXX" in script


def execution_time_summary(override: Optional[str], enabled: bool) -> str:
    """One line on where the execution time of a run comes from (the Execute tab shows it).

    ``override`` is ``--execution-time-regex`` (``EXECUTION_TIME_DISABLED`` forces the wall clock), ``enabled`` the
    stored setting of the configuration.
    """
    if override is not None:
        return (
            "from the console output (forced by --execution-time-regex)"
            if override != EXECUTION_TIME_DISABLED
            else "wall clock of execute.sh (forced by --execution-time-regex)"
        )
    if enabled:
        return "from the console output (see Editor -> execute.sh)"
    return "wall clock of execute.sh"


def last_recorded_execution_output(project_dir: str, config: Optional[str]) -> Optional[Tuple[str, str]]:
    """stdout and stderr of the most recent recorded execute.sh run of ``config``, if any."""
    if not config:
        return None
    results_path = os.path.join(project_dir, "execution_results.json")
    if not os.path.exists(results_path):
        return None
    try:
        with open(results_path, "r") as f:
            results = json.load(f)
        entries = results.get(config, {}).get("execute.sh", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return None

    # A pattern is written for the program as the measured runs execute it, so
    # prefer their output over that of the instrumented profiling runs.
    preferred = ["seq_settings.json", "par_settings.json"]
    ordered = preferred + [name for name in entries if name not in preferred]
    for settings_name in ordered:
        for entry in reversed(entries.get(settings_name, [])):
            if not entry.get("executed", True):
                continue
            stdout = str(entry.get("stdout", ""))
            stderr = str(entry.get("stderr", ""))
            if stdout or stderr:
                return stdout, stderr
    return None


def run_test_compilation(arguments: ProjectManagerArguments) -> Optional[Tuple[int, float, str, str]]:
    """Compile once with the shared compile.sh and seq_settings.json; (exit code, seconds, stdout, stderr).

    A test compilation is no run of a configuration, so no result is stored. None if the settings are not found.
    """
    from discopop_library.ProjectManager.configurations.execution import execute_configuration

    return execute_configuration(
        copy.copy(arguments),
        arguments.project_root,
        arguments.project_config_dir,
        os.path.join(arguments.project_config_dir, "seq_settings.json"),
        os.path.join(arguments.project_config_dir, "compile.sh"),
        1,
        arguments.timeout_compilation,
        store_result=False,
    )


def describe_compilation_test(return_code: int, elapsed: float, stdout: str, stderr: str) -> str:
    """The text of the dialog showing the result of a test compilation."""
    message = "Compilation test output:\n\n"
    if return_code == 0:
        message += f"Success ({elapsed:.2f}s)\n"
    else:
        message += f"Failed with exit code {return_code} ({elapsed:.2f}s)\n"
    if stdout:
        message += f"\nstdout:\n{stdout}\n"
    if stderr:
        message += f"\nstderr:\n{stderr}\n"
    return message
