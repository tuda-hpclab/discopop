# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The opencode backend: the model of a call, and the default the opencode CLI uses."""

import json
from typing import Dict, List
from pathlib import Path

import pytest

from discopop_library.PatchRepair.llm_backends import opencode

# placeholder names: the test must not depend on which models a machine has
RECENT = {"providerID": "provider-a", "modelID": "model-a"}
OTHER = {"providerID": "provider-b", "modelID": "model-b"}
RECENT_MODEL = RECENT["providerID"] + "/" + RECENT["modelID"]
CONFIGURED_MODEL = OTHER["providerID"] + "/" + OTHER["modelID"]


def write_state(state_home: Path, recent: List[Dict[str, str]]) -> None:
    (state_home / "opencode").mkdir(parents=True)
    (state_home / "opencode" / "model.json").write_text(json.dumps({"recent": recent, "favorite": []}))


def test_without_a_model_the_cli_default_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_state(tmp_path, [RECENT, OTHER])
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert opencode.build_argv({"model": ""}, "hi", "/tmp") == [
        "opencode",
        "run",
        "--format",
        "json",
        "-m",
        RECENT_MODEL,
        "--",
        "hi",
    ]


def test_a_configured_model_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_state(tmp_path, [RECENT])
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    argv = opencode.build_argv({"model": CONFIGURED_MODEL}, "hi", "/tmp")
    assert argv[argv.index("-m") + 1] == CONFIGURED_MODEL


def test_no_state_means_no_model_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert opencode.cli_default_model() == ""
    assert "-m" not in opencode.build_argv({"model": ""}, "hi", "/tmp")
