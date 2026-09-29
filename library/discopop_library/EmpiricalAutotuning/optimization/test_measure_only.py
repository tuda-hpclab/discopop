# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which suggestions ``-A 0`` measures one at a time.

``discopop_patch_repair`` compiles its candidates through ``-A 0 --compile-only
--search-space``, so a suggestion this algorithm leaves out is never built and never
reported. The builds themselves are out of scope here; the reference configuration is
a stub that records what it is asked to apply.
"""

import logging
from typing import Any, Dict, List, Optional

import pytest

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.optimization import measure_only
from discopop_library.HostpotLoader.HotspotType import HotspotType


class _Patterns:
    def __init__(self, ids: List[int]) -> None:
        self.ids = ids

    def get_pattern_ids(self) -> List[int]:
        return list(self.ids)


class _DetectionResult:
    def __init__(self, ids: List[int]) -> None:
        self.patterns = _Patterns(ids)


class _Configuration:
    def __init__(self, applied: List[List[int]]) -> None:
        self.applied = applied
        self.execution_result: Optional[ExecutionResult] = None
        self.root_path = ""

    def create_copy(self, *args: Any) -> "_Configuration":
        return _Configuration(self.applied)

    def apply_suggestions(self, arguments: Any, suggestions: List[int]) -> None:
        self.applied.append(list(suggestions))

    def execute(self, *args: Any, **kwargs: Any) -> None:
        result = ExecutionResult.__new__(ExecutionResult)
        result.runtime = 1.0
        result.return_code = 0
        result.result_valid = True
        result.thread_sanitizer = False
        result.failed_suggestions = []
        self.execution_result = result

    def deleteFolder(self) -> None:
        pass


def _measured(monkeypatch: pytest.MonkeyPatch, hotspot_types: str, search_space: Optional[str]) -> List[List[int]]:
    by_type: Dict[HotspotType, List[int]] = {HotspotType.YES: [1], HotspotType.MAYBE: [2], HotspotType.NO: [3]}
    monkeypatch.setattr(measure_only, "get_patterns_by_hotspot_type", lambda *a: by_type)
    monkeypatch.setattr(measure_only, "show_debug_stats", lambda *a: None)
    arguments = AutotunerArguments.__new__(AutotunerArguments)
    arguments.hotspot_types = hotspot_types
    arguments.search_space = search_space
    arguments.skip_cleanup = True
    arguments.thread_count = 1
    applied: List[List[int]] = []
    measure_only.execute_measure_only(
        _DetectionResult([1, 2, 3, 4]),  # type: ignore[arg-type]
        {},
        logging.getLogger("test_measure_only"),
        3600,
        _Configuration(applied),  # type: ignore[arg-type]
        arguments,
        0.0,
        [],
        lambda: 0,
    )
    return applied


def test_without_a_search_space_only_the_selected_buckets_are_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _measured(monkeypatch, "yes,maybe", None) == [[1], [2]]


def test_an_unclassified_suggestion_in_the_search_space_is_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _measured(monkeypatch, "yes,no,maybe", "1,2,3,4") == [[1], [2], [3], [4]]
