# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from typing import Any

import pytest

TESTDATA = Path(__file__).parent / "testdata"


@pytest.fixture
def fft_task_entries() -> list[dict[str, Any]]:
    """The task entries of patterns.json from a run of BOTS fft (26 groups, 52 tasks), reduced to what is read."""
    entries: list[dict[str, Any]] = json.loads((TESTDATA / "fft_task_groups.json").read_text())
    return entries
