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
from types import SimpleNamespace
from typing import Any
from unittest import mock

from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import get_data_dependencies
from mcp_server.tools.helpers import ToolContext


def _dep(source: str, sink: str, var_name: str = "sum", dtype: DepType = DepType.RAW) -> Any:
    dep = SimpleNamespace(etype=EdgeType.DATA, dtype=dtype, source_line=source, sink_line=sink, var_name=var_name)
    return (None, None, dep)


def _mixed() -> list[Any]:
    # One dependency per direction and type: incoming RAW, outgoing WAR, intra_region WAW.
    return [
        _dep("1:5", "1:12", "a", DepType.RAW),
        _dep("1:13", "1:30", "b", DepType.WAR),
        _dep("1:14", "1:15", "c", DepType.WAW),
    ]


def _counts(data: Any) -> dict[str, int]:
    return {direction: len(entries) for direction, entries in data["dependencies"].items()}


class TestGetDataDependencies(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.source = Path(self._tmp_dir.name) / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.header = Path(self._tmp_dir.name) / "util.h"
        self.header.write_text("\n")
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __handle(self, edges: list[Any], **extra: Any) -> Any:
        detection_result = SimpleNamespace(pet=SimpleNamespace(g=mock.Mock(edges=mock.Mock(return_value=edges))))
        with (
            mock.patch.object(self.ctx, "get_detection_result", return_value=detection_result),
            mock.patch.object(self.ctx, "get_file_mapping", return_value={1: self.source, 2: self.header}),
        ):
            arguments = {
                "project_path": self._tmp_dir.name,
                "file_path": str(self.source),
                "start_line": 10,
                "end_line": 20,
                **extra,
            }
            return json.loads(get_data_dependencies.handle(arguments, self.ctx)[0].text)

    def test_an_empty_region_is_not_presented_as_independent(self) -> None:
        # The dynamic analysis only knows executed code: no dependency can also mean
        # that the profiling run never reached the region.
        data = self.__handle([])
        self.assertEqual(data["num_dependencies"], 0)
        self.assertIn("never executed", data["next_step"])

    def test_a_region_with_dependencies_needs_no_caveat(self) -> None:
        data = self.__handle([_dep("1:12", "1:15")])
        self.assertEqual(data["num_dependencies"], 1)
        self.assertNotIn("next_step", data)

    def test_ends_in_the_queried_file_are_bare_lines(self) -> None:
        # The queried file is already file_path; repeating it per entry only costs tokens.
        data = self.__handle([_dep("1:12", "1:15"), _dep("2:3", "1:11", "x")])
        intra = data["dependencies"]["intra_region"][0]
        self.assertEqual((intra["source"], intra["sink"]), (12, 15))
        incoming = data["dependencies"]["incoming"][0]
        self.assertEqual(incoming["source"], {"file": str(self.header), "line": 3})
        self.assertEqual(incoming["sink"], 11)

    def test_result_is_capped_and_says_how_to_narrow(self) -> None:
        cap = get_data_dependencies.MAX_DEPENDENCIES
        edges = [_dep("1:12", "1:15", f"v{i}") for i in range(cap)]
        edges += [_dep("1:5", "1:11", f"w{i}") for i in range(5)]
        data = self.__handle(edges)
        self.assertEqual(data["num_dependencies"], cap + 5)
        self.assertTrue(data["truncated"])
        self.assertEqual(sum(_counts(data).values()), cap)
        # incoming comes first, so the cut falls on intra_region
        self.assertEqual(_counts(data)["incoming"], 5)
        self.assertEqual(data["num_dependencies_by_direction"], {"incoming": 5, "outgoing": 0, "intra_region": cap})
        for hint in ("start_line", "var_name", "dep_types", "directions"):
            self.assertIn(hint, data["next_step"])

    def test_a_truncated_result_does_not_depend_on_edge_order(self) -> None:
        cap = get_data_dependencies.MAX_DEPENDENCIES
        edges = [_dep(f"1:{10 + i % 11}", f"1:{10 + (i * 7) % 11}", f"v{i}") for i in range(cap + 50)]
        forward = self.__handle(edges)
        backward = self.__handle(list(reversed(edges)))
        self.assertEqual(forward["dependencies"], backward["dependencies"])
        sinks = [entry["sink"] for entry in forward["dependencies"]["intra_region"]]
        self.assertEqual(sinks, sorted(sinks))

    def test_a_result_at_the_cap_is_not_truncated(self) -> None:
        cap = get_data_dependencies.MAX_DEPENDENCIES
        data = self.__handle([_dep("1:12", "1:15", f"v{i}") for i in range(cap)])
        self.assertEqual(data["num_dependencies"], cap)
        self.assertNotIn("truncated", data)
        self.assertNotIn("next_step", data)

    def test_dep_types_filter(self) -> None:
        data = self.__handle(_mixed(), dep_types=["RAW", "WAW"])
        self.assertEqual(_counts(data), {"incoming": 1, "outgoing": 0, "intra_region": 1})

    def test_directions_filter(self) -> None:
        data = self.__handle(_mixed(), directions=["outgoing"])
        self.assertEqual(_counts(data), {"incoming": 0, "outgoing": 1, "intra_region": 0})

    def test_omitted_or_empty_filters_mean_all(self) -> None:
        extras: list[dict[str, Any]] = [{}, {"dep_types": [], "directions": []}]
        for extra in extras:
            with self.subTest(extra=extra):
                self.assertEqual(self.__handle(_mixed(), **extra)["num_dependencies"], 3)

    def test_var_name_excludes_incoming_and_says_so(self) -> None:
        edges = [_dep("1:5", "1:12", "a"), _dep("1:13", "1:30", "a"), _dep("1:14", "1:15", "b")]
        data = self.__handle(edges, var_name="a")
        self.assertEqual(_counts(data), {"incoming": 0, "outgoing": 1, "intra_region": 0})
        self.assertTrue(data["incoming_excluded_due_to_var_name_filter"])

    def test_var_name_with_directions_without_incoming_needs_no_notice(self) -> None:
        # Nothing was excluded on the caller's behalf, so there is nothing to report.
        edges = [_dep("1:13", "1:30", "a"), _dep("1:14", "1:15", "a")]
        data = self.__handle(edges, var_name="a", directions=["intra_region"])
        self.assertEqual(_counts(data), {"incoming": 0, "outgoing": 0, "intra_region": 1})
        self.assertNotIn("incoming_excluded_due_to_var_name_filter", data)


class TestFilterArguments(unittest.TestCase):
    """Clients often send arrays as strings; the filters must survive coercion and validation."""

    _SCHEMA = get_data_dependencies.TOOL.inputSchema
    _BASE = {"project_path": "/p", "file_path": "/p/a.c", "start_line": 1, "end_line": 2}

    def test_string_forms_validate_after_coercion(self) -> None:
        for dep_types, directions, expected in (
            ('["RAW", "WAR"]', '["incoming"]', (["RAW", "WAR"], ["incoming"])),
            ("RAW, WAW", "outgoing, intra_region", (["RAW", "WAW"], ["outgoing", "intra_region"])),
            ("WAR", "intra_region", (["WAR"], ["intra_region"])),
        ):
            with self.subTest(dep_types=dep_types, directions=directions):
                arguments = {**self._BASE, "dep_types": dep_types, "directions": directions}
                coerced, _ = coerce_arguments(arguments, self._SCHEMA)
                self.assertEqual((coerced["dep_types"], coerced["directions"]), expected)
                self.assertIsNone(validation_error("get_data_dependencies", coerced, self._SCHEMA))

    def test_unknown_values_are_rejected(self) -> None:
        for arguments in ({"dep_types": ["RAR"]}, {"directions": ["inbound"]}):
            with self.subTest(arguments=arguments):
                coerced, _ = coerce_arguments({**self._BASE, **arguments}, self._SCHEMA)
                self.assertIsNotNone(validation_error("get_data_dependencies", coerced, self._SCHEMA))

    def test_the_old_boolean_flags_are_rejected(self) -> None:
        coerced, _ = coerce_arguments({**self._BASE, "include_raw": False}, self._SCHEMA)
        self.assertIsNotNone(validation_error("get_data_dependencies", coerced, self._SCHEMA))


if __name__ == "__main__":
    unittest.main()
