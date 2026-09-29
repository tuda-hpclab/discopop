# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Progress bars for the autotuner's search loops.

The bars are suppressed on non-interactive streams. Redrawing a bar in place is
impossible there anyway (every refresh would be appended as another line), and it
actively breaks the structured progress channel: a bar redraw ends in a carriage
return without a newline, so the ``@@AT_PROGRESS`` line emitted right afterwards no
longer starts at a line boundary. A consumer reading the autotuner's merged
stdout/stderr stream line by line -- the Project Manager GUI's live plot -- would
then see the event glued behind the bar text.
"""

import sys
from typing import Any, Iterable, Optional, TypeVar

from discopop_library.StatusReporting.console import progress, supports_redrawing

T = TypeVar("T")


def search_bar(iterable: Optional[Iterable[T]] = None, total: Optional[int] = None, **kwargs: Any) -> Any:
    """``tqdm``-compatible progress bar, disabled unless stderr is an interactive console."""
    kwargs.setdefault("disable", not supports_redrawing(sys.stderr))
    return progress(iterable, total=total, **kwargs)
