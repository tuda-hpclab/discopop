# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The project wide environment of every command the project manager runs.

These variables tell the DiscoPoP tools where a run happens and what is project code:

``DP_PROJECT_ROOT_DIR``
    The absolute path of the project root the run uses: the project root itself, or the copy of it a run
    of a configuration works in. Scripts use it to find the project (``cmake -S "$DP_PROJECT_ROOT_DIR"``).
    The profiler and the hotspot detection instrument the code below it.
``DOT_DISCOPOP``
    ``<run root>/.discopop``, always absolute. The compiler wrappers, the LLVM passes and the runtime
    libraries write there. It has to be the same absolute path for every compile step of a build and
    for the instrumented program: a relative or missing value lets each directory a build compiles in
    get a ``.discopop`` of its own, with numbering that does not fit together, and lets the program
    write its results nowhere.
``DP_PROJECT_INCLUDE_DIRS``
    Directories outside the project root whose code is project code as well (sources shared between
    projects), absolute, separated by ``:``. They are not copied for the runs of a configuration.
``DP_PROJECT_EXCLUDE_DIRS``
    Directories below the project root (or below an included directory) whose code is no project code,
    e.g. the dependencies a CMake build fetches into ``build/_deps``. Passed as absolute paths in the run
    root.

The two lists are the *project directories*: stored in ``.discopop/project/included_directories.json``
(:mod:`..services.included_directories`) and ``.discopop/project/excluded_directories.json``
(:mod:`..services.excluded_directories`), edited in the Project Setup stage of the GUI, and overridden for
one invocation of the command line with ``--project-include-dirs`` / ``--project-exclude-dirs``.
:func:`build_environment` is the single place that stacks the layers of a run's environment.

``DP_PROJECT_ROOT_DIR`` and ``DOT_DISCOPOP`` cannot be set in the settings files (``seq_settings.json`` and the
files derived from it): every run overrides them, :func:`ignored_settings_warning` reports a value found there, and
:func:`migrate_settings_files` removes them. The two lists can be extended there: entries of a settings file are
kept in front of the stored ones.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from discopop_library.ProjectManager.services import excluded_directories, included_directories

ROOT_VARIABLE = "DP_PROJECT_ROOT_DIR"
DOT_DISCOPOP_VARIABLE = "DOT_DISCOPOP"
INCLUDE_VARIABLE = included_directories.ENVIRONMENT_VARIABLE
EXCLUDE_VARIABLE = excluded_directories.ENVIRONMENT_VARIABLE

# Set from the run root for every run, hence not allowed in a settings file.
RESERVED_VARIABLES = (ROOT_VARIABLE, DOT_DISCOPOP_VARIABLE)
# What the log of a run names.
PROJECT_VARIABLES = (ROOT_VARIABLE, DOT_DISCOPOP_VARIABLE, INCLUDE_VARIABLE, EXCLUDE_VARIABLE)

# The settings files below project_config_dir that are passed to the scripts as environment variables.
SETTINGS_FILES = ("seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json")

# The file of an earlier development version that held a single instrumentation scope; no longer read.
OBSOLETE_PROJECT_ENVIRONMENT_FILE = "project_environment.json"


@dataclass(frozen=True)
class ProjectDirectories:
    """What is project code besides the project root: ``included`` directories outside of it (absolute,
    normalized) and ``excluded`` directories below it (relative to the project root, ``/`` separated)."""

    included: Tuple[str, ...] = field(default_factory=tuple)
    excluded: Tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        """One line for messages, e.g. "included: /opt/shared; excluded: build/_deps"."""
        return (
            "included: "
            + (", ".join(self.included) if self.included else "none")
            + "; excluded: "
            + (", ".join(self.excluded) if self.excluded else "none")
        )


def split_entries(value: str) -> List[str]:
    """The entries of a ``:`` separated list, empty ones dropped."""
    return [entry for entry in value.split(":") if entry.strip()]


def load_project_directories(project_dir: str) -> ProjectDirectories:
    """The stored project directories; ``project_dir`` is ``.discopop/project``."""
    return ProjectDirectories(
        included=tuple(included_directories.load_included_directories(project_dir)),
        excluded=tuple(excluded_directories.load_excluded_directories(project_dir)),
    )


