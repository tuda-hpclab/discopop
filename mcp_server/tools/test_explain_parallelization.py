# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from discopop_explorer.classes.patterns.PatternDecisions import (
    LOOP_CARRIED_DEPENDENCY,
    TOO_FEW_ITERATIONS,
    CodeRegion,
    DecisionReason,
    DependencyRecord,
    PatternDecisionLog,
)
from mcp_server.tools import explain_parallelization
from mcp_server.tools.explain_parallelization import MAX_REASONS_PER_REGION
from mcp_server.tools.helpers import ToolContext

DETECTOR = "doall_reduction"
TYPES = ("doall", "reduction")


class _Pattern:
    def __init__(self, node_id: str, pattern_id: int) -> None:
        self.node_id = node_id
        self.pattern_id = pattern_id


class DoAllInfo(_Pattern):
    pass


def _carried(variable: str, line: int = 11) -> DecisionReason:
    return DecisionReason(
        kind=LOOP_CARRIED_DEPENDENCY,
        message="m",
        dependency=DependencyRecord(
            type="RAW",
            variable=variable,
            memory_region="7",
            source_line=f"1:{line}",
            sink_line=f"1:{line}",
            origin="dynamic",
            element_access=True,
        ),
    )


class TestExplainParallelization(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.dot_discopop = Path(self.project_path) / ".discopop"
        (self.dot_discopop / "explorer").mkdir(parents=True)
        (self.dot_discopop / "FileMapping.txt").write_text(f"1\t{self.source}\n")
        self.ctx = ToolContext(debug=False)

        log = PatternDecisionLog()
        log.ran(DETECTOR, TYPES)
        log.consider(DETECTOR, TYPES, CodeRegion("1:5", 1, 6, 8, "loop"))
        log.reject(DETECTOR, TYPES, CodeRegion("1:11", 1, 10, 30, "loop"), _carried("a"))
        log.reject(DETECTOR, TYPES, CodeRegion("1:13", 1, 12, 14, "loop"), DecisionReason(TOO_FEW_ITERATIONS, "m"))
        log.finalize(DETECTOR, [cast(Any, DoAllInfo("1:5", 3))])
        self.log = log
        self.__save()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __save(self) -> None:
        self.log.save(str(self.dot_discopop / "explorer" / "pattern_decisions.json"))

    def __handle(self, **arguments: Any) -> Any:
        arguments = {"project_path": self.project_path, "file_path": str(self.source), **arguments}
        return json.loads(explain_parallelization.handle(arguments, self.ctx)[0].text)

    def test_an_accepted_region_names_its_suggestions_as_strings(self) -> None:
        data = self.__handle(start_line=7)
        self.assertEqual(data["num_regions"], 1)
        region = data["regions"][0]
        self.assertEqual(region["outcome"], "accepted")
        self.assertEqual(region["suggestions"], [{"type": "doall", "pattern_id": "3"}])
        self.assertEqual((region["file"], region["start_line"], region["end_line"]), (str(self.source), 6, 8))
        self.assertNotIn("reasons", region)

    def test_a_rejected_region_names_the_dependency_with_resolved_lines(self) -> None:
        data = self.__handle(start_line=20)
        region = data["regions"][0]
        self.assertEqual(region["outcome"], "rejected")
        dependency = region["reasons"][0]["dependency"]
        self.assertEqual(dependency["variable"], "a")
        self.assertTrue(dependency["element_access"])
        self.assertEqual(dependency["source"], {"file": str(self.source), "line": 11})
        self.assertNotIn("memory_region", dependency)
        self.assertIn("get_data_dependencies", data["next_step"])
        self.assertIn("start_line=10, end_line=30", data["next_step"])

    def test_reason_details_use_string_ids_and_file_paths(self) -> None:
        details = {"pattern_id": 3, "node_id": "1:5", "file_id": 1, "start_line": 6, "end_line": 8}
        self.log.reject(
            DETECTOR,
            TYPES,
            CodeRegion("1:40", 1, 40, 42, "loop"),
            DecisionReason("duplicate_pattern", "m", details=details),
        )
        self.__save()
        reason = self.__handle(start_line=41)["regions"][0]["reasons"][0]
        self.assertEqual(reason["details"]["pattern_id"], "3")
        self.assertEqual(reason["details"]["file"], str(self.source))
        self.assertNotIn("file_id", reason["details"])

    def test_nested_regions_come_innermost_first(self) -> None:
        data = self.__handle(start_line=13)
        self.assertEqual([r["start_line"] for r in data["regions"]], [12, 10])
        self.assertIn("more often", data["next_step"])
        # the dependency hint names the region the dependency prevents, not the innermost one
        self.assertIn("start_line=10, end_line=30", data["next_step"])

    def test_an_accepted_region_points_at_its_suggestions(self) -> None:
        self.assertIn("get_parallelization_patches(pattern_ids=", self.__handle(start_line=7)["next_step"])

    def test_a_range_matches_every_overlapping_region(self) -> None:
        self.assertEqual(self.__handle(start_line=1, end_line=100)["num_regions"], 3)

    def test_many_reasons_are_cut(self) -> None:
        for i in range(MAX_REASONS_PER_REGION + 5):
            self.log.reject(DETECTOR, TYPES, CodeRegion("1:11", 1, 10, 30, "loop"), _carried(f"v{i}"))
        self.log.finalize(DETECTOR, [cast(Any, DoAllInfo("1:5", 3))])
        self.__save()
        region = self.__handle(start_line=20)["regions"][0]
        self.assertEqual(len(region["reasons"]), MAX_REASONS_PER_REGION)
        self.assertEqual(region["num_reasons"], MAX_REASONS_PER_REGION + 6)

    def test_lines_outside_every_region_are_explained(self) -> None:
        data = self.__handle(start_line=40)
        self.assertEqual(data["regions"], [])
        self.assertIn("never executed", data["next_step"])

    def test_a_detection_without_any_recording_detector_says_so(self) -> None:
        self.log = PatternDecisionLog()  # a detection that ran no detector which records decisions
        self.__save()
        data = self.__handle(start_line=7)
        self.assertEqual(data["regions"], [])
        self.assertIn("ran no detector", data["next_step"])

    def test_a_file_outside_the_program_is_an_error(self) -> None:
        data = self.__handle(file_path="/elsewhere/other.cpp", start_line=1)
        self.assertEqual(data["status"], "error")

    def test_a_result_of_an_older_version_asks_for_a_new_analysis(self) -> None:
        (self.dot_discopop / "explorer" / "pattern_decisions.json").unlink()
        self.assertIn("Run gather_data first", self.__handle(start_line=7)["message"])
        (self.dot_discopop / "explorer" / "patterns.json").write_text("{}")
        self.assertIn("does not record", self.__handle(start_line=7)["message"])

    def test_suggestions_newer_than_the_explanation_are_flagged(self) -> None:
        patterns = self.dot_discopop / "explorer" / "patterns.json"
        patterns.write_text("{}")
        decisions = self.dot_discopop / "explorer" / "pattern_decisions.json"
        os.utime(decisions, (decisions.stat().st_atime, patterns.stat().st_mtime - 60))
        self.assertIn("warning", self.__handle(start_line=7))


if __name__ == "__main__":
    unittest.main()
