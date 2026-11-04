# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path

from discopop_library.ProjectManager.services import patch_repair_view as view


def test_completion_results_have_a_file_of_their_own(tmp_path: Path) -> None:
    directory = tmp_path / "patch_repair"
    directory.mkdir()
    (directory / "results.json").write_text(json.dumps({"suggestions": {"1": {"status": "repaired"}}}))
    (directory / "completion_results.json").write_text(json.dumps({"suggestions": {"2": {"status": "completed"}}}))
    assert view.load_results(str(tmp_path)) == {"1": {"status": "repaired"}}
    assert view.load_results(str(tmp_path), view.MODE_COMPLETE) == {"2": {"status": "completed"}}


def test_a_completed_suggestion_is_a_success_row() -> None:
    (row,) = view.result_rows({"2": {"status": "completed", "files": [1], "changed_files": [1]}})
    assert row.status_label == "Completed"
    assert row.tone == view.TONE_OK
    assert view.preferred_row([row], None) == "2"


def test_completion_progress_texts() -> None:
    start = {"event": "start", "mode": "complete", "candidate_count": 3}
    assert view.progress_summary(start) == [("Completing 3 suggestion(s)...", view.TONE_BUSY)]
    none = {"event": "start", "mode": "complete", "candidate_count": 0}
    assert view.progress_summary(none)[0][0].startswith("No suggestion with a placeholder")
    done = {"event": "done", "mode": "complete", "repaired": 2, "failed": 0, "considered": 2}
    assert view.progress_summary(done) == [("2 completed, 0 not completed, 2 considered.", view.TONE_OK)]


def test_repair_progress_texts_are_unchanged() -> None:
    done = {"event": "done", "repaired": 1, "failed": 1, "considered": 4}
    assert view.progress_summary(done)[0][0] == "1 repaired, 1 not repaired, 4 considered."
    assert view.progress_summary({"event": "start", "mode": "repair", "candidate_count": 3}) == []