def project_directories_of(
    project_dir: str, project_root: str, include_override: Optional[str], exclude_override: Optional[str]
) -> ProjectDirectories:
    """The project directories of a run: the stored ones, each list replaced by a ``:`` separated override (from
    the command line) if one is given. An override is normalized like a stored list."""
    stored = load_project_directories(project_dir)
    included = (
        tuple(included_directories.minimal(split_entries(include_override), project_root))
        if include_override is not None
        else stored.included
    )
    excluded = (
        tuple(excluded_directories.minimal(split_entries(exclude_override)))
        if exclude_override is not None
        else stored.excluded
    )
    return ProjectDirectories(included=included, excluded=excluded)


def resolve_project_variables(directories: ProjectDirectories, run_root: str) -> Dict[str, str]:
    """The variables of a run in ``run_root`` (the project root or a copy of it); the lists only if not empty.

    The excluded directories become absolute paths in ``run_root``, so they hold for a copy of the project as well.
    """
    absolute_run_root = os.path.abspath(run_root)
    variables = {
        ROOT_VARIABLE: absolute_run_root,
        DOT_DISCOPOP_VARIABLE: os.path.join(absolute_run_root, ".discopop"),
    }
    if directories.included:
        variables[INCLUDE_VARIABLE] = included_directories.environment_value(directories.included)
    if directories.excluded:
        variables[EXCLUDE_VARIABLE] = excluded_directories.environment_value(
            directories.excluded, root=absolute_run_root
        )
    return variables


def reserved_variables_in(settings: Mapping[str, str]) -> List[str]:
    """The variables of ``settings`` that only the project manager may set."""
    return [name for name in RESERVED_VARIABLES if name in settings]


def _merged(existing: str, added: str) -> str:
    """The ``:`` separated entries of ``existing``, then those of ``added`` not among them."""
    entries: List[str] = []
    for entry in [*split_entries(existing), *split_entries(added)]:
        if entry not in entries:
            entries.append(entry)
    return ":".join(entries)


def build_environment(
    base: Mapping[str, str],
    settings: Mapping[str, str],
    directories: ProjectDirectories,
    run_root: str,
) -> Dict[str, str]:
    """The environment of a command run in ``run_root``.

    Layers, the later winning: ``base`` (usually the process's environment), ``settings`` (the settings file of
    the mode), then the variables of the project. ``DP_PROJECT_ROOT_DIR`` and ``DOT_DISCOPOP`` inherited from
    ``base`` or set in ``settings`` are overridden (:func:`ignored_settings_warning` tells the user about the
    latter); entries of the two lists found there are kept in front of the stored ones. What is specific to one run
    (``OMP_NUM_THREADS``, ``PATH``) is up to the caller.
    """
    result: Dict[str, str] = dict(base)
    for key, value in settings.items():
        result[key] = value
    for name, value in resolve_project_variables(directories, run_root).items():
        result[name] = _merged(result.get(name, ""), value) if name in (INCLUDE_VARIABLE, EXCLUDE_VARIABLE) else value
    return result


def ignored_settings_warning(settings: Mapping[str, str], settings_name: str) -> Optional[str]:
    """A warning if ``settings`` sets reserved variables, which every run overrides; ``None`` otherwise."""
    reserved = reserved_variables_in(settings)
    if not reserved:
        return None
    return (
        settings_name
        + " sets "
        + ", ".join(reserved)
        + ", which the project manager sets for every run; the values in the settings file are ignored. "
        "Remove them there. What is project code is configured with the included and excluded directories "
        "(GUI: Project Setup; command line: --project-include-dirs / --project-exclude-dirs)."
    )


def describe_project_variables(variables: Mapping[str, str]) -> str:
    """One line naming the values a run uses, for its log."""
    return "Environment: " + " ".join(name + "=" + variables.get(name, "") for name in PROJECT_VARIABLES)


