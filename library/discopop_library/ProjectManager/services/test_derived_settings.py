# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``derive_settings`` replaced two implementations (the CLI's file writer and the wizard's preview); both
are compared with it here, the wizard's as it was before the unification."""

import json
import os
from pathlib import Path
from typing import Dict

import pytest

from discopop_library.ProjectManager.services.derived_settings import derive_settings
from discopop_library.ProjectManager.utilities.deriveSettingsFiles import derive_settings_files

CASES = [
    {"CC": "clang", "CXX": "clang++", "CFLAGS": "", "CXXFLAGS": ""},
    {"CC": "gcc", "CXX": "g++", "CFLAGS": "-O2 -g", "CXXFLAGS": "-O3"},
    {"CC": "gcc", "CXX": "g++", "CFLAGS": "-O2", "CXXFLAGS": ""},
]


def _wizard_before_unification(step_data: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Verbatim logic of ConfigurationWizard._compute_and_display_derived_settings before this change."""
    seq_settings = {
        "CC": step_data["cc"],
        "CXX": step_data["cxx"],
        "CFLAGS": step_data["cflags"],
        "CXXFLAGS": step_data["cxxflags"],
    }
    dp_settings = json.loads(json.dumps(seq_settings))
    dp_settings["CC"] = "discopop_cc"
    dp_settings["CXX"] = "discopop_cxx"
    hd_settings = json.loads(json.dumps(seq_settings))
    hd_settings["CC"] = "discopop_hotspot_cc"
    hd_settings["CXX"] = "discopop_hotspot_cxx"
    hd_settings["CFLAGS"] = hd_settings["CFLAGS"] + " -fopenmp" if len(hd_settings["CFLAGS"]) != 0 else "-fopenmp"
    hd_settings["CXXFLAGS"] = hd_settings["CXXFLAGS"] + " -fopenmp" if len(hd_settings["CXXFLAGS"]) != 0 else "-fopenmp"
    par_settings = json.loads(json.dumps(seq_settings))
    par_settings["CFLAGS"] = par_settings["CFLAGS"] + " -fopenmp" if len(par_settings["CFLAGS"]) != 0 else "-fopenmp"
    par_settings["CXXFLAGS"] = (
        par_settings["CXXFLAGS"] + " -fopenmp" if len(par_settings["CXXFLAGS"]) != 0 else "-fopenmp"
    )
    return {"dp": dp_settings, "hd": hd_settings, "par": par_settings}


@pytest.mark.parametrize("seq", CASES)
def test_matches_the_wizard_before_the_unification(seq: Dict[str, str]) -> None:
    step_data = {"cc": seq["CC"], "cxx": seq["CXX"], "cflags": seq["CFLAGS"], "cxxflags": seq["CXXFLAGS"]}
    derived = derive_settings(seq)
    expected = _wizard_before_unification(step_data)
    assert derived == expected
    # the wizard shows json.dumps of these, so the key order matters as well
    assert {k: list(v) for k, v in derived.items()} == {k: list(v) for k, v in expected.items()}


@pytest.mark.parametrize("seq", CASES)
def test_matches_the_files_written_by_the_cli(seq: Dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "seq_settings.json").write_text(json.dumps(seq))
    derive_settings_files(str(tmp_path))
    derived = derive_settings(seq)
    for mode, settings in derived.items():
        with open(os.path.join(tmp_path, mode + "_settings.json")) as f:
            assert json.load(f) == settings


def test_the_input_is_not_modified() -> None:
    seq = dict(CASES[1])
    derive_settings(seq)
    assert seq == CASES[1]
