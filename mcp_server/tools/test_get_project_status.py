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
import time
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from mcp_server.tools import get_project_status, helpers
from mcp_server.tools.helpers import COMPILE_SCRIPT_PLACEHOLDER_MARKER, ToolContext

# Analysis outputs are dated this far before the sources (or after them), so the
# comparison never depends on the resolution of the file system's timestamps.
_OLD = time.time() - 3600
_NEW = time.time() + 3600


class TestGetProjectStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "main.cpp"
        self.source.write_text("int main() {}\n")
        os.utime(self.source, (_OLD - 3600, _OLD - 3600))
        self.dot_dp = Path(self.project_path) / ".discopop"
        self.configs = self.dot_dp / "project" / "configs"
        self.ctx = ToolContext(debug=False)
        # read_applied_suggestions runs the patch applicator; its answer is given here
        patcher = mock.patch.object(helpers, "read_applied_suggestions", return_value=([], None))
        self.read_applied = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __handle(self) -> Any:
        return json.loads(get_project_status.handle({"project_path": self.project_path}, self.ctx)[0].text)

    def __write(self, relative: str, content: str = "", mtime: Optional[float] = _NEW) -> Path:
        path = self.dot_dp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def __set_up(self) -> None:
        self.__write("project/configs/compile.sh", "#!/bin/bash\n$CXX $CXXFLAGS main.cpp\n")
        self.__write("project/configs/small/execute.sh", "#!/bin/bash\n./a.out\n")

    def __analyse(self, suggestions: int = 2, mtime: float = _NEW) -> None:
        for relative in ("profiler/Data.xml", "profiler/dynamic_dependencies.txt", "explorer/patterns.json"):
            self.__write(relative, mtime=mtime)
        self.__write("FileMapping.txt", f"1\t{self.source}\n")
        (self.dot_dp / "patch_generator").mkdir()
        for suggestion in range(suggestions):
            (self.dot_dp / "patch_generator" / str(suggestion)).mkdir(parents=True)
            # file id 1 is main.cpp
            (self.dot_dp / "patch_generator" / str(suggestion) / "1.patch").write_text("")
        os.utime(self.dot_dp / "patch_generator", (mtime, mtime))

    def __tune(self, events: list[dict[str, Any]], mtime: float = _NEW + 60) -> None:
        self.__write("auto_tuner/progress.jsonl", "\n".join(json.dumps(e) for e in events) + "\n", mtime=mtime)

    def test_an_uninitialized_project_is_pointed_at_initialization(self) -> None:
        data = self.__handle()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["initialized"])
        self.assertIn("initialize_discopop_directory", data["next_step"])
        self.assertNotIn("pipeline", data)

    def test_a_placeholder_compile_script_is_the_missing_step(self) -> None:
        self.__write("project/configs/compile.sh", f"echo '{COMPILE_SCRIPT_PLACEHOLDER_MARKER}'; exit 1\n")
        data = self.__handle()
        self.assertTrue(data["initialized"])
        self.assertFalse(data["compile_script_configured"])
        self.assertIn("set_compile_script", data["next_step"])

    def test_a_project_that_is_set_up_but_not_analysed_is_pointed_at_gather_data(self) -> None:
        self.__set_up()
        data = self.__handle()
        self.assertEqual(data["configurations"], ["small"])
        self.assertTrue(data["compile_script_configured"])
        self.assertEqual(data["pipeline"]["pattern_detection"], {"done": False})
        self.assertFalse(data["hotspot_results"])
        self.assertNotIn("suggestions", data)
        self.assertIn("gather_data", data["next_step"])

    def test_sources_newer_than_the_analysis_make_it_stale(self) -> None:
        self.__set_up()
        self.__analyse(mtime=_OLD)
        os.utime(self.source, (_NEW, _NEW))
        data = self.__handle()
        self.assertTrue(data["pipeline"]["profiling"]["stale"])
        self.assertTrue(data["pipeline"]["pattern_detection"]["stale"])
        self.assertIn("gather_data", data["next_step"])
        self.assertIn("changed", data["next_step"])

    def test_suggestions_without_tuning_lead_to_run_auto_tuning(self) -> None:
        self.__set_up()
        self.__analyse(suggestions=3)
        data = self.__handle()
        self.assertEqual(data["suggestions"], 3)
        self.assertFalse(data["pipeline"]["pattern_detection"]["stale"])
        self.assertEqual(data["applied_suggestions"], [])
        self.assertNotIn("auto_tuning", data)
        self.assertIn("run_auto_tuning", data["next_step"])
        self.assertIn("'small'", data["next_step"])

    def test_no_suggestions_lead_to_explain_parallelization(self) -> None:
        self.__set_up()
        self.__analyse(suggestions=0)
        self.assertIn("explain_parallelization", self.__handle()["next_step"])

    def test_an_unapplied_tuning_selection_is_named_for_manage_patches(self) -> None:
        self.__set_up()
        self.__analyse()
        self.__tune(
            [
                {"event": "baseline", "runtime": 10.0, "valid": True, "thread_count": 4, "config": "small"},
                {"event": "result", "suggestions": [1], "speedup": 2.0, "runtime": 5.0, "config": "small"},
            ]
        )
        data = self.__handle()
        self.assertEqual(
            data["auto_tuning"],
            {
                "at": data["auto_tuning"]["at"],
                "config": "small",
                "complete": True,
                "suggestion_ids": ["1"],
                "speedup": 2.0,
                "thread_count": 4,
            },
        )
        self.assertIn("manage_patches(action='apply'", data["next_step"])

    def test_tuning_older_than_the_analysis_is_stale(self) -> None:
        self.__set_up()
        self.__analyse()
        self.__tune([{"event": "result", "suggestions": [1], "speedup": 2.0}], mtime=_OLD)
        data = self.__handle()
        self.assertTrue(data["auto_tuning"]["stale"])
        self.assertIn("run_auto_tuning", data["next_step"])

    def test_applied_suggestions_are_reported_and_end_the_workflow(self) -> None:
        self.__set_up()
        self.__analyse()
        self.__write("patch_applicator/applied_suggestions.json", json.dumps({"applied": ["1"]}))
        self.read_applied.return_value = (["1"], None)
        data = self.__handle()
        self.assertEqual(data["applied_suggestions"], ["1"])
        self.assertIn("rollback", data["next_step"])
        self.assertNotIn("gather_data", data["next_step"])

    def test_staleness_caused_by_patching_is_not_a_reason_to_reanalyse(self) -> None:
        self.__set_up()
        self.__analyse(mtime=_OLD)
        os.utime(self.source, (_NEW, _NEW))
        # the applicator records the selection right after it rewrote the sources
        self.__write("patch_applicator/applied_suggestions.json", json.dumps({"applied": []}), mtime=_NEW + 1)
        data = self.__handle()
        self.assertTrue(data["pipeline"]["pattern_detection"]["stale"])
        self.assertIn("note", data)
        self.assertIn("run_auto_tuning", data["next_step"])

    def test_edits_after_patching_need_a_rollback_before_reanalysing(self) -> None:
        self.__set_up()
        self.__analyse(mtime=_OLD)
        self.__write("patch_applicator/applied_suggestions.json", json.dumps({"applied": ["1"]}), mtime=_OLD + 60)
        os.utime(self.source, (_NEW, _NEW))
        self.read_applied.return_value = (["1"], None)
        data = self.__handle()
        self.assertNotIn("note", data)
        self.assertIn("rollback", data["next_step"])

    def test_an_edit_to_a_file_no_suggestion_patches_is_not_taken_for_patching(self) -> None:
        # edited after the analysis, then a suggestion was applied to main.cpp: the newest
        # source file is the patched one, but the edit still makes the analysis stale
        self.__set_up()
        self.__analyse(mtime=_OLD)
        header = Path(self.project_path) / "util.h"
        header.write_text("int f();\n")
        os.utime(header, (_OLD + 60, _OLD + 60))
        os.utime(self.source, (_NEW, _NEW))
        self.__write("patch_applicator/applied_suggestions.json", json.dumps({"applied": []}), mtime=_NEW + 1)
        data = self.__handle()
        self.assertNotIn("note", data)
        self.assertIn("gather_data", data["next_step"])

    def test_an_edit_made_just_after_patching_is_not_taken_for_it(self) -> None:
        self.__set_up()
        self.__analyse(mtime=_OLD)
        self.__write("patch_applicator/applied_suggestions.json", json.dumps({"applied": []}), mtime=_OLD + 60)
        os.utime(self.source, (_OLD + 60 + 2 * get_project_status._PATCHING_SLACK_SECONDS,) * 2)
        data = self.__handle()
        self.assertNotIn("note", data)
        self.assertIn("gather_data", data["next_step"])

    def test_the_applicator_is_not_run_without_a_record_of_applied_suggestions(self) -> None:
        # it would create its state file, and this tool must not write to the project
        self.__set_up()
        self.__analyse()
        self.__handle()
        self.read_applied.assert_not_called()

    def test_errors_are_reported_not_raised(self) -> None:
        self.__set_up()
        with mock.patch.object(get_project_status, "configuration_names", side_effect=RuntimeError("boom")):
            data = self.__handle()
        self.assertEqual(data["status"], "error")
        self.assertIn("boom", data["message"])
        missing = json.loads(get_project_status.handle({"project_path": "/does/not/exist"}, self.ctx)[0].text)
        self.assertEqual(missing["status"], "error")


if __name__ == "__main__":
    unittest.main()