def migrate_settings_files(project_config_dir: str) -> List[str]:
    """Remove the reserved variables from the settings files; returns what was done, one message each.

    Every run overrode them, so they never had an effect.
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
            + ": the project manager sets these variables for every run, the values had no effect. What is "
            "project code is configured with the included and excluded directories."
        )
    obsolete = os.path.join(project_config_dir, OBSOLETE_PROJECT_ENVIRONMENT_FILE)
    if os.path.exists(obsolete):
        messages.append(
            obsolete
            + " is no longer read: the instrumentation scope it holds was replaced by the included and excluded "
            "directories (GUI: Project Setup). Configure those and delete the file."
        )
    return messages


# Written into DOT_DISCOPOP by every instrumented build: the project directories its data was instrumented with,
# per mode.
INSTRUMENTED_DIRECTORIES_FILE = "instrumented_project_directories.json"


def record_instrumented_directories(dot_discopop: str, mode: str, directories: ProjectDirectories) -> None:
    """Note that the data of ``mode`` ("dp" or "hd") in ``dot_discopop`` was instrumented with ``directories``.
    Best effort: a failure only costs the stale data warning."""
    path = os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE)
    try:
        with open(path, "r") as f:
            recorded = json.load(f)
        if not isinstance(recorded, dict):
            recorded = {}
    except (OSError, ValueError):
        recorded = {}
    recorded[mode] = {"included": list(directories.included), "excluded": list(directories.excluded)}
    try:
        with open(path, "w") as f:
            json.dump(recorded, f, indent=2)
    except OSError:
        pass


def _string_list(value: object) -> Optional[Tuple[str, ...]]:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        return None
    return tuple(value)


def instrumented_directories(dot_discopop: str, mode: str) -> Optional[ProjectDirectories]:
    """The project directories the data of ``mode`` in ``dot_discopop`` was instrumented with; ``None`` if unknown."""
    try:
        with open(os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE), "r") as f:
            recorded = json.load(f)
    except (OSError, ValueError):
        return None
    entry = recorded.get(mode) if isinstance(recorded, dict) else None
    if not isinstance(entry, dict):
        return None
    included = _string_list(entry.get("included"))
    excluded = _string_list(entry.get("excluded"))
    if included is None or excluded is None:
        return None
    return ProjectDirectories(included=included, excluded=excluded)


def stale_directories_message(dot_discopop: str, mode: str, project_dir: str) -> Optional[str]:
    """A message if the data of ``mode`` was instrumented with other project directories than the stored ones."""
    recorded = instrumented_directories(dot_discopop, mode)
    if recorded is None:
        return None
    configured = load_project_directories(project_dir)
    if sorted(recorded.included) == sorted(configured.included) and sorted(recorded.excluded) == sorted(
        configured.excluded
    ):
        return None
    return (
        "The "
        + ("profiling" if mode == "dp" else "hotspot detection")
        + " data was instrumented with other project directories ("
        + recorded.describe()
        + ") than the project's current ones ("
        + configured.describe()
        + "). Run the "
        + mode
        + " mode again to update it."
    )


def update_project_directories(
    project_dir: str,
    project_root: str,
    included: Optional[Sequence[str]],
    excluded: Optional[Sequence[str]],
) -> Tuple[ProjectDirectories, List[str]]:
    """Store the lists that are given (None leaves a list alone); returns the stored directories and warnings.

    A list is written only if it changes: the modification time of the files marks analysis results as stale (MCP
    server). Entries that cannot be used are dropped with a warning: an included directory that is relative, inside
    the project or missing, an excluded directory that is absolute or outside the project. A missing excluded
    directory is kept (the build may create it) with a warning.
    """
    warnings: List[str] = []
    stored = load_project_directories(project_dir)
    if included is not None:
        usable: List[str] = []
        for entry in included:
            reasons = included_directories.problems(project_root, entry)
            if reasons:
                warnings.extend("Included directory " + entry + " ignored: " + reason for reason in reasons)
            else:
                usable.append(entry)
        if tuple(included_directories.minimal(usable, project_root)) != stored.included:
            included_directories.save_included_directories(project_dir, project_root, usable)
    if excluded is not None:
        usable = []
        for entry in excluded:
            normalized = excluded_directories.normalize(entry)
            if normalized is None:
                warnings.append(
                    "Excluded directory " + entry + " ignored: give a directory below the project root, relative to it."
                )
                continue
            if not os.path.isdir(os.path.join(project_root, normalized)):
                warnings.append(
                    "Excluded directory " + normalized + " does not exist (yet); it applies once the build creates it."
                )
            usable.append(normalized)
        if tuple(excluded_directories.minimal(usable)) != stored.excluded:
            excluded_directories.save_excluded_directories(project_dir, usable)
    return load_project_directories(project_dir), warnings
