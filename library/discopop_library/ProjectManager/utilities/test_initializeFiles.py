# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.utilities.initializeFiles import initialize_configuration_files


@pytest.mark.parametrize("directory_name", ["plain", "with space", "semi;colon", "dollar$HOME"])
def test_created_scripts_are_executable(tmp_path: Path, directory_name: str) -> None:
    # characters a shell would interpret must not matter, the path is never handed to one
    config_dir = tmp_path / directory_name / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    arguments = cast(ProjectManagerArguments, SimpleNamespace(project_config_dir=str(config_dir)))

    initialize_configuration_files(arguments)

    for script in (config_dir / "compile.sh", config_dir / "tiny" / "execute.sh"):
        assert script.is_file()
        assert os.access(script, os.X_OK), script
    assert (config_dir / "seq_settings.json").is_file()
