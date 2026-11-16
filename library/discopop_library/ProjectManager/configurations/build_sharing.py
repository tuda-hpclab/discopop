# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Sharing a build between configurations that differ only in what the runs do (input, arguments, threads).

A configuration may declare ``build_from: <owner>`` in ``<config dir>/<member>/build_from.json``. The build of the
owner (its compile script, settings and build files, see :data:`RUN_ONLY_FILES`) is then also the build of the member,
whose ``execute.sh`` / ``validate.sh`` run in the owner's build tree. Owners do not build from others (no chains).
Everything here is toolkit free and the only place that reads the declaration.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

from discopop_library.ProjectManager.configurations.compile_script import (
    VALIDATION_COMPILE_SCRIPT_NAME,
    get_per_config_validation_compile_script_path,
    get_shared_validation_compile_script_path,
)

PATH = str

logger = logging.getLogger("ConfigurationManager")

BUILD_FROM_FILE = "build_from.json"

# the files of a configuration directory that only the runs read; every other file can change the build
# (see ``builds.configuration_fingerprint``)
RUN_ONLY_FILES = ("execute.sh", "validate.sh", "execution_time.json", BUILD_FROM_FILE)


class BuildSharingError(Exception):
    """Sharing cannot be set up; the message tells the user why."""


@dataclass(frozen=True)
class BuildInputs:
    """Which configuration compiles for a configuration and which one runs.

    ``build_config`` names the configuration whose compile script, settings and files make the build (and whose
    build id is used); ``run_config`` is the configuration whose execute.sh / validate.sh run in it.
    """

    build_config: str
    run_config: str

    @property
    def shared(self) -> bool:
        return self.build_config != self.run_config


def _declared_owner(config_dir: PATH, config: str) -> Optional[str]:
    try:
        with open(os.path.join(config_dir, config, BUILD_FROM_FILE), "r") as f:
            owner = json.load(f).get("build_from")
    except (OSError, ValueError, AttributeError):
        return None
    return owner if isinstance(owner, str) and owner else None


def declared_owner_of(config_dir: PATH, config: str) -> Optional[str]:
    """The owner ``config`` declares, even if it is not usable (missing or itself a member); None if none."""
    return _declared_owner(config_dir, config)


def build_owner_of(config_dir: PATH, config: str) -> str:
    """The configuration whose build serves ``config``: its declared owner, else ``config`` itself.

    A declaration that cannot be followed (the owner does not exist, is ``config`` itself or builds from another
    configuration) is ignored with a warning, so that the configuration builds for itself.
    """
    owner = _declared_owner(config_dir, config)
    if owner is None:
        return config
    if owner == config or not os.path.isdir(os.path.join(config_dir, owner)) or _declared_owner(config_dir, owner):
        logger.warning("Configuration " + config + " declares the unusable build owner " + owner + ", ignored.")
        return config
    return owner


def build_inputs_for(config_dir: PATH, config: str) -> BuildInputs:
    return BuildInputs(build_owner_of(config_dir, config), config)


def members_of(config_dir: PATH, owner: str) -> List[str]:
    """The configurations that build from ``owner`` (sorted)."""
    if not os.path.isdir(config_dir):
        return []
    return sorted(
        name
        for name in os.listdir(config_dir)
        if name != owner and os.path.isdir(os.path.join(config_dir, name)) and build_owner_of(config_dir, name) == owner
    )


def own_build_files(config_dir: PATH, config: str) -> List[str]:
    """The files of ``config`` that would change a build, which a member cannot have (relative to its directory)."""
    directory = os.path.join(config_dir, config)
    found: List[str] = []
    for current, _subdirectories, files in os.walk(directory):
        for name in files:
            relative = os.path.relpath(os.path.join(current, name), directory)
            if relative not in RUN_ONLY_FILES:
                found.append(relative)
    return sorted(found)


def validation_compile_script_of(config_dir: PATH, config: str) -> Optional[PATH]:
    """The separate validation compile script that applies to ``config`` (its own or the shared one), if any."""
    for path in (
        get_per_config_validation_compile_script_path(config_dir, config),
        get_shared_validation_compile_script_path(config_dir),
    ):
        if os.path.exists(path):
            return path
    return None


def check_can_share(config_dir: PATH, member: str, owner: str) -> None:
    """Raise :class:`BuildSharingError` if ``member`` cannot build from ``owner``."""
    if member == owner:
        raise BuildSharingError("A configuration cannot build from itself.")
    for name in (member, owner):
        if not os.path.isdir(os.path.join(config_dir, name)):
            raise BuildSharingError("The configuration " + name + " does not exist.")
    if _declared_owner(config_dir, owner):
        raise BuildSharingError(
            owner + " builds from " + str(_declared_owner(config_dir, owner)) + " itself; builds are not chained."
        )
    others = members_of(config_dir, member)
    if others:
        raise BuildSharingError(
            member + " is the build owner of " + ", ".join(others) + "; let them build from " + owner + " first."
        )
    files = own_build_files(config_dir, member)
    if files:
        raise BuildSharingError(
            member + " has files of its own that change the build (" + ", ".join(files) + "); remove them first."
        )
    script = validation_compile_script_of(config_dir, owner)
    if script is not None:
        raise BuildSharingError(
            "The build of "
            + owner
            + " cannot be shared: it has a separate validation compile script ("
            + os.path.basename(script)
            + " = "
            + VALIDATION_COMPILE_SCRIPT_NAME
            + "), whose compilation changes the build tree and would make the build of every member stale."
        )


def set_build_from(config_dir: PATH, member: str, owner: Optional[str]) -> None:
    """Let ``member`` build from ``owner``, or build for itself again if ``owner`` is None."""
    path = os.path.join(config_dir, member, BUILD_FROM_FILE)
    if owner is None:
        if os.path.exists(path):
            os.remove(path)
        return
    check_can_share(config_dir, member, owner)
    with open(path, "w") as f:
        json.dump({"build_from": owner}, f, indent=2)


def stale_declaration_problems(config_dir: PATH, config: str) -> List[str]:
    """What stopped being true for the declaration of ``config`` since it was made (empty if all is well).

    Checked when a build is requested: an own ``compile.sh`` added later would be silently ignored otherwise.
    """
    owner = _declared_owner(config_dir, config)
    if owner is None:
        return []
    problems: List[str] = []
    if build_owner_of(config_dir, config) != owner:
        problems.append("the build owner " + owner + " is missing or builds from another configuration")
        return problems
    files = own_build_files(config_dir, config)
    if files:
        problems.append("its own files " + ", ".join(files) + " are ignored; the build is the one of " + owner)
    if validation_compile_script_of(config_dir, owner) is not None:
        problems.append(
            owner + " has a validation compile script, which makes the shared build stale after validations"
        )
    return problems


def detach_members(config_dir: PATH, owner: str) -> List[str]:
    """Let every member of ``owner`` build for itself again; returns them."""
    members = members_of(config_dir, owner)
    for member in members:
        set_build_from(config_dir, member, None)
    return members


def repoint_members(config_dir: PATH, old_owner: str, new_owner: str) -> List[str]:
    """After renaming ``old_owner`` to ``new_owner``: the declarations of its members follow."""
    changed: List[str] = []
    for name in os.listdir(config_dir):
        if os.path.isdir(os.path.join(config_dir, name)) and _declared_owner(config_dir, name) == old_owner:
            with open(os.path.join(config_dir, name, BUILD_FROM_FILE), "w") as f:
                json.dump({"build_from": new_owner}, f, indent=2)
            changed.append(name)
    return sorted(changed)
