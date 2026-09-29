# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os

PATH = str

# Name of the compilation script used to build the code that execute.sh runs.
COMPILE_SCRIPT_NAME = "compile.sh"
# Name of the optional compilation script used to build the code that validate.sh runs.
VALIDATION_COMPILE_SCRIPT_NAME = "compile_validate.sh"


def get_shared_compile_script_path(project_config_dir: PATH) -> PATH:
    return os.path.join(project_config_dir, COMPILE_SCRIPT_NAME)


def get_per_config_compile_script_path(project_config_dir: PATH, config_name: str) -> PATH:
    return os.path.join(project_config_dir, config_name, COMPILE_SCRIPT_NAME)


def resolve_compile_script_path(project_config_dir: PATH, config_name: str) -> PATH:
    """Returns the per-configuration compile.sh if it exists, otherwise the shared project-level one."""
    per_config_path = get_per_config_compile_script_path(project_config_dir, config_name)
    if os.path.exists(per_config_path):
        return per_config_path
    return get_shared_compile_script_path(project_config_dir)


def get_shared_validation_compile_script_path(project_config_dir: PATH) -> PATH:
    return os.path.join(project_config_dir, VALIDATION_COMPILE_SCRIPT_NAME)


def get_per_config_validation_compile_script_path(project_config_dir: PATH, config_name: str) -> PATH:
    return os.path.join(project_config_dir, config_name, VALIDATION_COMPILE_SCRIPT_NAME)


def resolve_validation_compile_script_path(project_config_dir: PATH, config_name: str) -> PATH:
    """Returns the compilation script used to build the code that validate.sh runs.

    validate.sh may require a differently compiled binary than the timed
    execute.sh run. The script is looked up by role first and by specificity
    second, i.e. a shared compile_validate.sh takes precedence over a
    per-configuration compile.sh override:

    1. <config>/compile_validate.sh
    2. compile_validate.sh
    3. whatever resolve_compile_script_path() returns

    Falling through to (3) reproduces the historic behaviour of a single build
    serving both execute.sh and validate.sh.
    """
    per_config_path = get_per_config_validation_compile_script_path(project_config_dir, config_name)
    if os.path.exists(per_config_path):
        return per_config_path
    shared_path = get_shared_validation_compile_script_path(project_config_dir)
    if os.path.exists(shared_path):
        return shared_path
    return resolve_compile_script_path(project_config_dir, config_name)


def validation_needs_separate_compile(project_config_dir: PATH, config_name: str) -> bool:
    """Whether validate.sh requires its own build in addition to the execute.sh build."""
    return os.path.abspath(resolve_validation_compile_script_path(project_config_dir, config_name)) != os.path.abspath(
        resolve_compile_script_path(project_config_dir, config_name)
    )
