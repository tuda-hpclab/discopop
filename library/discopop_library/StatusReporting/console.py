# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unified console status reporting: colored stage banners with spinners, progress bars,
and log-backed success/warning/error messages, all sharing the same look and feel.

`stage(...)` is the single entry point for announcing a step of work, whether it is a
top-level pipeline phase or one of many sequential sub-steps of a larger construction
process. It shows an animated spinner for the duration of the `with` block, so every
currently-running step has a visible indicator even if it has no countable inner loop.
`progress(...)` is used for the inner loops themselves. Because both are backed by `tqdm`,
progress bars started inside a `stage(...)` block are automatically positioned below its
spinner line, so the step header keeps animating while its progress bar(s) run underneath.

Stages nest (the pipeline opens a stage per phase, which opens a stage per sub-step), so
several spinners can be visible at once. All of them are animated by a *single* renderer
thread, and every write to the console goes through `_RENDER_LOCK`: concurrent writers would
interleave their cursor-positioning escape sequences and produce garbled output. For the
same reason the cursor is hidden while any spinner is alive - it would otherwise be dragged
along every redraw and flicker across the occupied lines.
"""

import atexit
import logging
import os
import sys
import threading
import time
from types import TracebackType
from typing import IO, Any, Iterable, List, Optional, Type, TypeVar

from termcolor import colored
from tqdm import tqdm  # type: ignore

logger = logging.getLogger("Explorer")

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL_SECONDS = 0.1

_CURSOR_HIDE = "\x1b[?25l"
_CURSOR_SHOW = "\x1b[?25h"

# Serializes every console write issued by this module, so that the renderer thread and the
# thread(s) opening/closing spinners never interleave partial escape sequences.
_RENDER_LOCK = threading.RLock()

# Spinners currently being animated, outermost first. Guarded by _RENDER_LOCK.
_active_spinners: List["Spinner"] = []
_renderer: Optional[threading.Thread] = None
_renderer_stop: Optional[threading.Event] = None
_frame_index = 0
# stream the cursor has been hidden on, so it can be restored on exactly that stream
_cursor_hidden_on: Optional[IO[str]] = None

T = TypeVar("T")


def supports_redrawing(stream: IO[str]) -> bool:
    """Check whether previously written lines of the given stream can be overwritten, i.e.
    whether it is an interactive console rather than a file, a pipe, or a dumb terminal."""
    try:
        if not stream.isatty():
            return False
    except Exception:
        # closed or replaced streams (e.g. when embedded into another application)
        return False
    return os.environ.get("TERM", "") != "dumb"


def _write_raw(stream: IO[str], text: str) -> None:
    """Write a control sequence directly, bypassing tqdm. Callers must hold _RENDER_LOCK."""
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        # closed or replaced streams must not break the reported computation
        pass


def _hide_cursor(stream: IO[str]) -> None:
    """Callers must hold _RENDER_LOCK."""
    global _cursor_hidden_on
    if _cursor_hidden_on is not None:
        return
    _cursor_hidden_on = stream
    _write_raw(stream, _CURSOR_HIDE)


def _show_cursor() -> None:
    """Callers must hold _RENDER_LOCK."""
    global _cursor_hidden_on
    if _cursor_hidden_on is None:
        return
    stream, _cursor_hidden_on = _cursor_hidden_on, None
    _write_raw(stream, _CURSOR_SHOW)


@atexit.register
def _restore_cursor_at_exit() -> None:
    """Safety net: a crash or a hard exit while a spinner is alive must not leave the
    user's terminal without a cursor."""
    with _RENDER_LOCK:
        _show_cursor()


def _render_loop(stop_event: threading.Event) -> None:
    """Advance and redraw every active spinner. Runs in the single renderer thread, so all
    spinner lines are rewritten sequentially instead of by one competing thread each."""
    global _frame_index
    # wait first: the spinners draw their initial frame themselves when they are opened
    while not stop_event.wait(_SPINNER_INTERVAL_SECONDS):
        with _RENDER_LOCK:
            _frame_index += 1
            for spinner in _active_spinners:
                spinner._draw(_frame_index)


def _register(spinner: "Spinner") -> None:
    global _renderer, _renderer_stop
    with _RENDER_LOCK:
        _hide_cursor(spinner.stream)
        _active_spinners.append(spinner)
        if _renderer is None:
            _renderer_stop = threading.Event()
            _renderer = threading.Thread(target=_render_loop, args=(_renderer_stop,), daemon=True)
            _renderer.start()


