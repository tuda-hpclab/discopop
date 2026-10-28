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

import pytest

from mcp_server.argument_coercion import coerce_arguments, validation_error
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
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.dot_discopop = Path(self.project_path) / ".discopop"
        (self.dot_discopop / "hotspot_detection").mkdir(parents=True)
        (self.dot_discopop / "FileMapping.txt").write_text(f"1\t{self.source}\n")
        self.ctx = ToolContext(debug=False)
        # whether a demangler is installed must not matter
        demangler = mock.patch.object(get_hotspots, "demangle", return_value={})
        demangler.start()
        self.addCleanup(demangler.stop)
        self.__write(
            [
                _region(1, "FUNCTION", 1, "YES", [1.0, 10.0], name="main"),
                _region(2, "FUNCTION", 3, "YES", [1.0, 9.0], name="_Z7computei"),
                _region(3, "LOOP", 5, "MAYBE", [2.0, 20.0 / 3]),
                _region(4, "LOOP", 8, "YES", [0.5, 4.0]),
                _region(5, "LOOP", 12, "NO", [0.1, 0.1]),
            ]
        )

    def __write(self, regions: list[dict[str, Any]]) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))

    def __handle(self, **arguments: Any) -> str:
        return get_hotspots.handle({"project_path": self.project_path, **arguments}, self.ctx)[0].text

    def test_hotspots_come_longest_running_first_whatever_their_class(self) -> None:
        lines = self.__handle().splitlines()
        self.assertEqual(lines[0], "2 hotspots and 1 potential hotspot, longest running first:")
        self.assertEqual(
            lines[1:4],
            [
                "Hotspot Function main.cpp:3 _Z7computei (9.00 s, 90% of runtime)",
                "Potential Hotspot Loop main.cpp:5 (6.67 s, 67% of runtime)",
                "Hotspot Loop main.cpp:8 (4.00 s, 40% of runtime)",
            ],
        )

    def test_main_and_regions_that_are_no_hotspots_are_left_out(self) -> None:
        text = self.__handle()
        self.assertNotIn("main.cpp:1 ", text)
        self.assertNotIn("main.cpp:12", text)
        self.assertEqual(text.count("\n"), 3)

    def test_function_names_are_demangled_and_shown_without_their_parameters(self) -> None:
        with mock.patch.object(get_hotspots, "demangle", return_value={"_Z7computei": "ns::compute(int, double*)"}):
            self.assertIn("Hotspot Function main.cpp:3 ns::compute (9.00 s", self.__handle())

    def test_the_limit_says_how_many_hotspots_and_potential_hotspots_are_not_shown(self) -> None:
        text = self.__handle(limit=1)
        self.assertEqual(len([line for line in text.splitlines() if "main.cpp" in line]), 1)
        self.assertIn("1 hotspot and 1 potential hotspot not shown (limit=1); pass a larger limit", text)
        self.assertIn("1 hotspot not shown (limit=2)", self.__handle(limit=2))
        self.assertNotIn("not shown", self.__handle(limit=3))

    def test_the_default_limit_is_fixed(self) -> None:
        regions = [_region(100 + n, "LOOP", 100 + n, "YES", [1.0, 5.0 - n / 100]) for n in range(15)]
        self.__write([_region(1, "FUNCTION", 1, "YES", [1.0, 10.0], name="main"), *regions])
        text = self.__handle()
        self.assertEqual(len([line for line in text.splitlines() if "main.cpp" in line]), get_hotspots.DEFAULT_LIMIT)
        self.assertIn("5 hotspots not shown", text)

    def test_a_single_input_size_is_flagged(self) -> None:
        self.assertNotIn("Only one input size", self.__handle())
        self.__write(
            [_region(1, "LOOP", 5, "YES", [2.0]), _region(2, "LOOP", 8, "MAYBE", [1.0])],
        )
        self.assertIn("Only one input size was profiled", self.__handle())

    def test_results_without_regions_are_not_blamed_on_the_input_sizes(self) -> None:
        self.__write([])
        text = self.__handle()
        self.assertIn("No hotspots found.", text)
        self.assertIn("no region", text)
        self.assertNotIn("input size", text)

    def test_missing_results_name_the_call_that_produces_them(self) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").unlink()
        data = json.loads(self.__handle())
        self.assertEqual(data["status"], "error")
        self.assertIn("gather_data", data["message"])

    def test_the_schema_has_the_limit_only(self) -> None:
        schema = get_hotspots.TOOL.inputSchema
        self.assertEqual(set(schema["properties"]), {"project_path", "limit"})
        arguments, _ = coerce_arguments({"project_path": "/p", "limit": "5"}, schema)
        self.assertEqual(arguments["limit"], 5)
        self.assertIsNone(validation_error("get_hotspots", arguments, schema))

    def test_demangle_without_a_demangler_keeps_the_names(self) -> None:
        with mock.patch("mcp_server.tools.get_hotspots.shutil.which", return_value=None):
            self.assertEqual(get_hotspots.demangle(["_Z1fv"]), {})


@pytest.mark.parametrize(
    "name, short",
    [
        ("compute", "compute"),
        ("ns::Cls::scale(double*, int)", "ns::Cls::scale"),
        ("f(void (*)(int), int)", "f"),
        ("Cls::operator()(int)", "Cls::operator()"),
        ("Cls::operator()", "Cls::operator()"),
    ],
)
def test_the_parameter_list_is_dropped_from_function_names(name: str, short: str) -> None:
    assert get_hotspots._short_name(name) == short


if __name__ == "__main__":
    unittest.main()
