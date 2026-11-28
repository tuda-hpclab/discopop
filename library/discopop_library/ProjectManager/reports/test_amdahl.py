# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import matplotlib.pyplot as plt
import pytest

from discopop_library.Amdahl import regions
from discopop_library.Amdahl.model import amdahl_ceiling, amdahl_limit
from discopop_library.ProjectManager.plots.data import ExecutionRecord
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.reports.amdahl import MISSING_EXTENTS_TEXT, best_rows, generate_amdahl_report


def _rec(config: str, speedup: float, threads: int, p: float, mode: str = "par") -> ExecutionRecord:
    return ExecutionRecord(
        config=config,
        script="execute.sh",
        mode=mode,
        label="",
        thread_count=threads,
        applied_suggestions=[5],
        time=1.0,
        code=0,
        timeout=False,
        valid=True,
        speedup=speedup,
        efficiency=speedup / threads,
        parallel_fraction=p,
        amdahl_ceiling=amdahl_ceiling(p, threads),
        amdahl_limit=amdahl_limit(p),
    )


def test_best_rows_picks_best_par_record_per_config() -> None:
    rows = best_rows(
        [_rec("a", 1.5, 4, 0.9), _rec("a", 3.0, 4, 0.9), _rec("b", 2.0, 2, 1.0), _rec("c", 1.0, 1, 0.0, "seq")]
    )
    assert [r[0] for r in rows] == ["a", "b"]
    assert rows[0][3] == "3.00x" and rows[0][4] == "3.08x" and rows[0][5] == "10.00x" and rows[0][6] == "97%"
    assert rows[1][5] == "unbounded"


def _fignums() -> Any:
    return plt.get_fignums()  # type: ignore[attr-defined]


def _texts_of_new_figures(before: Any) -> list:  # type: ignore[type-arg]
    return [t.get_text() for n in _fignums() if n not in before for t in cast(Any, plt.figure(n)).texts]


@pytest.mark.parametrize("with_dump", [True, False])
def test_missing_extents_get_a_page_instead_of_a_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_dump: bool
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "execution_results.json").write_text(json.dumps({}))
    if with_dump:
        (tmp_path / "explorer").mkdir()
        (tmp_path / "explorer" / regions.DUMP_NAME).write_text("dump of an older explorer")

    def no_decode(_dot_dp: str) -> Any:
        raise AssertionError("decoded in the report")

    monkeypatch.setattr(regions, "extract_suggestion_extents", no_decode)
    arguments = cast(ProjectManagerArguments, SimpleNamespace(project_dir=str(project_dir)))
    before = _fignums()
    try:
        generate_amdahl_report(arguments, "now")
        texts = _texts_of_new_figures(before)
    finally:
        for n in _fignums():
            if n not in before:
                plt.close(n)
    if with_dump:
        assert len(texts) == 1 and texts[0].replace("\n", " ") == MISSING_EXTENTS_TEXT
    else:
        assert texts == []
