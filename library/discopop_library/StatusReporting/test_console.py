# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the unified console status reporting."""

import io
from typing import Any

import pytest

from discopop_library.StatusReporting import console
from discopop_library.StatusReporting.console import (
    _CURSOR_HIDE,
    _CURSOR_SHOW,
    Spinner,
    progress,
    stage,
    supports_redrawing,
)


class _FakeConsole(io.StringIO):
    """Stream which claims to be an interactive console."""

    def isatty(self) -> bool:
        return True


def test_redrawing_detection() -> None:
    assert not supports_redrawing(io.StringIO())
    assert supports_redrawing(_FakeConsole())


def test_redrawing_detection_handles_dumb_terminals(monkeypatch: Any) -> None:
    monkeypatch.setenv("TERM", "dumb")
    assert not supports_redrawing(_FakeConsole())


def test_stage_label_includes_step_counter_when_given() -> None:
    with stage("Breaking cycles", 2, total=15) as spinner:
        assert spinner.label == "[2/15] Breaking cycles"


def test_stage_label_omits_step_counter_when_not_given() -> None:
    with stage("Loading Hotspots") as spinner:
        assert spinner.label == "Loading Hotspots"


def test_stage_reports_failure_without_swallowing_the_exception() -> None:
    with pytest.raises(ValueError):
        with stage("Some step"):
            raise ValueError("boom")


def test_progress_wraps_a_plain_iterable() -> None:
    assert list(progress([1, 2, 3], desc="counting")) == [1, 2, 3]


# --- animation on interactive consoles -------------------------------------------
# Concurrent writers interleave their cursor-positioning escape sequences, so the amount of
# writing threads and the state of the cursor are part of the contract, not an implementation
# detail: getting them wrong shows up as flickering and garbled output.


def test_cursor_is_hidden_while_a_spinner_is_active_and_restored_afterwards() -> None:
    stream = _FakeConsole()
    with Spinner("Some step", stream=stream):
        assert _CURSOR_HIDE in stream.getvalue()
        assert _CURSOR_SHOW not in stream.getvalue()
    assert stream.getvalue().endswith(_CURSOR_SHOW)


def test_cursor_is_restored_even_if_the_step_fails() -> None:
    stream = _FakeConsole()
    with pytest.raises(ValueError):
        with Spinner("Some step", stream=stream):
            raise ValueError("boom")
    assert stream.getvalue().endswith(_CURSOR_SHOW)


def test_nested_spinners_are_animated_by_a_single_shared_renderer_thread() -> None:
    stream = _FakeConsole()
    assert console._renderer is None
    with Spinner("Outer", stream=stream):
        outer_renderer = console._renderer
        assert outer_renderer is not None
        with Spinner("Inner", stream=stream):
            # one renderer for both, rather than one competing thread per spinner
            assert console._renderer is outer_renderer
            assert len(console._active_spinners) == 2
        assert console._renderer is outer_renderer
        assert len(console._active_spinners) == 1
    # the renderer is shut down again once the last spinner is done
    assert console._renderer is None
    assert len(console._active_spinners) == 0


def test_nested_spinners_keep_the_cursor_hidden_until_the_outermost_one_ends() -> None:
    stream = _FakeConsole()
    with Spinner("Outer", stream=stream):
        with Spinner("Inner", stream=stream):
            pass
        # the inner step ending must not bring the cursor back while the outer one animates
        assert _CURSOR_SHOW not in stream.getvalue()
    assert _CURSOR_SHOW in stream.getvalue()


def test_spinner_emits_a_permanent_summary_line() -> None:
    stream = _FakeConsole()
    with Spinner("Some step", stream=stream):
        pass
    # the animated line is transient, the summary has to survive
    assert "✓ Some step" in stream.getvalue()
