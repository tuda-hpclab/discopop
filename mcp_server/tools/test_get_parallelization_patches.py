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

from mcp_server.tools import get_parallelization_patches
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
        self.assertEqual(data["patches"][0]["pattern_id"], 7)
        self.assertIn("patch_content", data["patches"][0])
        self.assertIn("#pragma omp parallel for", data["patches"][0]["patch_content"])

    def test_the_summary_carries_the_decision_relevant_facts_only(self) -> None:
        # What a suggestion *is*: one pragma above one loop. The diff around it is
        # context that only matters once a patch is being read rather than chosen.
        data = self.__handle(detail="summary")
        patch = data["patches"][0]
        self.assertNotIn("patch_content", patch)
        self.assertEqual(patch["target_line"], 17)
        self.assertEqual(patch["pragma"], "#pragma omp parallel for firstprivate(N)")
        self.assertEqual(patch["source_file"], "original/main.cpp")

    def test_the_result_points_at_the_tool_that_decides(self) -> None:
        self.assertIn("run_auto_tuning", self.__handle()["next_step"])

    def test_a_project_without_patches_gets_no_next_step(self) -> None:
        shutil.rmtree(os.path.join(self.project_path, ".discopop", "patch_generator", "7"))
        data = self.__handle()
        self.assertEqual(data["patches"], [])
        self.assertNotIn("next_step", data)


if __name__ == "__main__":
    unittest.main()
