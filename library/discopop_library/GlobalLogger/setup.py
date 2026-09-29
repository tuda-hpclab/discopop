# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
from typing import TYPE_CHECKING, TextIO

from termcolor import colored
from tqdm import tqdm  # type: ignore

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments
from discopop_library.StatusReporting.console import _RENDER_LOCK

_LEVEL_COLORS = {
    logging.DEBUG: "dark_grey",
    logging.WARNING: "yellow",
    logging.ERROR: "red",
    logging.CRITICAL: "red",
}


class _ColoredFormatter(logging.Formatter):
    """Colorizes the level name and message consistently with the rest of the console
    output, based on the record's severity. Colors are stripped automatically by
    `termcolor` when the output stream is not a terminal (e.g. redirected to a file)."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        color = _LEVEL_COLORS.get(record.levelno)
        return colored(formatted, color) if color is not None else formatted


# `logging.StreamHandler` is generic for type checkers, but only subscriptable at runtime
# from Python 3.11 on. Subscript it for the type checker only, so older interpreters work.
if TYPE_CHECKING:
    _StreamHandler = logging.StreamHandler[TextIO]
else:
    _StreamHandler = logging.StreamHandler


class _TqdmLoggingHandler(_StreamHandler):
    """Writes log records via `tqdm.write` instead of directly to the stream, so they do not
    corrupt an active `tqdm` progress bar or spinner. The write is serialized against the
    spinner renderer thread on the same lock it uses (see StatusReporting.console), since
    otherwise a record emitted mid-redraw interleaves with the spinner's escape sequences."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with _RENDER_LOCK:
                tqdm.write(self.format(record), file=self.stream)
        except Exception:
            self.handleError(record)


def setup_logger(arguments: GeneralArguments) -> None:
    if arguments.write_log:
        logging.basicConfig(filename="log.txt", level=arguments.log_level)
    else:
        handler = _TqdmLoggingHandler()
        handler.setFormatter(_ColoredFormatter("[DP][%(name)s] %(levelname)s: %(message)s"))
        logging.basicConfig(level=arguments.log_level, handlers=[handler])

    logging.getLogger("filelock").setLevel(logging.WARNING)
