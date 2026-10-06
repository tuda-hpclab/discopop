# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import shutil
import tempfile
import unittest
from typing import Any

from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import get_parallelization_patches, manage_patches
from mcp_server.tools.helpers import ToolContext

_PATCH = """--- original/main.cpp
+++ main.cpp
@@ -17,6 +17,7 @@
+  #pragma omp parallel for firstprivate(N)
   for (int i = 0; i < N; i++) {
     Arr[i] = i % 13;
   }
"""


class TestGetParallelizationPatches(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = os.path.join(self._tmp_dir.name, "project")
        patch_dir = os.path.join(self.project_path, ".discopop", "patch_generator", "7")
        os.makedirs(patch_dir)
        with open(os.path.join(patch_dir, "1.patch"), "w") as f:
            f.write(_PATCH)
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __handle(self, **overrides: Any) -> Any:
        arguments: dict[str, Any] = {"project_path": self.project_path}
        arguments.update(overrides)
        return json.loads(get_parallelization_patches.handle(arguments, self.ctx)[0].text)

    def test_the_full_diff_is_returned_by_default(self) -> None:
        data = self.__handle()
        self.assertEqual(data["patches"][0]["pattern_id"], "7")
        self.assertIn("patch_content", data["patches"][0])
        self.assertIn("#pragma omp parallel for", data["patches"][0]["patch_content"])

    def test_pattern_ids_have_the_type_manage_patches_takes(self) -> None:
        # The id read here is passed on as manage_patches' suggestion_ids, which are
        # strings; an int in one place and a string in the other is a schema contradiction.
        schema = get_parallelization_patches.TOOL.inputSchema["properties"]["pattern_id"]
        id_items = manage_patches.TOOL.inputSchema["properties"]["suggestion_ids"]["items"]
        self.assertEqual(schema["type"], id_items["type"])
        self.assertIsInstance(self.__handle()["patches"][0]["pattern_id"], str)

    def test_the_pattern_id_filter_selects_one_suggestion(self) -> None:
        self.assertEqual(len(self.__handle(pattern_id="7")["patches"]), 1)
        self.assertEqual(self.__handle(pattern_id="8")["patches"], [])

    def test_an_integer_pattern_id_is_still_accepted(self) -> None:
        schema = get_parallelization_patches.TOOL.inputSchema
        arguments, _ = coerce_arguments({"project_path": self.project_path, "pattern_id": 7}, schema)
        self.assertIsNone(validation_error("get_parallelization_patches", arguments, schema))
        data = json.loads(get_parallelization_patches.handle(arguments, self.ctx)[0].text)
        self.assertEqual([patch["pattern_id"] for patch in data["patches"]], ["7"])

    def test_the_summary_carries_the_decision_relevant_facts_only(self) -> None:
        # What a suggestion *is*: one pragma above one region. The diff around it is
        # context that only matters once a patch is being read rather than chosen.
        data = self.__handle(detail="summary")
        self.assertEqual(data["num_suggestions"], 1)
        group = data["files"][0]
        self.assertEqual(group["file"], "original/main.cpp")
        suggestion = group["suggestions"][0]
        self.assertNotIn("patch_content", suggestion)
        self.assertNotIn("source_file", suggestion)
        self.assertEqual(suggestion["pragma"], "#pragma omp parallel for firstprivate(N)")

    def test_the_summary_names_type_lines_hotness_and_nesting(self) -> None:
        self.__analysed_project()
        data = self.__handle(detail="summary")
        self.assertEqual([g["file"] for g in data["files"]], [self.source])
        by_id = {s["pattern_id"]: s for s in data["files"][0]["suggestions"]}
        self.assertEqual(
            by_id["7"],
            {
                "pattern_id": "7",
                "type": "doall",
                "line": 20,
                "end_line": 30,
                "hotness": "YES",
                "same_region": ["9"],
                "pragma": "#pragma omp parallel for firstprivate(N)",
            },
        )
        self.assertEqual(by_id["8"]["type"], "reduction")
        self.assertEqual(by_id["8"]["nested_in"], ["7", "9"])
        self.assertEqual(by_id["8"]["hotness"], "unclassified")
        self.assertEqual(by_id["9"]["collapse"], 2)

    def test_filters_and_limit(self) -> None:
        self.__analysed_project()
        self.assertEqual([p["pattern_id"] for p in self.__handle(pattern_ids=["8", "9"])["patches"]], ["8", "9"])
        self.assertEqual(len(self.__handle(file_path=self.source)["patches"]), 3)
        self.assertEqual(self.__handle(file_path="/elsewhere.cpp")["status"], "error")
        limited = self.__handle(limit=1)
        self.assertEqual(len(limited["patches"]), 1)
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["num_suggestions"], 3)
        self.assertIn("limit", limited["next_step"])

    def test_limit_counts_suggestions_not_the_files_they_patch(self) -> None:
        # suggestion 7 changes two files; limit=1 keeps both its patches, and only it
        with open(os.path.join(self.project_path, ".discopop", "patch_generator", "7", "2.patch"), "w") as f:
            f.write(_PATCH.replace("main.cpp", "util.cpp"))
        other = os.path.join(self.project_path, ".discopop", "patch_generator", "8")
        os.makedirs(other)
        with open(os.path.join(other, "1.patch"), "w") as f:
            f.write(_PATCH)
        limited = self.__handle(limit=1)
        self.assertEqual([p["pattern_id"] for p in limited["patches"]], ["7", "7"])
        self.assertTrue(limited["truncated"])

    def __analysed_project(self) -> None:
        """Three suggestions in main.cpp, as gather_data leaves them: two on the loop at line 20
        (a doall and its collapsed variant), a reduction on a loop nested in it."""
        from discopop_explorer.classes.patterns.PatternDecisions import CodeRegion, PatternDecisionLog

        dot_discopop = os.path.join(self.project_path, ".discopop")
        self.source = os.path.join(self.project_path, "main.cpp")
        with open(self.source, "w") as f:
            f.write("int main() {}\n")
        with open(os.path.join(dot_discopop, "FileMapping.txt"), "w") as f:
            f.write(f"1\t{self.source}\n")
        for pid in ("8", "9"):
            os.makedirs(os.path.join(dot_discopop, "patch_generator", pid))
            with open(os.path.join(dot_discopop, "patch_generator", pid, "1.patch"), "w") as f:
                f.write(_PATCH)
        os.makedirs(os.path.join(dot_discopop, "explorer"))
        with open(os.path.join(dot_discopop, "explorer", "patterns.json"), "w") as f:
            json.dump(
                {
                    "patterns": {
                        "do_all": [
                            {"pattern_id": 7, "start_line": "1:20", "collapse_level": 1},
                            {"pattern_id": 9, "start_line": "1:20", "collapse_level": 2},
                        ],
                        "reduction": [{"pattern_id": 8, "start_line": "1:22"}],
                    }
                },
                f,
            )

        class _Pattern:
            def __init__(self, node_id: str, pattern_id: int) -> None:
                self.node_id, self.pattern_id = node_id, pattern_id

        class DoAllInfo(_Pattern):
            pass

        class ReductionInfo(_Pattern):
            pass

        log = PatternDecisionLog()
        log.consider("doall_reduction", ["doall", "reduction"], CodeRegion("1:5", 1, 20, 30, "loop"))
        log.consider("doall_reduction", ["doall", "reduction"], CodeRegion("1:6", 1, 22, 25, "loop"))
        patterns: list[Any] = [DoAllInfo("1:5", 7), DoAllInfo("1:5", 9), ReductionInfo("1:6", 8)]
        log.finalize("doall_reduction", patterns)
        log.save(os.path.join(dot_discopop, "explorer", "pattern_decisions.json"))
        os.makedirs(os.path.join(dot_discopop, "hotspot_detection"))
        with open(os.path.join(dot_discopop, "hotspot_detection", "Hotspots.json"), "w") as f:
            region = {"csid": 1, "typ": "LOOP", "fid": 1, "lineNum": 20, "name": "", "hotness": "YES", "avr": 1.0}
            json.dump({"code_regions": [region]}, f)

    def test_the_result_points_at_the_tool_that_decides(self) -> None:
        self.assertIn("run_auto_tuning", self.__handle()["next_step"])

    def test_a_project_without_patches_gets_no_next_step(self) -> None:
        shutil.rmtree(os.path.join(self.project_path, ".discopop", "patch_generator", "7"))
        data = self.__handle()
        self.assertEqual(data["patches"], [])
        self.assertNotIn("next_step", data)


if __name__ == "__main__":
    unittest.main()
