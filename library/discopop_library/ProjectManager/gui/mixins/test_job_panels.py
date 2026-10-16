# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Drives the job based panels (patch repair, autotuning, pattern detection) headlessly.

The widgets are mocks, ``after`` is pumped by the test, and the command is replaced by a small Python program; what is
checked is the wiring: output and progress events reach the handlers on the pumping thread, the completion callback
gets the right ``error`` flag, and stopping cancels the job.
"""

import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, List
from unittest import mock

from discopop_library.ProjectManager.gui.mixins import autotuning_panel, explorer_integration, patch_repair_panel
from discopop_library.ProjectManager.gui.mixins.autotuning_panel import AutotuningPanelMixin
from discopop_library.ProjectManager.gui.mixins.explorer_integration import ExplorerIntegrationMixin
from discopop_library.ProjectManager.gui.mixins.patch_repair_panel import PatchRepairPanelMixin
from discopop_library.ProjectManager.services.requests import AutotunerRequest, ExplorerRequest, PatchRepairRequest


def _program(code: str) -> List[str]:
    return [sys.executable, "-u", "-c", code]


def _pump(app: Any, until: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while not until():
        assert time.time() < deadline, "timed out"
        pending, app.queued = app.queued, []  # callbacks that re-schedule themselves run once per round
        for callback in pending:
            callback()
        time.sleep(0.01)


class _PanelFake:
    """Mixin methods of one panel on top of mock widgets; ``after`` only queues."""

    def after(self, _delay: int, func: Callable[[], None]) -> None:
        self.queued.append(func)  # type: ignore[attr-defined]


def _setup(app: Any, tmp_path: Path, **extra: Any) -> None:
    app.queued = []
    app.arguments = mock.MagicMock(dot_dp=str(tmp_path))
    app.status_label = mock.MagicMock()
    app.current_config = "tiny"
    for name, value in extra.items():
        setattr(app, name, value)


# ---- patch repair --------------------------------------------------------------------------------------------


class _PatchRepairApp(_PanelFake, PatchRepairPanelMixin):
    pass


def _patch_repair_app(tmp_path: Path, command: List[str]) -> Any:
    app = _PatchRepairApp()
    _setup(
        app,
        tmp_path,
        patch_repair_running=False,
        patch_repair_run_button=mock.MagicMock(),
        patch_repair_stop_button=mock.MagicMock(),
        patch_repair_output_text=mock.MagicMock(),
        _patch_repair_records={},
        _refresh_patch_repair_table=mock.MagicMock(),
        _on_patch_repair_complete=mock.MagicMock(),
        _on_patch_repair_progress=mock.MagicMock(),
        _snapshot_patch_repair_request=lambda: PatchRepairRequest(
            "tiny", "yes", 1, 1, 10, "INFO", "claude", "", False, None
        ),
    )
    return app


def test_patch_repair_success_and_progress(tmp_path: Path) -> None:
    app = _patch_repair_app(tmp_path, [])
    code = 'print(\'hello\'); print(\'@@PR_PROGRESS {"event": "done", "repaired": 1}\')'
    with mock.patch.object(patch_repair_panel, "patch_repair_command", lambda *_a, **_k: _program(code)):
        app._run_patch_repair()
        _pump(app, lambda: app._on_patch_repair_complete.called)
    app._on_patch_repair_complete.assert_called_once_with()
    app._on_patch_repair_progress.assert_called_once()
    assert app._on_patch_repair_progress.call_args.args[0]["repaired"] == 1
    inserted = "".join(call.args[1] for call in app.patch_repair_output_text.insert.call_args_list)
    assert "Starting patch repair..." in inserted and "hello" in inserted and "Patch repair completed." in inserted
    assert "@@PR_PROGRESS" not in inserted
    assert app._patch_repair_job is None


def test_patch_repair_failure(tmp_path: Path) -> None:
    app = _patch_repair_app(tmp_path, [])
    with mock.patch.object(
        patch_repair_panel, "patch_repair_command", lambda *_a, **_k: _program("raise SystemExit(4)")
    ):
        app._run_patch_repair()
        _pump(app, lambda: app._on_patch_repair_complete.called)
    app._on_patch_repair_complete.assert_called_once_with(error=True)
    inserted = "".join(call.args[1] for call in app.patch_repair_output_text.insert.call_args_list)
    assert "Patch repair exited with return code 4" in inserted


def test_patch_repair_stop(tmp_path: Path) -> None:
    app = _patch_repair_app(tmp_path, [])
    ready = threading.Event()
    code = "import time; print('ready', flush=True); time.sleep(60)"
    original_append = app._on_patch_repair_job_event

    def watching(event: Any, output_callback: Callable[[str], None]) -> None:
        if getattr(event, "line", None) == "ready":
            ready.set()
        original_append(event, output_callback)

    app._on_patch_repair_job_event = watching
    with mock.patch.object(patch_repair_panel, "patch_repair_command", lambda *_a, **_k: _program(code)):
        app._run_patch_repair()
        _pump(app, ready.is_set)
        app._stop_patch_repair()
        _pump(app, lambda: app._on_patch_repair_complete.called)
    assert app._on_patch_repair_complete.call_args.kwargs == {"error": True}  # SIGINT ends the program abnormally


# ---- autotuning ----------------------------------------------------------------------------------------------


class _AutotuningApp(_PanelFake, AutotuningPanelMixin):
    pass


def test_autotuning_success_and_progress(tmp_path: Path) -> None:
    app: Any = _AutotuningApp()
    request = AutotunerRequest("tiny", "yes", "auto", 1, "bad value", "0", "INFO", "search", (), None)
    _setup(
        app,
        tmp_path,
        autotuning_running=False,
        autotuning_run_button=mock.MagicMock(),
        autotuning_stop_button=mock.MagicMock(),
        autotuning_output_text=mock.MagicMock(),
        _redraw_autotuning_plot=mock.MagicMock(),
        _update_autotuning_tiles=mock.MagicMock(),
        _on_autotuning_complete=mock.MagicMock(),
        _on_autotuning_progress=mock.MagicMock(),
        _snapshot_autotuner_request=lambda: request,
    )
    code = "print('working'); print('@@AT_PROGRESS {\"event\": \"start\"}')"
    with mock.patch.object(autotuning_panel, "autotuner_command", lambda *_a, **_k: _program(code)):
        app._run_autotuning()
        _pump(app, lambda: app._on_autotuning_complete.called)
    app._on_autotuning_complete.assert_called_once_with()
    app._on_autotuning_progress.assert_called_once_with({"event": "start"})
    inserted = "".join(call.args[1] for call in app.autotuning_output_text.insert.call_args_list)
    assert "Ignoring the repetition count: bad value" in inserted
    assert "working" in inserted and "Autotuning completed." in inserted


# ---- pattern detection ---------------------------------------------------------------------------------------


class _ExplorerApp(_PanelFake, ExplorerIntegrationMixin):
    pass


def _explorer_app(tmp_path: Path, missing: List[str]) -> Any:
    app = _ExplorerApp()
    _setup(
        app,
        tmp_path,
        explorer_running=False,
        _explorer_stopped=False,
        explorer_run_button=mock.MagicMock(),
        explorer_stop_button=mock.MagicMock(),
        explorer_output_text=mock.MagicMock(),
        no_suggestions_label=None,
        visualize_var=None,
        _check_explorer_prerequisites=lambda: True,
        _on_pattern_detection_complete=mock.MagicMock(),
        _get_missing_required_explorer_files=lambda _path: missing,
        _snapshot_explorer_request=lambda: ExplorerRequest("doall", "auto", False),
    )
    return app


def test_pattern_detection_success(tmp_path: Path) -> None:
    app = _explorer_app(tmp_path, [])
    with mock.patch.object(explorer_integration, "explorer_command", lambda *_a, **_k: _program("print('found')")):
        app._run_pattern_detection()
        _pump(app, lambda: app._on_pattern_detection_complete.called)
    app._on_pattern_detection_complete.assert_called_once_with()
    inserted = "".join(call.args[1] for call in app.explorer_output_text.insert.call_args_list)
    assert "found" in inserted and "Pattern detection completed." in inserted


def test_pattern_detection_reports_missing_profiling_data(tmp_path: Path) -> None:
    app = _explorer_app(tmp_path, ["/p/Data.xml"])
    app._run_pattern_detection()
    # reported at once, no job involved
    app._on_pattern_detection_complete.assert_called_once_with(error=True)
    inserted = "".join(call.args[1] for call in app.explorer_output_text.insert.call_args_list)
    assert "/p/Data.xml" in inserted and "Missing required profiling data files" in inserted
