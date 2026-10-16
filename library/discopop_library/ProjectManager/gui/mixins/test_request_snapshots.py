# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The panels hand immutable snapshots to their worker threads (no display needed: Tk variables are stand-ins)."""

import dataclasses
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from discopop_library.ProjectManager.gui.mixins.autotuning_panel import AutotuningPanelMixin
from discopop_library.ProjectManager.gui.mixins.explorer_integration import ExplorerIntegrationMixin
from discopop_library.ProjectManager.gui.mixins.patch_repair_panel import PatchRepairPanelMixin
from discopop_library.ProjectManager.services.requests import AutotunerRequest


class _Var:
    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value


class _Selector:
    def __init__(self, ids: List[str], all_selected: bool = False) -> None:
        self._ids = ids
        self._all = all_selected

    def get_selected_ids(self) -> List[str]:
        return list(self._ids)

    def is_all_selected(self) -> bool:
        return self._all


def _autotuner_panel(mode: str = "search", repetitions: str = "3") -> Any:
    return SimpleNamespace(
        autotuning_threads_var=_Var("4"),
        autotuning_hotspot_types_vars={"yes": _Var(True), "no": _Var(False), "maybe": _Var(True)},
        autotuning_algorithm_var=_Var("desc"),
        autotuning_algorithm_map={"desc": "2"},
        autotuning_log_level_var=_Var("INFO"),
        autotuning_repetitions_var=_Var(repetitions),
        autotuning_suggestions_mode_var=_Var(mode),
        autotuner_evaluate_selector=_Selector(["1", "2"]),
        autotuner_search_space_selector=_Selector(["5"], all_selected=False),
        current_config="tiny",
    )


def _snapshot(panel: Any) -> AutotunerRequest:
    return AutotuningPanelMixin._snapshot_autotuner_request(panel)


def test_autotuner_snapshot_search_mode() -> None:
    request = _snapshot(_autotuner_panel())
    assert request.hotspot_types == "yes,maybe"
    assert request.threads == "4"
    assert request.repetitions == 3
    assert request.repetitions_warning is None
    assert request.algorithm == "2"
    assert request.search_space_ids == ("5",)
    assert request.evaluate_ids == ()


def test_autotuner_snapshot_evaluate_mode() -> None:
    request = _snapshot(_autotuner_panel(mode="evaluate"))
    assert request.evaluate_ids == ("1", "2")
    assert request.search_space_ids is None


def test_autotuner_snapshot_unusable_repetitions_fall_back_with_a_warning() -> None:
    request = _snapshot(_autotuner_panel(repetitions="x"))
    assert request.repetitions == 1
    assert request.repetitions_warning is not None


def test_snapshot_is_immutable_and_independent_of_later_changes() -> None:
    panel = _autotuner_panel()
    request = _snapshot(panel)
    panel.autotuning_threads_var = _Var("8")
    assert request.threads == "4"
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.threads = "2"  # type: ignore[misc]


def test_patch_repair_snapshot() -> None:
    panel = SimpleNamespace(
        patch_repair_hotspot_types_vars={"yes": _Var(False), "no": _Var(False)},
        patch_repair_selector=_Selector(["7"], all_selected=False),
        patch_repair_prompts_var=_Var("3"),
        patch_repair_retries_var=_Var("1"),
        patch_repair_timeout_var=_Var("60"),
        patch_repair_log_level_var=None,
        patch_repair_backend_var=_Var("claude"),
        patch_repair_model_var=_Var("  m  "),
        patch_repair_dry_run_var=_Var(True),
        current_config=None,
    )
    request = PatchRepairPanelMixin._snapshot_patch_repair_request(panel)  # type: ignore[arg-type]
    assert (request.prompts, request.retries, request.agent_timeout) == (3, 1, 60)
    assert request.model == "m"
    assert request.log_level == "INFO"
    assert request.configuration == "tiny"
    assert request.dry_run is True
    assert request.suggestion_ids == ("7",)


def test_explorer_snapshot() -> None:
    panel: Dict[str, Any] = dict(
        pattern_types_vars={"reduction": _Var(False), "doall": _Var(False)},
        jobs_var=_Var("auto"),
    )
    namespace = SimpleNamespace(**panel, _ignore_dependency_states=lambda: True)
    request = ExplorerIntegrationMixin._snapshot_explorer_request(namespace)  # type: ignore[arg-type]
    assert request.enable_patterns == "reduction,doall"
    assert request.jobs == "auto"
    assert request.ignore_dependency_states is True
