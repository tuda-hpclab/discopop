# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The project wide environment of every command the project manager runs.

Three variables tell the DiscoPoP tools where a run happens and what it instruments:

``DP_RUN_ROOT_DIR``
    The absolute path of the project root the run uses: the project root itself, or the copy of it a run
    of a configuration works in. Scripts use it to find the project (``cmake -S "$DP_RUN_ROOT_DIR"``).
``DOT_DISCOPOP``
    ``<run root>/.discopop``, always absolute. The compiler wrappers, the LLVM passes and the runtime
    libraries write there. It has to be the same absolute path for every compile step of a build and
    for the instrumented program: a relative or missing value lets each directory a build compiles in
    get a ``.discopop`` of its own, with numbering that does not fit together, and lets the program
    write its results nowhere.
``DP_PROJECT_ROOT_DIR``
    The instrumentation scope: only functions defined in a file whose path contains this directory are
    instrumented, by the profiler and by the hotspot detection. Defaults to the run root. Narrowing it
    (e.g. to ``src/``) leaves third-party code out, which can shorten profiling runs by an order of
    magnitude.

The scope is the only one of them that can be configured. It is stored in
``<project_config_dir>/project_environment.json`` relative to the project root, so that it moves along
into the copies of the project, and resolved per run by :func:`resolve_project_variables`.
:func:`build_environment` is the single place that stacks the layers of a run's environment.

The variables cannot be set in the settings files (``seq_settings.json`` and the files derived from it):
every run overrides them, :func:`ignored_settings_warning` reports a value found there, and
:func:`migrate_settings_files` removes them.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional

PROJECT_ENVIRONMENT_FILE = "project_environment.json"

RUN_ROOT_VARIABLE = "DP_RUN_ROOT_DIR"
DOT_DISCOPOP_VARIABLE = "DOT_DISCOPOP"
SCOPE_VARIABLE = "DP_PROJECT_ROOT_DIR"

# Set from the project environment for every run, hence not allowed in a settings file.
RESERVED_VARIABLES = (SCOPE_VARIABLE, DOT_DISCOPOP_VARIABLE, RUN_ROOT_VARIABLE)

# The scope "the whole project", stored relative to the project root.
DEFAULT_SCOPE = "."

# The settings files below project_config_dir that are passed to the scripts as environment variables.
SETTINGS_FILES = ("seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json")


class ProjectEnvironmentError(ValueError):
    """The project environment or a settings file cannot be used as it is."""


@dataclass(frozen=True)
class ProjectEnvironment:
    """What ``project_environment.json`` holds.

    ``instrumentation_scope`` is a directory relative to the project root (``"."`` for all of it), or an
    absolute path outside of it, which is not moved into copies of the project.
    """

    instrumentation_scope: str = DEFAULT_SCOPE


def project_environment_path(project_config_dir: str) -> str:
    return os.path.join(project_config_dir, PROJECT_ENVIRONMENT_FILE)


def load_project_environment(project_config_dir: str) -> ProjectEnvironment:
    """The stored project environment, or the default one if none is stored.

    Raises :class:`ProjectEnvironmentError` if the file exists but cannot be used: a run with an
    environment other than the one configured would profile the wrong code without telling anyone.
    """
    path = project_environment_path(project_config_dir)
    if not os.path.exists(path):
        return ProjectEnvironment()
    try:
        with open(path, "r") as f:
            content = json.load(f)
    except (OSError, ValueError) as error:  # ValueError: invalid JSON or invalid UTF-8
        raise ProjectEnvironmentError("cannot read " + path + ": " + str(error)) from error
    if not isinstance(content, dict):
        raise ProjectEnvironmentError(path + " has to contain a JSON object")
    unknown = sorted(set(content) - {SCOPE_VARIABLE})
    if unknown:
        raise ProjectEnvironmentError(
            path + ": unknown key(s) " + ", ".join(unknown) + "; only " + SCOPE_VARIABLE + " can be set"
        )
    scope = content.get(SCOPE_VARIABLE, DEFAULT_SCOPE)
    if not isinstance(scope, str):
        raise ProjectEnvironmentError(path + ": " + SCOPE_VARIABLE + " has to be a string")
    return ProjectEnvironment(instrumentation_scope=scope.strip() or DEFAULT_SCOPE)


