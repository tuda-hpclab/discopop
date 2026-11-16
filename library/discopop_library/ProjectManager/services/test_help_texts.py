# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import pytest

from discopop_library.ProjectManager.services.help_texts import HELP_TEXTS


@pytest.mark.parametrize("script", ["compile.sh", "compile_validate.sh", "execute.sh", "validate.sh"])
def test_the_help_of_a_script_names_the_project_root_variable(script: str) -> None:
    assert "DP_PROJECT_ROOT_DIR" in HELP_TEXTS[script][1]
