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

from mcp_server.tools import get_project_status
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

    def test_an_uninitialized_project_is_pointed_at_initialization(self) -> None:
        data = self.__handle()
        self.assertNotIn("status", data)
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

    def test_suggestions_lead_to_the_suggestions_tool(self) -> None:
        self.__set_up()
        self.__analyse(suggestions=3)
        data = self.__handle()
        self.assertEqual(data["suggestions"], 3)
        self.assertFalse(data["pipeline"]["pattern_detection"]["stale"])
        self.assertIn("3 parallelization suggestions", data["next_step"])
        self.assertIn("get_parallelization_suggestions", data["next_step"])

    def test_no_suggestions_lead_to_explain_parallelization(self) -> None:
        self.__set_up()
        self.__analyse(suggestions=0)
        self.assertIn("explain_parallelization", self.__handle()["next_step"])

    def test_prepared_results_without_any_setup_are_usable(self) -> None:
        self.__analyse(suggestions=2)
        data = self.__handle()
        self.assertFalse(data["initialized"])
        self.assertEqual(data["suggestions"], 2)
        self.assertIn("get_parallelization_suggestions", data["next_step"])
        self.assertIn("cheap", data["next_step"])
        self.assertIn("no setup", data["next_step"])

    def test_prepared_results_older_than_the_sources_are_stale(self) -> None:
        self.__analyse(mtime=_OLD - 7200)
        self.assertTrue(self.__handle()["pipeline"]["pattern_detection"]["stale"])

    def test_current_results_say_that_the_queries_are_cheap(self) -> None:
        self.__set_up()
        self.__analyse()
        self.assertIn("cheap", self.__handle()["next_step"])

    def test_the_result_does_not_report_what_discopop_no_longer_does(self) -> None:
        self.__set_up()
        self.__analyse()
        data = self.__handle()
        for key in ("applied_suggestions", "auto_tuning", "hotspot_results", "note"):
            self.assertNotIn(key, data)
        for tool in ("run_auto_tuning", "manage_patches", "get_execution_results"):
            self.assertNotIn(tool, data["next_step"])
        self.assertNotIn("rollback", get_project_status.TOOL.description or "")

    def test_generated_sources_of_a_build_do_not_make_the_analysis_stale(self) -> None:
        self.__set_up()
        self.__analyse(mtime=_OLD)
        generated = Path(self.project_path) / "build" / "CMakeFiles" / "3.28" / "CompilerIdC" / "CMakeCCompilerId.c"
        generated.parent.mkdir(parents=True)
        generated.write_text("")
        os.utime(generated, (_NEW, _NEW))
        data = self.__handle()
        self.assertFalse(data["pipeline"]["pattern_detection"]["stale"])
        self.assertNotIn("changed", data["next_step"])

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
