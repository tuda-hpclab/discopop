# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

import pytest

from discopop_library.ProjectManager.services.configurations import WizardData, list_configurations
from discopop_library.ProjectManager.services.jobs import WorkFinished
from discopop_library.ProjectManager.services.wizard import (
    compute_derived_settings,
    describe_test_compilation,
    existing_compile_script,
    initial_seq_settings,
    save_derived_settings,
)
from discopop_library.ProjectManager.utilities.initializeFiles import initial_script_content


def test_list_configurations_is_sorted_and_ignores_files(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "compile.sh").write_text("")
    assert list_configurations(str(tmp_path)) == ["a", "b"]
    assert list_configurations(str(tmp_path / "missing")) == []


def test_existing_compile_script_ignores_the_initial_one(tmp_path: Path) -> None:
    assert existing_compile_script(str(tmp_path)) is None
    (tmp_path / "compile.sh").write_text(initial_script_content)
    assert existing_compile_script(str(tmp_path)) is None
    (tmp_path / "compile.sh").write_text("#!/bin/bash\n$CC x.c\n")
    assert existing_compile_script(str(tmp_path)) == "#!/bin/bash\n$CC x.c\n"


def test_initial_seq_settings_fill_missing_keys(tmp_path: Path) -> None:
    assert initial_seq_settings(str(tmp_path))["CC"] == "clang"
    (tmp_path / "seq_settings.json").write_text(json.dumps({"CXX": "g++"}))
    assert initial_seq_settings(str(tmp_path)) == {"CC": "clang", "CXX": "g++", "CFLAGS": "", "CXXFLAGS": ""}


def test_derived_settings_use_the_wrappers() -> None:
    data = WizardData(cc="gcc", cxx="g++", cflags="-O1")
    derived = compute_derived_settings(data)
    assert derived["dp_settings"]["CXX"] == "discopop_cxx" and derived["par_settings"]["CC"] == "gcc"
    assert data.derived_settings == derived


def test_invalid_derived_settings_write_nothing(tmp_path: Path) -> None:
    with pytest.raises(json.JSONDecodeError):
        save_derived_settings(str(tmp_path), "{}", "{", "{}")
    assert list(tmp_path.iterdir()) == []
    save_derived_settings(str(tmp_path), "{}", "{}", '{"a": 1}\n')
    assert json.loads((tmp_path / "par_settings.json").read_text()) == {"a": 1}


def test_describe_test_compilation() -> None:
    ok = describe_test_compilation(WorkFinished(result=(0, 1.5, "out", ""), error=None))
    assert (ok.status, ok.kind, ok.output) == ("✓ Success", "ok", ["Compilation succeeded (1.50s)\n", "stdout:\nout\n"])
    bad = describe_test_compilation(WorkFinished(result=(2, 0.5, "", "err"), error=None))
    assert bad.status == "✗ Failed (exit code: 2)" and bad.output[-1] == "stderr:\nerr\n"
    assert describe_test_compilation(WorkFinished(result=None, error=None)).output == [
        "Compilation failed: settings file not found.\n"
    ]
    assert describe_test_compilation(WorkFinished(result=None, error="boom")).output == ["Compilation failed: boom\n"]
