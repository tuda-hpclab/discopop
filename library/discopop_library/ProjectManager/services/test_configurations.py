# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services.configurations import (
    AlreadyExistsError,
    EmptyNameError,
    SameNameError,
    WizardData,
    copy_configuration_directory,
    create_configuration,
    delete_configuration_directory,
    has_real_configuration,
    is_meaningful_script,
    rename_configuration,
    write_seq_settings,
    write_shared_compile_script,
    write_wizard_configuration,
)


def _arguments(tmp_path: Path) -> ProjectManagerArguments:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    return cast(ProjectManagerArguments, SimpleNamespace(project_config_dir=str(config_dir)))


def test_create_strips_the_name_and_creates_the_shared_files(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    assert create_configuration(arguments, "  tiny ") == "tiny"
    assert os.path.isdir(os.path.join(arguments.project_config_dir, "tiny"))
    assert os.path.exists(os.path.join(arguments.project_config_dir, "compile.sh"))
    assert os.path.exists(os.path.join(arguments.project_config_dir, "seq_settings.json"))


def test_invalid_names(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    create_configuration(arguments, "a")
    with pytest.raises(EmptyNameError):
        create_configuration(arguments, "   ")
    with pytest.raises(AlreadyExistsError):
        create_configuration(arguments, "a")
    with pytest.raises(SameNameError):
        copy_configuration_directory(arguments.project_config_dir, "a", " a")
    with pytest.raises(SameNameError):
        rename_configuration(arguments.project_config_dir, "a", "a")


def test_copy_rename_delete(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    config_dir = arguments.project_config_dir
    create_configuration(arguments, "a")
    Path(config_dir, "a", "execute.sh").write_text("echo")
    copy_configuration_directory(config_dir, "a", "b")
    assert Path(config_dir, "b", "execute.sh").read_text() == "echo"
    with pytest.raises(AlreadyExistsError):
        rename_configuration(config_dir, "a", "b")
    assert rename_configuration(config_dir, "a", "c") == "c"
    assert not os.path.exists(os.path.join(config_dir, "a"))
    delete_configuration_directory(config_dir, "c")
    assert not os.path.exists(os.path.join(config_dir, "c"))


def test_is_meaningful_script() -> None:
    assert not is_meaningful_script("")
    assert not is_meaningful_script("#!/bin/bash\n\n  \n")
    assert is_meaningful_script("#!/bin/bash\nmake\n")
    assert is_meaningful_script("# a comment is content\n")


def test_wizard_files(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    data = WizardData(
        compile_sh="make CC=$CC\n",
        cc="gcc",
        cxx="g++",
        cflags="-O2",
        cxxflags="",
        config_name="mine",
        execute_sh="./prog\n",
        validate_sh="#!/bin/bash\ndiff a b\n",
        validate_compile_sh="#!/bin/bash\n\n",
    )
    config_dir = arguments.project_config_dir
    write_shared_compile_script(config_dir, data)
    write_seq_settings(config_dir, data)
    assert write_wizard_configuration(arguments, data) == "mine"

    compile_sh = Path(config_dir, "compile.sh")
    assert compile_sh.read_text() == "make CC=$CC\n"  # written as typed
    assert os.access(compile_sh, os.X_OK)
    assert json.loads(Path(config_dir, "seq_settings.json").read_text()) == {
        "CC": "gcc",
        "CXX": "g++",
        "CFLAGS": "-O2",
        "CXXFLAGS": "",
    }
    execute_sh = Path(config_dir, "mine", "execute.sh")
    assert execute_sh.read_text() == "./prog\n" and os.access(execute_sh, os.X_OK)
    assert os.access(Path(config_dir, "mine", "validate.sh"), os.X_OK)
    # an empty compile script for the validation is not written
    assert not any(
        "compile_validate" in name or "validate_compile" in name for name in os.listdir(Path(config_dir, "mine"))
    )


def test_optional_scripts_are_skipped_when_empty(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    data = WizardData(config_name="x", execute_sh="run\n", validate_sh="#!/bin/bash\n", validate_compile_sh="make\n")
    write_wizard_configuration(arguments, data)
    assert sorted(os.listdir(Path(arguments.project_config_dir, "x"))) == ["execute.sh"]


def test_has_real_configuration(tmp_path: Path) -> None:
    from discopop_library.ProjectManager.utilities.initializeFiles import initial_script_content

    arguments = _arguments(tmp_path)
    config_dir = arguments.project_config_dir
    assert not has_real_configuration(str(tmp_path / "missing"))
    assert not has_real_configuration(config_dir)
    create_configuration(arguments, "a")
    Path(config_dir, "a", "execute.sh").write_text(initial_script_content)
    assert not has_real_configuration(config_dir)
    Path(config_dir, "a", "execute.sh").write_text("./prog\n")
    assert has_real_configuration(config_dir)
