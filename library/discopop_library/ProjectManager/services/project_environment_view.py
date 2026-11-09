# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the "Project environment" widgets show, without a toolkit: the instrumentation scope as it would be stored
and resolved, the warnings about it, and the scripts that still use ``DP_PROJECT_ROOT_DIR`` as the project root."""

import os
import re
from dataclasses import dataclass, field
from typing import Iterable, List

from discopop_library.ProjectManager.configurations.project_environment import (
    DEFAULT_SCOPE,
    DOT_DISCOPOP_VARIABLE,
    RUN_ROOT_VARIABLE,
    SCOPE_VARIABLE,
    ProjectEnvironment,
    load_project_environment,
    normalize_scope,
    resolve_project_variables,
    save_project_environment,
    scripts_using_scope_variable,
    validate_project_environment,
)

HINT = (
    "Only functions defined below this directory are instrumented by the profiler and the hotspot detection. "
    "Narrow it to leave third-party code out; this can shorten profiling runs considerably."
)

SHARED_SCRIPTS = ("compile.sh", "compile_validate.sh")
CONFIGURATION_SCRIPTS = ("execute.sh", "validate.sh", "compile.sh", "compile_validate.sh")

_SCOPE_VARIABLE_PATTERN = re.compile(r"(?<![A-Za-z0-9_])" + SCOPE_VARIABLE + r"(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class ProjectEnvironmentView:
    """What is shown for a candidate scope."""

    scope: str  # normalized
    project_root_dir: str  # the resolved DP_PROJECT_ROOT_DIR of a run in the project root
    dot_discopop: str
    warnings: List[str] = field(default_factory=list)
    scripts_using_scope_variable: List[str] = field(default_factory=list)


def stored_scope(project_config_dir: str) -> str:
    """The scope stored for the project (the default one if none is)."""
    return load_project_environment(project_config_dir).instrumentation_scope


def project_scripts(project_config_dir: str) -> List[str]:
    """The existing scripts below ``project_config_dir`` that may use the scope variable."""
    paths = [os.path.join(project_config_dir, name) for name in SHARED_SCRIPTS]
    try:
        entries = sorted(os.listdir(project_config_dir))
    except OSError:
        entries = []
    for entry in entries:
        directory = os.path.join(project_config_dir, entry)
        if os.path.isdir(directory):
            paths.extend(os.path.join(directory, name) for name in CONFIGURATION_SCRIPTS)
    return [path for path in paths if os.path.isfile(path)]


def build_view(project_root: str, project_config_dir: str, scope: str) -> ProjectEnvironmentView:
    """The view of the candidate ``scope``; the scripts are only listed if the scope is narrowed."""
    root = os.path.abspath(project_root)
    normalized = normalize_scope(root, scope)
    environment = ProjectEnvironment(instrumentation_scope=normalized)
    variables = resolve_project_variables(environment, root, root)
    scripts: List[str] = []
    if normalized != DEFAULT_SCOPE:
        scripts = scripts_using_scope_variable(project_scripts(project_config_dir))
    return ProjectEnvironmentView(
        scope=normalized,
        project_root_dir=variables[SCOPE_VARIABLE],
        dot_discopop=variables[DOT_DISCOPOP_VARIABLE],
        warnings=validate_project_environment(root, environment),
        scripts_using_scope_variable=scripts,
    )


def save_scope(project_config_dir: str, project_root: str, scope: str) -> str:
    """Store ``scope``; returns the normalized form that was stored."""
    save_project_environment(project_config_dir, project_root, ProjectEnvironment(instrumentation_scope=scope))
    return stored_scope(project_config_dir)


def use_run_root_variable(script_paths: Iterable[str]) -> List[str]:
    """Replace ``DP_PROJECT_ROOT_DIR`` by ``DP_RUN_ROOT_DIR`` (whole words only) in the scripts; returns those changed.

    Raises ``OSError`` if a script cannot be read or written.
    """
    changed: List[str] = []
    for path in script_paths:
        with open(path, "r") as f:
            content = f.read()
        replaced = _SCOPE_VARIABLE_PATTERN.sub(RUN_ROOT_VARIABLE, content)
        if replaced != content:
            with open(path, "w") as f:
                f.write(replaced)
            changed.append(path)
    return changed
