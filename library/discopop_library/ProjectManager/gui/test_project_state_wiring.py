# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which panel update follows which event, in which order (the wiring of ConfigManagerApp, without a display)."""

from typing import Any, List
from unittest import mock

from discopop_library.ProjectManager.gui.ConfigManagerApp import ConfigManagerApp
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)

UPDATES = (
    "_update_autotuning_config_display",
    "_refresh_autotuning_suggestions_display",
    "_refresh_suggestion_selection_display",
    "_update_hotspot_config_display",
    "_update_patch_repair_ui",
    "_update_report_display",
    "_update_autotuning_ui",
)


def _wired() -> Any:
    calls: List[str] = []
    app = mock.MagicMock()
    app.project_state = ProjectState()
    for name in UPDATES:
        getattr(app, name).side_effect = lambda name=name: calls.append(name)
    ConfigManagerApp._subscribe_panels_to_project_state(app)
    return app, calls


def test_a_selected_configuration_reaches_the_tabs_in_a_fixed_order() -> None:
    app, calls = _wired()
    app.project_state.publish(ConfigChanged("tiny"))
    assert calls == [
        "_update_autotuning_config_display",
        "_refresh_autotuning_suggestions_display",
        "_refresh_suggestion_selection_display",
        "_update_hotspot_config_display",
        "_update_patch_repair_ui",
    ]


def test_the_other_events() -> None:
    app, calls = _wired()
    state = app.project_state
    state.publish(ResultsChanged())
    assert calls == ["_update_report_display"]
    calls.clear()
    state.publish(PatternsChanged())
    assert calls == ["_update_autotuning_ui", "_update_patch_repair_ui"]
    calls.clear()
    state.publish(HotspotsChanged())
    assert calls == ["_update_autotuning_ui"]
    calls.clear()
    state.publish(AutotuningChanged())
    assert calls == ["_refresh_autotuning_suggestions_display"]
    calls.clear()
    state.publish(AutotuningFinished())
    assert calls == [
        "_refresh_autotuning_suggestions_display",
        "_refresh_suggestion_selection_display",
        "_update_report_display",
    ]


def test_the_selected_configuration_lives_in_the_project_state() -> None:
    app = mock.MagicMock()
    app.project_state = ProjectState()
    ConfigManagerApp.current_config.fset(app, "tiny")  # type: ignore[attr-defined]
    assert app.project_state.current_config == "tiny"
    assert ConfigManagerApp.current_config.fget(app) == "tiny"  # type: ignore[attr-defined]