def _deregister(spinner: "Spinner") -> None:
    """Stop animating the given spinner, shutting the renderer down if it was the last one.
    The cursor stays hidden - it is restored by _restore_cursor_if_idle, once the caller is
    done writing the step's final line."""
    global _renderer, _renderer_stop
    with _RENDER_LOCK:
        if spinner in _active_spinners:
            _active_spinners.remove(spinner)
        if len(_active_spinners) > 0:
            return
        stop_event, thread = _renderer_stop, _renderer
        _renderer, _renderer_stop = None, None

    # the renderer acquires _RENDER_LOCK itself, so it must be joined without holding it
    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=1.0)


def _restore_cursor_if_idle() -> None:
    with _RENDER_LOCK:
        if len(_active_spinners) == 0:
            _show_cursor()


class Spinner:
    """Animated single-line indicator for the duration of a running step. Redraws in place
    on interactive consoles; on non-interactive streams (files, pipes, CI logs) it instead
    prints a single start line and a single done/fail line, since redrawing is not possible.

    The animated line is transient (`leave=False`): its tqdm position is handed back when the
    step ends, so a following bar or spinner reuses it instead of overwriting a line meant to
    stay. The permanent one-line summary is emitted via `tqdm.write`, which scrolls it above
    whatever bars are still live."""

    def __init__(self, label: str, stream: Optional[IO[str]] = None) -> None:
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        self._redraw = supports_redrawing(self.stream)
        self._line: Optional[tqdm] = None
        self._start_time = 0.0

    def __enter__(self) -> "Spinner":
        self._start_time = time.monotonic()
        if self._redraw:
            with _RENDER_LOCK:
                self._line = tqdm(total=0, bar_format="{desc}", leave=False, dynamic_ncols=True, file=self.stream)
                self._draw(_frame_index)
            _register(self)
        else:
            with _RENDER_LOCK:
                tqdm.write(colored(self.label + "...", "cyan", attrs=["bold"]), file=self.stream)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        final_line = self._render_final(time.monotonic() - self._start_time, failed=exc_type is not None)
        if self._redraw:
            # deregister first, so the renderer can no longer touch the line being closed
            _deregister(self)
        with _RENDER_LOCK:
            if self._line is not None:
                self._line.close()
                self._line = None
            tqdm.write(final_line, file=self.stream)
        if self._redraw:
            # last, so that the cursor stays hidden for the writes above as well
            _restore_cursor_if_idle()

    def _draw(self, frame_index: int) -> None:
        """Rewrite the animated line. Callers must hold _RENDER_LOCK."""
        if self._line is None:
            return
        frame = _SPINNER_FRAMES[frame_index % len(_SPINNER_FRAMES)]
        self._line.set_description_str(colored(f"{frame} {self.label}...", "cyan", attrs=["bold"]), refresh=True)

    def _render_final(self, elapsed: float, failed: bool) -> str:
        if failed:
            return colored(f"✗ {self.label} failed after {elapsed:.1f}s", "red", attrs=["bold"])
        return colored(f"✓ {self.label} ({elapsed:.1f}s)", "green")


def stage(name: str, index: Optional[int] = None, total: Optional[int] = None, **kwargs: Any) -> Spinner:
    """Announce a step of work, showing an animated spinner for the duration of the
    surrounding `with` block. Use `index`/`total` for steps that are part of a known-length
    sequence, e.g. `with stage("Breaking cycles", 2, total=15):`.

    >>> with stage("Loading Hotspots"):
    ...     load_hotspots()
    """
    label = f"[{index}/{total}] {name}" if index is not None and total is not None else name
    return Spinner(label, **kwargs)


def progress(
    iterable: Optional[Iterable[T]] = None, total: Optional[int] = None, desc: str = "", **kwargs: Any
) -> tqdm:
    """Thin wrapper around `tqdm` fixing shared styling, so every progress bar in the
    codebase looks and behaves the same way. Use exactly like `tqdm(...)`."""
    kwargs.setdefault("dynamic_ncols", True)
    kwargs.setdefault("leave", False)
    with _RENDER_LOCK:
        return tqdm(iterable, total=total, desc=desc, **kwargs)


def success(msg: str) -> None:
    """Log a successful step outcome, consistently color-coded across the codebase."""
    logger.info(colored(f"✓ {msg}", "green"))


def warn(msg: str) -> None:
    """Log a warning, consistently color-coded across the codebase."""
    logger.warning(colored(f"⚠ {msg}", "yellow"))


def error(msg: str) -> None:
    """Log an error, consistently color-coded across the codebase."""
    logger.error(colored(f"✗ {msg}", "red", attrs=["bold"]))


def banner(title: str) -> None:
    """Print a consistently-framed section header for persistent, user-facing console
    output (e.g. end-of-run instructions or a suggestions overview), as opposed to
    `stage(...)`'s transient step narration."""
    line = colored("─" * max(20, len(title) + 4), "cyan")
    print(line)
    print(colored(f"  {title}", "cyan", attrs=["bold"]))
    print(line)
