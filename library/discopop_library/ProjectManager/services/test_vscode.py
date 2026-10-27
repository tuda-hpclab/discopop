# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import subprocess
from typing import Any, List

import pytest

from discopop_library.ProjectManager.services import vscode


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> List[List[str]]:
    calls: List[List[str]] = []

    def fake_popen(arguments: List[str], **_kwargs: Any) -> None:
        calls.append(arguments)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return calls


def test_open_project_opens_the_parent_of_dot_discopop_and_focuses_the_extension(launched: List[List[str]]) -> None:
    vscode.open_project("code", "/work/my project/.discopop")
    assert launched[0] == ["code", "/work/my project"]
    assert launched[1][:2] == ["code", "--open-url"]
    assert launched[1][2].startswith("vscode://TUDarmstadt-LaboratoryforParallelProgramming.discopop/focus?")
    assert "dotDiscopop=%2Fwork%2Fmy%20project%2F.discopop" in launched[1][2]
    assert "projectPath=%2Fwork%2Fmy%20project" in launched[1][2]


def test_open_file_at(launched: List[List[str]]) -> None:
    vscode.open_file_at("code", "/a/b.cpp", 12)
    assert launched == [["code", "--goto", "/a/b.cpp:12"]]


def test_a_failing_focus_call_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[List[str]] = []

    def popen(arguments: List[str], **_kwargs: Any) -> None:
        calls.append(arguments)
        if "--open-url" in arguments:
            raise OSError("no")

    monkeypatch.setattr(subprocess, "Popen", popen)
    vscode.open_project("code", "/p/.discopop")
    assert len(calls) == 2


def test_a_failing_first_call_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def popen(arguments: List[str], **_kwargs: Any) -> None:
        raise OSError("no")

    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(OSError):
        vscode.open_project("code", "/p/.discopop")
