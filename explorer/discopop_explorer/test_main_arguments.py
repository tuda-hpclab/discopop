# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The command line of the explorer: the defaults of the options for the pragmas of the do-all patterns."""

from pathlib import Path

import pytest

from discopop_explorer.__main__ import parse_args


@pytest.fixture  # type: ignore[misc]
def dot_discopop(tmp_path: Path) -> Path:
    """A .discopop directory with the files the explorer checks for (empty: the arguments are only parsed)."""
    (tmp_path / "profiler").mkdir()
    for name in ("Data.xml", "dynamic_dependencies.txt", "loop_counter_output.txt", "reduction.txt"):
        (tmp_path / "profiler" / name).write_text("")
    (tmp_path / "FileMapping.txt").write_text("")
    return tmp_path


def test_default_none_is_on_by_default(dot_discopop: Path) -> None:
    assert parse_args(["--path", str(dot_discopop)]).doall_default_none is True


def test_default_none_can_be_switched_off(dot_discopop: Path) -> None:
    assert parse_args(["--path", str(dot_discopop), "--no-doall-default-none"]).doall_default_none is False


def test_default_none_can_still_be_requested_explicitly(dot_discopop: Path) -> None:
    assert parse_args(["--path", str(dot_discopop), "--doall-default-none"]).doall_default_none is True