def save_project_environment(project_config_dir: str, project_root: str, environment: ProjectEnvironment) -> None:
    """Store ``environment``, its scope normalized by :func:`normalize_scope`."""
    scope = normalize_scope(project_root, environment.instrumentation_scope)
    with open(project_environment_path(project_config_dir), "w") as f:
        json.dump({SCOPE_VARIABLE: scope}, f, indent=2)
        f.write("\n")


def write_default_project_environment(project_config_dir: str) -> None:
    """Store the default project environment, unless one is stored already."""
    path = project_environment_path(project_config_dir)
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({SCOPE_VARIABLE: DEFAULT_SCOPE}, f, indent=2)
            f.write("\n")


def _is_below(path: str, directory: str) -> bool:
    """Whether ``path`` is ``directory`` or lies below it; both absolute and normalized."""
    return os.path.commonpath([path, directory]) == directory


def normalize_scope(project_root: str, scope: str) -> str:
    """The form a scope is stored in: relative to ``project_root`` if it lies inside, else absolute.

    A relative ``scope`` is taken relative to ``project_root``. Neither the trailing slash nor ``..``
    survive, so equal scopes are stored equally.
    """
    scope = scope.strip() or DEFAULT_SCOPE
    root = os.path.abspath(project_root)
    absolute = os.path.normpath(os.path.join(root, os.path.expanduser(scope)))
    if _is_below(absolute, root):
        return os.path.relpath(absolute, root)
    return absolute


def validate_project_environment(project_root: str, environment: ProjectEnvironment) -> List[str]:
    """Warnings about ``environment``; an empty list if there is nothing to object to.

    Neither case stops a run: a scope outside the project root may be intended (sources shared between
    projects), and a scope below it may only be created by the build (generated sources).
    """
    warnings: List[str] = []
    root = os.path.abspath(project_root)
    scope = normalize_scope(root, environment.instrumentation_scope)
    absolute = os.path.normpath(os.path.join(root, scope))
    if not _is_below(absolute, root):
        warnings.append(
            "The instrumentation scope "
            + absolute
            + " lies outside the project root "
            + root
            + ": the copies of the project a configuration runs in are not instrumented, only the sources "
            "in that directory."
        )
    if not os.path.isdir(absolute):
        warnings.append("The instrumentation scope " + absolute + " is not an existing directory.")
    return warnings


def resolve_scope(environment: ProjectEnvironment, project_root: str, run_root: str) -> str:
    """The value of ``DP_PROJECT_ROOT_DIR`` for a run in ``run_root``: absolute, with a trailing slash.

    A scope inside the project root is moved into ``run_root``, the copy the run works in. The passes
    test whether a file's path *contains* the value, so the trailing slash keeps ``.../src/`` from
    matching ``.../src_old/``.
    """
    root = os.path.abspath(project_root)
    scope = normalize_scope(root, environment.instrumentation_scope)
    if os.path.isabs(scope):
        resolved = scope
    else:
        resolved = os.path.normpath(os.path.join(os.path.abspath(run_root), scope))
    return resolved if resolved.endswith(os.sep) else resolved + os.sep


def resolve_project_variables(environment: ProjectEnvironment, project_root: str, run_root: str) -> Dict[str, str]:
    """The three variables of a run in ``run_root`` (the project root or a copy of it)."""
    absolute_run_root = os.path.abspath(run_root)
    return {
        RUN_ROOT_VARIABLE: absolute_run_root,
        DOT_DISCOPOP_VARIABLE: os.path.join(absolute_run_root, ".discopop"),
        SCOPE_VARIABLE: resolve_scope(environment, project_root, absolute_run_root),
    }


def reserved_variables_in(settings: Mapping[str, str]) -> List[str]:
    """The variables of ``settings`` that only the project environment may set."""
    return [name for name in RESERVED_VARIABLES if name in settings]


def build_environment(
    base: Mapping[str, str],
    settings: Mapping[str, str],
    environment: ProjectEnvironment,
    project_root: str,
    run_root: str,
    settings_name: str = "settings file",
) -> Dict[str, str]:
    """The environment of a command run in ``run_root``.

    Layers, the later winning: ``base`` (usually the process's environment), ``settings`` (the settings
    file of the mode), then the variables of the project environment. Values of these variables
    inherited from ``base`` are overridden, so that a run depends on the project files only. What is
    specific to one run (``OMP_NUM_THREADS``, ``PATH``) is up to the caller.

    A project variable in ``settings`` is overridden like one inherited from ``base``;
    :func:`ignored_settings_warning` tells the user about it.
    """
    result: Dict[str, str] = dict(base)
    for key, value in settings.items():
        result[key] = value
    result.update(resolve_project_variables(environment, project_root, run_root))
    return result


