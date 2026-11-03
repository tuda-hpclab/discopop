# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The hotspot analysis is recorded once Hotspots.json exists."""

import json
from pathlib import Path

from discopop_hotspot_analyzer.hotspot_analyzer import _record_analysis
from discopop_library.AnalysisRecord import RECORD_FILENAME, record_hotspot_run


def test_analysis_records_the_detection_configurations(tmp_path: Path) -> None:
    dot = tmp_path / ".discopop"
    (dot / "hotspot_detection" / "private").mkdir(parents=True)
    (dot / "hotspot_detection" / "private" / "hotspot_result_0.txt").write_text("1 0.5\n")
    (tmp_path / "main.cpp").write_text("int main() {}\n")
    record_hotspot_run(str(dot), "b", "compile.sh")
    record_hotspot_run(str(dot), "a", "compile.sh")

    _record_analysis(str(dot))

    with open(dot / RECORD_FILENAME) as f:
        steps = json.load(f)["steps"]
    assert steps["hotspot_analysis"]["params"] == {"configs": ["a", "b"]}
    assert steps["hotspot_analysis"]["inputs"] == {"hotspot_detection": steps["hotspot_detection"]["run_id"]}
