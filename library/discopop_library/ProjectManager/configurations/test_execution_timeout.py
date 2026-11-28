# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""A script stopped by its timeout is recorded as such.

The limit is enforced by coreutils' ``timeout`` (exit status 124), so the script's process simply ends; the result
used to say ``timeout_expired: False`` for it.
"""

import os
from pathlib import Path

from discopop_library.ProjectManager.configurations.execution import TIMEOUT_EXIT_CODE, _run_once


def _script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "script.sh"
    path.write_text("#!/bin/bash\n" + body + "\n")
    return str(path)


def test_a_script_stopped_by_the_timeout_is_recorded_as_timed_out(tmp_path: Path) -> None:
    script = _script(tmp_path, "echo started; sleep 30")

    outcome = _run_once(script, str(tmp_path), dict(os.environ), 1, 0.5, None, None)

    assert outcome.returncode == TIMEOUT_EXIT_CODE
    assert outcome.timeout_expired is True
    # what it printed before tells how far it got
    assert outcome.stdout == "started\n"


def test_a_script_within_its_timeout_is_not(tmp_path: Path) -> None:
    outcome = _run_once(_script(tmp_path, "exit 3"), str(tmp_path), dict(os.environ), 1, 30.0, None, None)

    assert outcome.returncode == 3
    assert outcome.timeout_expired is False


def test_exit_status_124_without_a_timeout_is_an_ordinary_failure(tmp_path: Path) -> None:
    outcome = _run_once(_script(tmp_path, "exit 124"), str(tmp_path), dict(os.environ), 1, None, None, None)

    assert outcome.timeout_expired is False
