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
    UNPRIVATIZABLE_STATIC_DEPENDENCY,
    CodeRegion,
    DecisionReason,
    DependencyRecord,
    PatternDecisionLog,
)
from mcp_server.tools import explain_parallelization
from mcp_server.tools.explain_parallelization import MAX_REASONS_PER_REGION, MAX_REGIONS
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

    def __handle(self, **arguments: Any) -> str:
        arguments = {"project_path": self.project_path, "file_path": str(self.source), **arguments}
        return explain_parallelization.handle(arguments, self.ctx)[0].text

    def __error(self, **arguments: Any) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.__handle(**arguments))
        return data

    def test_an_accepted_region_names_its_suggestions(self) -> None:
        text = self.__handle(start_line=7)
        self.assertEqual(
            text.splitlines()[:2],
            ["main.cpp:7 lies in 1 code region, innermost first:", "Loop main.cpp:6-8: suggestion 3 (doall)."],
        )
        self.assertIn("get_parallelization_suggestions", text)
        self.assertNotIn("not parallelizable", text)

    def test_a_rejected_region_names_the_dependency_with_resolved_lines(self) -> None:
        text = self.__handle(start_line=20)
        self.assertIn("Loop main.cpp:10-30: not parallelizable.", text)
        self.assertIn(
            "- RAW dependency to main.cpp:11 via elements of variable a from main.cpp:11 prevents "
            "parallelization (observed during profiling).",
            text,
        )

    def test_a_dependency_of_the_static_analysis_that_cannot_be_privatized_says_so(self) -> None:
        reason = DecisionReason(
            UNPRIVATIZABLE_STATIC_DEPENDENCY,
            "m",
            dependency=DependencyRecord("WAR", "t", "7", "1:14", "1:15", "static", False),
        )
        self.log.reject(DETECTOR, TYPES, CodeRegion("1:40", 1, 40, 42, "loop"), reason)
        self.__save()
        text = self.__handle(start_line=41)
        self.assertIn(
            "- WAR dependency to main.cpp:15 via variable t from main.cpp:14 prevents parallelization: the variable "
            "cannot be privatized, as it is neither written before it is read in each iteration nor a reduction "
            "variable (found by static analysis).",
            text,
        )

    def test_a_reason_without_a_dependency_is_worded_by_the_explorer(self) -> None:
        text = self.__handle(start_line=13)
        self.assertIn("Loop main.cpp:12-14: not parallelizable.\n- m", text)

    def test_reasons_of_other_kinds_use_their_message(self) -> None:
        details = {"pattern_id": 3, "node_id": "1:5", "file_id": 1, "start_line": 6, "end_line": 8}
        self.log.reject(
            DETECTOR,
            TYPES,
            CodeRegion("1:40", 1, 40, 42, "loop"),
            DecisionReason(
                "duplicate_pattern", "An equivalent suggestion was reported for other code.", details=details
            ),
        )
        self.__save()
        self.assertIn("- An equivalent suggestion was reported for other code.", self.__handle(start_line=41))

    def test_nested_regions_come_innermost_first(self) -> None:
        lines = self.__handle(start_line=13).splitlines()
        self.assertEqual(lines[0], "main.cpp:13 lies in 2 code regions, innermost first:")
        titles = [line for line in lines if line.startswith("Loop")]
        self.assertEqual(
            titles, ["Loop main.cpp:12-14: not parallelizable.", "Loop main.cpp:10-30: not parallelizable."]
        )
        self.assertIn("more often", self.__handle(start_line=13))

    def test_a_range_matches_every_overlapping_region(self) -> None:
        text = self.__handle(start_line=1, end_line=100)
        self.assertTrue(text.startswith("main.cpp:1-100 lies in 3 code regions"))

    def test_a_relative_file_path_is_taken_relative_to_the_project(self) -> None:
        self.assertIn("Loop main.cpp:6-8", self.__handle(file_path="main.cpp", start_line=7))

    def test_many_regions_and_reasons_are_cut(self) -> None:
        for i in range(MAX_REASONS_PER_REGION + 5):
            self.log.reject(DETECTOR, TYPES, CodeRegion("1:11", 1, 10, 30, "loop"), _carried(f"v{i}"))
        for n in range(MAX_REGIONS + 2):
            self.log.reject(DETECTOR, TYPES, CodeRegion(f"1:{50 + n}", 1, 50 + n, 80, "loop"), _carried("w"))
        self.log.finalize(DETECTOR, [cast(Any, DoAllInfo("1:5", 3))])
        self.__save()
        text = self.__handle(start_line=20)
        self.assertEqual(text.count("- RAW dependency"), MAX_REASONS_PER_REGION)
        self.assertIn("- 6 more reasons.", text)
        text = self.__handle(start_line=70)
        self.assertEqual(text.count("\nLoop "), MAX_REGIONS)
        self.assertIn("2 more regions not explained (the outermost ones).", text)

    def test_lines_outside_every_region_are_explained(self) -> None:
        text = self.__handle(start_line=40)
        self.assertTrue(text.startswith("Pattern detection considered no code region at main.cpp:40."))
        self.assertIn("never executed", text)

    def test_a_detection_without_any_recording_detector_says_so(self) -> None:
        self.log = PatternDecisionLog()  # a detection that ran no detector which records decisions
        self.__save()
        self.assertIn("ran no detector", self.__handle(start_line=7))

    def test_a_file_outside_the_program_is_an_error(self) -> None:
        data = self.__error(file_path="/elsewhere/other.cpp", start_line=1)
        self.assertEqual(data["status"], "error")

    def test_a_result_of_an_older_version_asks_for_a_new_analysis(self) -> None:
        (self.dot_discopop / "explorer" / "pattern_decisions.json").unlink()
        self.assertIn("Run gather_data first", self.__error(start_line=7)["message"])
        (self.dot_discopop / "explorer" / "patterns.json").write_text("{}")
        self.assertIn("does not record", self.__error(start_line=7)["message"])

    def test_suggestions_newer_than_the_explanation_are_flagged(self) -> None:
        patterns = self.dot_discopop / "explorer" / "patterns.json"
        patterns.write_text("{}")
        decisions = self.dot_discopop / "explorer" / "pattern_decisions.json"
        os.utime(decisions, (decisions.stat().st_atime, patterns.stat().st_mtime - 60))
        self.assertIn("Note: the suggestions were produced after", self.__handle(start_line=7))

    def test_the_hints_do_not_point_at_tools_that_are_gone(self) -> None:
        description = explain_parallelization.TOOL.description or ""
        for text in (description, self.__handle(start_line=20), self.__handle(start_line=13)):
            self.assertNotIn("get_data_dependencies", text)


if __name__ == "__main__":
    unittest.main()
