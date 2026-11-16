# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the storage the builds and runs of a project occupy."""

import os
from pathlib import Path

from discopop_library.ProjectManager.services.build_overview import storage_of


def test_the_storage_is_the_size_of_all_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one").write_bytes(b"x" * 1000)
    (tmp_path / "two").write_bytes(b"x" * 24)
    assert storage_of(str(tmp_path)) == 1024


def test_a_file_linked_into_several_runs_counts_once(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "Data.xml").write_bytes(b"x" * 1000)
    for run in ("run1", "run2"):
        (tmp_path / run).mkdir()
        os.link(build / "Data.xml", tmp_path / run / "Data.xml")
    assert storage_of(str(tmp_path)) == 1000


def test_a_missing_directory_occupies_nothing(tmp_path: Path) -> None:
    assert storage_of(str(tmp_path / "missing")) == 0
