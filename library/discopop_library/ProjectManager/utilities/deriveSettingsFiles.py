# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os
import json
import copy
import logging

logger = logging.getLogger("ConfigurationManager")


def derive_settings_files(config_dir: str, overwrite: bool = True) -> None:
    """Derives dp_settings.json, hd_settings.json, and par_settings.json from the shared seq_settings.json"""
    shared_settings_path = os.path.join(config_dir, "seq_settings.json")
    if not os.path.exists(shared_settings_path):
        raise FileNotFoundError(shared_settings_path)

    with open(shared_settings_path, "r") as f:
        settings = json.load(f)

    shared_dp_settings = os.path.join(config_dir, "dp_settings.json")
    if overwrite or not os.path.exists(shared_dp_settings):
        dp_settings = copy.deepcopy(settings)
        dp_settings["CC"] = "discopop_cc"
        dp_settings["CXX"] = "discopop_cxx"
        with open(shared_dp_settings, "w") as f:
            json.dump(dp_settings, f, indent=2)
        logger.debug("Created derived settings file: " + shared_dp_settings)

    shared_hd_settings = os.path.join(config_dir, "hd_settings.json")
    if overwrite or not os.path.exists(shared_hd_settings):
        hd_settings = copy.deepcopy(settings)
        hd_settings["CC"] = "discopop_hotspot_cc"
        hd_settings["CXX"] = "discopop_hotspot_cxx"
        hd_settings["CFLAGS"] += " -fopenmp" if len(hd_settings["CFLAGS"]) != 0 else "-fopenmp"
        hd_settings["CXXFLAGS"] += " -fopenmp" if len(hd_settings["CXXFLAGS"]) != 0 else "-fopenmp"
        with open(shared_hd_settings, "w") as f:
            json.dump(hd_settings, f, indent=2)
        logger.debug("Created derived settings file: " + shared_hd_settings)

    shared_par_settings = os.path.join(config_dir, "par_settings.json")
    if overwrite or not os.path.exists(shared_par_settings):
        parallel_settings = copy.deepcopy(settings)
        parallel_settings["CFLAGS"] += " -fopenmp" if len(parallel_settings["CFLAGS"]) != 0 else "-fopenmp"
        parallel_settings["CXXFLAGS"] += " -fopenmp" if len(parallel_settings["CXXFLAGS"]) != 0 else "-fopenmp"
        with open(shared_par_settings, "w") as f:
            json.dump(parallel_settings, f, indent=2)
        logger.debug("Created derived settings file: " + shared_par_settings)