def ignored_settings_warning(settings: Mapping[str, str], settings_name: str) -> Optional[str]:
    """A warning if ``settings`` sets project variables, which every run overrides; ``None`` otherwise."""
    reserved = reserved_variables_in(settings)
    if not reserved:
        return None
    return (
        settings_name
        + " sets "
        + ", ".join(reserved)
        + ", which the project manager sets for every run; the values in the settings file are ignored. "
        "Remove them there. The instrumentation scope ("
        + SCOPE_VARIABLE
        + ") is configured in "
        + PROJECT_ENVIRONMENT_FILE
        + " (GUI: Editor -> Project environment, command line: --dp-project-root-dir)."
    )


# The variable as a whole word: $DP_PROJECT_ROOT_DIR and ${DP_PROJECT_ROOT_DIR}, not DP_PROJECT_ROOT_DIR_X.
_SCOPE_VARIABLE_PATTERN = re.compile(r"\b" + SCOPE_VARIABLE + r"\b")


def scripts_using_scope_variable(script_paths: Iterable[str]) -> List[str]:
    """The scripts among ``script_paths`` that mention ``DP_PROJECT_ROOT_DIR``; unreadable ones are skipped.

    Before the scope could be configured, the variable held the project root, and scripts used it as
    such (``cmake -S "$DP_PROJECT_ROOT_DIR"``). With a narrowed scope they have to use
    ``DP_RUN_ROOT_DIR`` instead.
    """
    found: List[str] = []
    for path in script_paths:
        try:
            with open(path, "r", errors="replace") as f:
                if _SCOPE_VARIABLE_PATTERN.search(f.read()):
                    found.append(path)
        except OSError:
            continue
    return found


def scope_variable_warning(script_path: str, variables: Mapping[str, str]) -> Optional[str]:
    """A warning if the scope of ``variables`` is narrowed and the script still uses its variable."""
    run_root = variables.get(RUN_ROOT_VARIABLE, "")
    if variables.get(SCOPE_VARIABLE, "").rstrip(os.sep) == run_root.rstrip(os.sep):
        return None
    if not scripts_using_scope_variable([script_path]):
        return None
    return (
        os.path.basename(script_path)
        + " uses "
        + SCOPE_VARIABLE
        + ", which holds the instrumentation scope "
        + variables.get(SCOPE_VARIABLE, "")
        + " rather than the project root. Use "
        + RUN_ROOT_VARIABLE
        + " for the root of the project ("
        + run_root
        + ")."
    )


def describe_project_variables(variables: Mapping[str, str]) -> str:
    """One line naming the values a run uses, for its log."""
    return "Environment: " + " ".join(name + "=" + variables.get(name, "") for name in RESERVED_VARIABLES)


def migrate_settings_files(project_config_dir: str) -> List[str]:
    """Remove the project variables from the settings files; returns what was done, one message each.

    Every run overrode them, so they never had an effect. A ``DP_PROJECT_ROOT_DIR`` found there is not
    turned into the instrumentation scope: it may be stale (e.g. the path of an old checkout), and a scope
    that never applied should not start to apply unasked. The message names it, so that it can be set
    deliberately.
    """
    messages: List[str] = []
    for name in SETTINGS_FILES:
        path = os.path.join(project_config_dir, name)
        try:
            with open(path, "r") as f:
                settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(settings, dict):
            continue
        reserved = reserved_variables_in(settings)
        if not reserved:
            continue
        removed = ", ".join(key + "=" + str(settings.pop(key)) for key in reserved)
        temporary = path + ".tmp"
        with open(temporary, "w") as f:
            json.dump(settings, f, indent=2)
        os.replace(temporary, path)
        messages.append(
            "Removed "
            + removed
            + " from "
            + path
            + ": the project manager sets these variables for every run, the values had no effect. The "
            "instrumentation scope ("
            + SCOPE_VARIABLE
            + ") is configured in "
            + project_environment_path(project_config_dir)
            + "."
        )
    return messages
