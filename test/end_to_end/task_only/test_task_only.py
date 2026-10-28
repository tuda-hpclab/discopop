# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end test of ``discopop_explorer --enable-patterns task`` without do-all and reduction: the task group of
the two independent recursive calls of fib is found, although the program also contains a do-all loop and a
reduction, which must not be reported when they were not asked for."""

import json
from pathlib import Path

from test.end_to_end.pipeline import PipelineTestCase

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo

SRC = Path(__file__).parent / "src"


class TestTaskPatternsOnly(PipelineTestCase):
    SRC_DIR = SRC
    ENABLE_PATTERNS = "task"

    def test_only_task_is_enabled(self) -> None:
        self.assertEqual(self.test_output.enabled_patterns, ["task"])

    def test_the_two_recursive_calls_are_a_task_group(self) -> None:
        patterns = self.test_output.patterns.task
        regions = [p for p in patterns if type(p) is ParallelRegionInfo]
        tasks = [p for p in patterns if type(p) is TaskParallelismInfo]
        self.assertEqual(len(regions), 1)
        self.assertEqual((regions[0].region_start_line, regions[0].region_end_line), ("5", "6"))
        self.assertEqual(sorted((t.region_start_line, t.region_end_line) for t in tasks), [("5", "5"), ("6", "6")])

    def test_no_do_all_and_no_reduction_is_reported(self) -> None:
        # the detectors of types that were not asked for do not run, so the storage has no such attribute at all
        for pattern_type in ("do_all", "reduction", "pipeline", "geometric_decomposition"):
            self.assertEqual(getattr(self.test_output.patterns, pattern_type, []), [], pattern_type)
        self.assertNotIn(
            "DoAllInfo", {type(p).__name__ for p in self.test_output.patterns.task}
        )  # nothing of another type hides in the task patterns

    def test_patterns_json_lists_only_task(self) -> None:
        patterns_json = json.loads((self.dot_discopop / "explorer" / "patterns.json").read_text())
        self.assertEqual(patterns_json["enabled_patterns"], ["task"])
        self.assertEqual([key for key, value in patterns_json["patterns"].items() if value], ["task"])
