# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The execution modes of a configuration and the settings file each one runs with."""

import os
from typing import Dict, List, Optional

EXECUTION_MODES = ("seq", "dp", "hd", "par")


def settings_file_name(mode: str) -> Optional[str]:
    """The name of the shared settings file of ``mode`` (e.g. ``dp_settings.json``), None for an unknown mode."""
    return mode + "_settings.json" if mode in EXECUTION_MODES else None


def settings_path(project_config_dir: str, mode: str) -> Optional[str]:
    name = settings_file_name(mode)
    return os.path.join(project_config_dir, name) if name is not None else None


def available_modes(project_config_dir: str, compile_script: str, execute_script: str) -> Dict[str, bool]:
    """For every mode: whether its settings file, the compile script and the execute script all exist."""
    scripts_exist = os.path.exists(compile_script) and os.path.exists(execute_script)
    result: Dict[str, bool] = {}
    for mode in EXECUTION_MODES:
        path = settings_path(project_config_dir, mode)
        result[mode] = path is not None and os.path.exists(path) and scripts_exist
    return result


def selected_modes_in_order(selected: Dict[str, bool]) -> List[str]:
    """The selected modes in execution order (seq, dp, hd, par)."""
    return [mode for mode in EXECUTION_MODES if selected.get(mode, False)]
