# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from discopop_library.EmpiricalAutotuning.agent_approved import add_published_approvals
from discopop_library.BlockerResolution.publish import MARKER_FILE
from discopop_library.BlockerResolution.unsure import UNSURE_SUGGESTIONS_FILE


def _result(ids: List[int]) -> SimpleNamespace:
    return SimpleNamespace(patterns=SimpleNamespace(do_all=[], get_pattern_ids=lambda: list(ids)))


def _dot(tmp_path: Path, published: List[int], unsure: List[int]) -> Path:
    dot = tmp_path / ".discopop"
    (dot / "explorer").mkdir(parents=True)
    (dot / UNSURE_SUGGESTIONS_FILE).write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "pattern_id": i,
                        "node_id": "1:2",
                        "start_line": "1:7",
                        "end_line": "1:9",
                        "pragma": "#pragma omp parallel for",
                    }
                    for i in unsure
                ]
            }
        )
    )
    for i in published:
        target = dot / "patch_generator" / str(i)
        target.mkdir(parents=True)
        (target / "1.patch").write_text("p")
        (target / MARKER_FILE).write_text("{}")
    return dot


def test_published_approvals_become_do_all_candidates(tmp_path: Path) -> None:
    dot = _dot(tmp_path, [7], [7, 8])
    result = _result([1])
    assert add_published_approvals(result, str(dot), logging.getLogger("t")) == [7]
    (pattern,) = result.patterns.do_all
    assert pattern.pattern_id == 7 and pattern.start_line == "1:7"
    assert pattern.applicable_pattern and pattern.standalone_pattern
    assert type(pattern).__name__ == "DoAllInfo"


def test_nothing_published_nothing_added(tmp_path: Path) -> None:
    dot = _dot(tmp_path, [], [7])
    result = _result([])
    assert add_published_approvals(result, str(dot), logging.getLogger("t")) == []
    assert result.patterns.do_all == []


def test_an_id_the_explorer_already_uses_is_not_added(tmp_path: Path) -> None:
    dot = _dot(tmp_path, [7], [7])
    result = _result([7])
    assert add_published_approvals(result, str(dot), logging.getLogger("t")) == []


def test_the_search_includes_published_approvals_unless_told_not_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """Published means the user has not withdrawn them: they are searched unless --no-agent-approved is given."""
    from discopop_library.EmpiricalAutotuning import __main__ as autotuner_main

    # the arguments as parsed; constructing AutotunerArguments would check the .discopop directory
    monkeypatch.setattr(autotuner_main, "AutotunerArguments", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(sys, "argv", ["discopop_auto_tuner"])
    assert autotuner_main.parse_args().include_agent_approved
    monkeypatch.setattr(sys, "argv", ["discopop_auto_tuner", "--no-agent-approved"])
    assert not autotuner_main.parse_args().include_agent_approved
