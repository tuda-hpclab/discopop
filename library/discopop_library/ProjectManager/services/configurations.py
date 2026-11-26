# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Creating, copying, renaming and deleting configurations, and writing what the configuration wizard collected.

Problems are reported as :class:`ConfigurationError` (the GUI decides how to show them); anything else that goes
wrong (file system errors) propagates as the exception it is.
"""

import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from discopop_library.ProjectManager.configurations.build_sharing import detach_members, repoint_members
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import (
    INCREMENTAL_COMPILE_SCRIPT_NAME,
    get_per_config_validation_compile_script_path,
)
from discopop_library.ProjectManager.utilities.initializeFiles import (
    initial_script_content,
    initialize_configuration_files,
)
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file


class ConfigurationError(Exception):
    """A request that cannot be carried out; ``title`` and ``message`` are meant for the user."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__(message)
        self.title = title
        self.message = message


class EmptyNameError(ConfigurationError):
    def __init__(self) -> None:
        super().__init__("Invalid name", "Configuration name cannot be empty")


class SameNameError(ConfigurationError):
    def __init__(self) -> None:
        super().__init__("Invalid name", "New name must be different from the original")


class AlreadyExistsError(ConfigurationError):
    def __init__(self, name: str) -> None:
        super().__init__("Already exists", f"Configuration '{name}' already exists")


def _checked_new_name(config_dir: str, name: str, current: str = "") -> str:
    """The stripped new name, after checking that it is usable next to the existing configurations."""
    name = name.strip()
    if not name:
        raise EmptyNameError()
    if current and name == current:
        raise SameNameError()
    if os.path.exists(os.path.join(config_dir, name)):
        raise AlreadyExistsError(name)
    return name


def list_configurations(config_dir: str) -> List[str]:
    """The names of the configurations (the directories of ``config_dir``), sorted."""
    if not os.path.exists(config_dir):
        return []
    return sorted(d for d in os.listdir(config_dir) if os.path.isdir(os.path.join(config_dir, d)))


def create_configuration(arguments: ProjectManagerArguments, name: str) -> str:
    """Create an empty configuration and its default files; returns its (stripped) name."""
    name = _checked_new_name(arguments.project_config_dir, name)
    os.makedirs(os.path.join(arguments.project_config_dir, name), exist_ok=True)
    initialize_configuration_files(arguments)
    return name


def copy_configuration_directory(config_dir: str, source: str, new_name: str) -> str:
    new_name = _checked_new_name(config_dir, new_name, current=source)
    shutil.copytree(os.path.join(config_dir, source), os.path.join(config_dir, new_name))
    return new_name


def rename_configuration(config_dir: str, current: str, new_name: str) -> str:
    new_name = _checked_new_name(config_dir, new_name, current=current)
    os.rename(os.path.join(config_dir, current), os.path.join(config_dir, new_name))
    # the configurations that build from it follow (its builds carry the old name and are compiled again)
    repoint_members(config_dir, current, new_name)
    return new_name


def delete_configuration_directory(config_dir: str, name: str) -> List[str]:
    """Delete the configuration; the configurations that built from it build for themselves from now on (returned)."""
    detached = detach_members(config_dir, name)
    shutil.rmtree(os.path.join(config_dir, name))
    return detached


@dataclass
class WizardData:
    """What the configuration wizard collects, step by step."""

    compile_sh: str = ""
    cc: str = ""
    cxx: str = ""
    cflags: str = ""
    cxxflags: str = ""
    config_name: str = "default"
    execute_sh: str = ""
    validate_sh: str = ""
    validate_compile_sh: str = ""
    derived_settings: Dict[str, Dict[str, str]] = field(default_factory=dict)


def _write_executable(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | 0o111)


def write_shared_compile_script(project_config_dir: str, data: WizardData) -> None:
    os.makedirs(project_config_dir, exist_ok=True)
    _write_executable(os.path.join(project_config_dir, "compile.sh"), data.compile_sh)


def shared_incremental_script_path(project_config_dir: str) -> str:
    return os.path.join(project_config_dir, INCREMENTAL_COMPILE_SCRIPT_NAME)


def existing_shared_incremental_script(project_config_dir: str) -> Optional[str]:
    """The content of the shared compile_incremental.sh, None if there is none."""
    path = shared_incremental_script_path(project_config_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return f.read()


def write_shared_incremental_script(project_config_dir: str, text: str) -> None:
    """Write the shared compile_incremental.sh (executable); blank content is a :class:`ConfigurationError`."""
    if not text.strip():
        raise ConfigurationError(
            "Empty Incremental Build Script",
            "The incremental build script is empty. Write the rebuild command, or uncheck the box to skip it.",
        )
    os.makedirs(project_config_dir, exist_ok=True)
    _write_executable(shared_incremental_script_path(project_config_dir), text if text.endswith("\n") else text + "\n")


def remove_shared_incremental_script(project_config_dir: str) -> None:
    path = shared_incremental_script_path(project_config_dir)
    if os.path.exists(path):
        os.remove(path)


def write_seq_settings(project_config_dir: str, data: WizardData) -> None:
    settings = {"CC": data.cc, "CXX": data.cxx, "CFLAGS": data.cflags, "CXXFLAGS": data.cxxflags}
    with open(os.path.join(project_config_dir, "seq_settings.json"), "w") as f:
        json.dump(settings, f, indent=2)


def is_meaningful_script(content: str) -> bool:
    """Whether the user actually filled in an optional script editor (more than blank lines and a shebang)."""
    return bool(
        "\n".join(line for line in content.splitlines() if line.strip() and not line.strip().startswith("#!")).strip()
    )


def write_wizard_configuration(arguments: ProjectManagerArguments, data: WizardData) -> str:
    """Write the configuration the wizard collected; returns its name."""
    config_path = os.path.join(arguments.project_config_dir, data.config_name)
    os.makedirs(config_path, exist_ok=True)

    _write_executable(os.path.join(config_path, "execute.sh"), data.execute_sh)

    # validate.sh is optional: only create it if the user provided more than an empty script / bare shebang.
    if is_meaningful_script(data.validate_sh):
        _write_executable(os.path.join(config_path, "validate.sh"), data.validate_sh)

        # compile_validate.sh is equally optional, and pointless without a validate.sh to run against its
        # build -- hence the nesting.
        if is_meaningful_script(data.validate_compile_sh):
            write_script_file(
                get_per_config_validation_compile_script_path(arguments.project_config_dir, data.config_name),
                data.validate_compile_sh,
            )

    initialize_configuration_files(arguments)
    return data.config_name


def has_real_configuration(project_config_dir: str) -> bool:
    """Whether at least one configuration has an execute.sh that was edited (is not the placeholder script)."""
    if not os.path.exists(project_config_dir):
        return False
    for entry in os.scandir(project_config_dir):
        execute_sh = os.path.join(entry.path, "execute.sh")
        if entry.is_dir() and os.path.exists(execute_sh):
            with open(execute_sh, "r") as f:
                if f.read().strip() != initial_script_content.strip():
                    return True
    return False
