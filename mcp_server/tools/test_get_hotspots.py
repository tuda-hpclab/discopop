# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from mcp_server.argument_coercion import validation_error
from mcp_server.tools import get_hotspots
from mcp_server.tools.helpers import ToolContext


def _region(csid: int, typ: str, line: int, hotness: str, runtimes: list[float], name: str = "") -> dict[str, Any]:
    ratio = 1 / (min(runtimes) / max(runtimes) + 1)
    return {
        "csid": csid,
        "typ": typ,
        "fid": 1,
        "lineNum": line,
        "name": name,
        "runtimes": runtimes,
        "hotness": hotness,
        "avr": sum(runtimes) / len(runtimes),
        "minVal": min(runtimes),
        "maxVal": max(runtimes),
        "ratio": ratio,
    }


class TestGetHotspots(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.dot_discopop = Path(self.project_path) / ".discopop"
        (self.dot_discopop / "hotspot_detection").mkdir(parents=True)
        (self.dot_discopop / "FileMapping.txt").write_text(f"1\t{self.source}\n")
        self.ctx = ToolContext(debug=False)
        self.__write(
            [
                _region(1, "FUNCTION", 3, "YES", [1.0, 9.0], name="_Z7computei"),
                _region(2, "LOOP", 5, "MAYBE", [2.0, 20.0]),
                _region(3, "LOOP", 8, "YES", [0.5, 4.0]),
                _region(4, "LOOP", 12, "NO", [0.1, 0.1]),
            ]
        )

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, regions: list[dict[str, Any]]) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))

    def __handle(self, **arguments: Any) -> Any:
        return json.loads(get_hotspots.handle({"project_path": self.project_path, **arguments}, self.ctx)[0].text)

    def test_regions_come_hottest_class_first_then_by_longest_runtime(self) -> None:
        data = self.__handle()
        self.assertEqual([(r["line"], r["hotness"]) for r in data["regions"]], [(3, "YES"), (8, "YES"), (5, "MAYBE")])
        self.assertEqual(data["num_regions_by_hotness"], {"YES": 2, "MAYBE": 1, "NO": 1})
        self.assertEqual(data["regions"][1]["file"], str(self.source))
        self.assertEqual(data["regions"][1]["runtimes"], [0.5, 4.0])

    def test_function_names_are_demangled(self) -> None:
        with mock.patch.object(get_hotspots, "demangle", return_value={"_Z7computei": "compute(int)"}):
            self.assertEqual(self.__handle()["regions"][0]["name"], "compute(int)")
        self.assertNotIn("name", self.__handle()["regions"][1])

    def test_filters_and_limit(self) -> None:
        self.assertEqual([r["line"] for r in self.__handle(hotness=["NO"])["regions"]], [12])
        self.assertEqual([r["type"] for r in self.__handle(region_type="loop")["regions"]], ["loop", "loop"])
        limited = self.__handle(limit=1)
        self.assertEqual(len(limited["regions"]), 1)
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["num_regions"], 3)
        self.assertEqual(self.__handle(file_path=str(self.source))["num_regions"], 3)
        self.assertEqual(self.__handle(file_path="/elsewhere.cpp")["status"], "error")

    def test_a_single_input_size_is_flagged(self) -> None:
        self.assertNotIn("warning", self.__handle())
        self.__write([_region(1, "LOOP", 5, "YES", [2.0]), _region(2, "LOOP", 8, "MAYBE", [1.0])])
        self.assertIn("input sizes", self.__handle()["warning"])

    def test_results_without_regions_are_not_blamed_on_the_input_sizes(self) -> None:
        self.__write([])
        warning = self.__handle()["warning"]
        self.assertNotIn("input sizes", warning)
        self.assertIn("no region", warning)

    def test_an_empty_hotness_filter_is_rejected(self) -> None:
        schema = get_hotspots.TOOL.inputSchema
        self.assertIsNotNone(validation_error("get_hotspots", {"project_path": "/p", "hotness": []}, schema))

    def test_missing_results_name_the_call_that_produces_them(self) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").unlink()
        data = self.__handle()
        self.assertEqual(data["regions"], [])
        self.assertIn("hotspot_config_names", data["next_step"])

    def test_demangle_without_a_demangler_keeps_the_names(self) -> None:
        with mock.patch("mcp_server.tools.get_hotspots.shutil.which", return_value=None):
            self.assertEqual(get_hotspots.demangle(["_Z1fv"]), {})


if __name__ == "__main__":
    unittest.main()
