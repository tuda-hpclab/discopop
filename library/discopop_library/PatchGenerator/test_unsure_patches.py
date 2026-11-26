# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
from pathlib import Path

from discopop_library.PatchGenerator.patch_generator import unsure_patterns_by_type


def test_unsure_suggestions_are_read_as_patterns_without_their_blockers(tmp_path: Path) -> None:
    path = tmp_path / "unsure_suggestions.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "suggestions": [
                    {
                        "pattern_id": 7,
                        "type": "do_all",
                        "pragma": "#pragma omp parallel for",
                        "blockers": [{"type": "RAW"}],
                    },
                    {"pattern_id": 8, "type": "reduction", "blockers": []},
                ],
            }
        )
    )
    by_type = unsure_patterns_by_type(str(path))
    assert sorted(by_type) == ["do_all", "reduction"]
    assert [json.loads(p) for p in by_type["do_all"]] == [{"pattern_id": 7, "pragma": "#pragma omp parallel for"}]
    assert [json.loads(p) for p in by_type["reduction"]] == [{"pattern_id": 8}]


def test_no_unsure_suggestions(tmp_path: Path) -> None:
    path = tmp_path / "unsure_suggestions.json"
    path.write_text(json.dumps({"format_version": 1, "suggestions": []}))
    assert unsure_patterns_by_type(str(path)) == {}
