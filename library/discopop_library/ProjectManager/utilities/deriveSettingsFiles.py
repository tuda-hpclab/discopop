# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os
import json
import logging

from discopop_library.ProjectManager.services.derived_settings import derive_settings

logger = logging.getLogger("ConfigurationManager")


def derive_settings_files(config_dir: str, overwrite: bool = True) -> None:
    """Derives dp_settings.json, hd_settings.json, and par_settings.json from the shared seq_settings.json"""
    shared_settings_path = os.path.join(config_dir, "seq_settings.json")
    if not os.path.exists(shared_settings_path):
        raise FileNotFoundError(shared_settings_path)

    with open(shared_settings_path, "r") as f:
        settings = json.load(f)

    derived = derive_settings(settings)
    for mode in ("dp", "hd", "par"):
        derived_path = os.path.join(config_dir, mode + "_settings.json")
        if overwrite or not os.path.exists(derived_path):
            with open(derived_path, "w") as f:
                json.dump(derived[mode], f, indent=2)
            logger.debug("Created derived settings file: " + derived_path)
