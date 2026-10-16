# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The settings of the dp, hd and par modes, derived from those of the sequential mode."""

import copy
from typing import Dict

Settings = Dict[str, str]

OPENMP_FLAG = "-fopenmp"


def _with_openmp(flags: str) -> str:
    return flags + " " + OPENMP_FLAG if len(flags) != 0 else OPENMP_FLAG


def derive_settings(seq_settings: Settings) -> Dict[str, Settings]:
    """Return the ``dp``, ``hd`` and ``par`` settings for the given ``seq`` settings.

    dp: the DiscoPoP compiler wrappers. hd: the hotspot detection wrappers, compiled with OpenMP.
    par: the original compilers, compiled with OpenMP. Requires the keys ``CFLAGS`` and ``CXXFLAGS``.
    """
    dp_settings = copy.deepcopy(seq_settings)
    dp_settings["CC"] = "discopop_cc"
    dp_settings["CXX"] = "discopop_cxx"

    hd_settings = copy.deepcopy(seq_settings)
    hd_settings["CC"] = "discopop_hotspot_cc"
    hd_settings["CXX"] = "discopop_hotspot_cxx"
    hd_settings["CFLAGS"] = _with_openmp(hd_settings["CFLAGS"])
    hd_settings["CXXFLAGS"] = _with_openmp(hd_settings["CXXFLAGS"])

    par_settings = copy.deepcopy(seq_settings)
    par_settings["CFLAGS"] = _with_openmp(par_settings["CFLAGS"])
    par_settings["CXXFLAGS"] = _with_openmp(par_settings["CXXFLAGS"])

    return {"dp": dp_settings, "hd": hd_settings, "par": par_settings}
