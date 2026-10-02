# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unit tests of get_side_effects and ToolContext.get_side_effect_index.

The analysis is replaced by a fake index returning hand-built results, so that
these tests check only what the tool adds: resolution, filters, ranking, cutting,
wording and the handling of the export file.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from discopop_explorer.side_effects.result import Effect, EffectSite, FunctionInfo, SideEffects
from discopop_explorer.side_effects.schema import FORMAT_VERSION, dependency_file_info, export_path, save_export
from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import get_side_effects
from mcp_server.tools.helpers import SideEffectDataProblem, ToolContext, dynamic_dependencies_path

MAIN_FILE = "/src/main.cpp"
OTHER_FILE = "/src/util.h"


def _function(
    fid: str = "1:5", display_name: str = "f(int*)", file: str = MAIN_FILE, start: int = 10, end: int = 20
) -> FunctionInfo:
    file_id = 1 if file == MAIN_FILE else 2
    return FunctionInfo(
        id=fid,
        name="_Z" + display_name.split("(")[0],
        display_name=display_name,
        file=file,
        file_id=file_id,
        start_line=start,
        end_line=end,
    )


def _effect(
    name: str,
    kind: str = "global",
    access: str = "write",
    source: str = "observed",
    via: tuple[str, ...] = (),
    lines: tuple[int, ...] = (12,),
    file_id: int = 1,
    **extra: Any,
) -> Effect:
    sites = [EffectSite(file_id=file_id, line=line, via=via) for line in lines]
    return Effect(name=name, kind=kind, access=access, source=source, sites=sites, **extra)  # type: ignore[arg-type]


def _result(
    effects: list[Effect],
    coverage: str = "executed",
    function: Optional[FunctionInfo] = None,
    **extra: Any,
) -> SideEffects:
    values: dict[str, Any] = {
        "function": function or _function(),
        "coverage": coverage,
        "pure_on_observed_inputs": None,
        "performs_file_io": False,
        "unprofiled_calls": [],
        "effects": effects,
        "unmapped_records": 0,
        "contributing_callees": [],
        "ast_facts": True,
    }
    values.update(extra)
    return SideEffects(**values)


class FakeIndex:
    """Stands in for SideEffectIndex: name matching with or without signature, results by id."""

    def __init__(self, functions: list[FunctionInfo], results: dict[str, SideEffects]) -> None:
        self.functions = functions
        self.results = results
        self.export: dict[str, Any] = {"files": {"1": MAIN_FILE, "2": OTHER_FILE}}
        self.computed: list[str] = []

    def find_functions(
        self, name: str, file_path: Optional[str] = None, line: Optional[int] = None
    ) -> list[FunctionInfo]:
        return [
            info for info in self.functions if name in (info.name, info.display_name, info.display_name.split("(")[0])
        ]

    def compute(self, function_id: str) -> SideEffects:
        self.computed.append(function_id)
        return self.results[function_id]


class TestGetSideEffects(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project = self._tmp_dir.name
        self.ctx = ToolContext(debug=False)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __call(self, index: Any, problem: Optional[SideEffectDataProblem] = None, **arguments: Any) -> Any:
        arguments.setdefault("function", "f")
        with mock.patch.object(self.ctx, "get_side_effect_index", return_value=(index, problem)):
            return json.loads(get_side_effects.handle({"project_path": self.project, **arguments}, self.ctx)[0].text)

    def __query(self, effects: list[Effect], **arguments: Any) -> Any:
        extra = arguments.pop("result_extra", {})
        return self.__call(FakeIndex([_function()], {"1:5": _result(effects, **extra)}), **arguments)

    # --- name resolution

    def test_a_unique_name_is_resolved_with_or_without_signature(self) -> None:
        index = FakeIndex([_function()], {"1:5": _result([])})
        for name in ("f", "f(int*)", "_Zf"):
            with self.subTest(name=name):
                data = self.__call(index, function=name)
                self.assertEqual(data["status"], "success", data)
                self.assertEqual(
                    data["function"], {"name": "f(int*)", "file": MAIN_FILE, "start_line": 10, "end_line": 20}
                )

    def test_an_ambiguous_name_lists_the_candidates(self) -> None:
        first = _function("1:5", "f(int*)", MAIN_FILE, 10, 20)
        second = _function("2:3", "f(double)", OTHER_FILE, 3, 8)
        index = FakeIndex([first, second], {})
        data = self.__call(index, function="f")
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(data["num_candidates"], 2)
        self.assertEqual(
            data["candidates"],
            [
                {"name": "f(int*)", "file": MAIN_FILE, "start_line": 10, "end_line": 20},
                {"name": "f(double)", "file": OTHER_FILE, "start_line": 3, "end_line": 8},
            ],
        )
        self.assertIn("file_path", data["next_step"])
        self.assertEqual(index.computed, [])

    def test_file_path_and_line_pick_one_definition(self) -> None:
        source = Path(self.project) / "a.cpp"
        source.write_text("\n")
        first = _function("1:5", "f(int*)", str(source), 10, 20)
        second = _function("1:30", "f(double)", str(source), 30, 40)
        third = _function("2:3", "f(long)", OTHER_FILE, 3, 8)
        index = FakeIndex([first, second, third], {"1:5": _result([], function=first), "1:30": _result([])})
        # a relative file_path is taken relative to the project
        data = self.__call(index, file_path="a.cpp", line=35)
        self.assertEqual(data["status"], "success", data)
        self.assertEqual(index.computed, ["1:30"])
        data = self.__call(index, file_path=str(source))
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(data["num_candidates"], 2)
        data = self.__call(index, line=15)
        self.assertEqual(data["status"], "success", data)
        self.assertEqual(index.computed[-1], "1:5")

    def test_a_file_or_line_that_excludes_every_definition_names_the_existing_ones(self) -> None:
        data = self.__call(FakeIndex([_function()], {}), line=99)
        self.assertEqual(data["status"], "error")
        self.assertIn("at line 99", data["message"])
        self.assertIn("main.cpp", data["message"])
        self.assertIn("next_step", data)

    def test_an_unknown_name_says_how_names_are_matched(self) -> None:
        data = self.__call(FakeIndex([_function()], {}), function="g")
        self.assertEqual(data["status"], "error")
        self.assertIn("'g'", data["message"])
        self.assertIn("signature", data["next_step"])

    # --- ranking and cutting

    def test_ranking_order(self) -> None:
        effects = [
            _effect("z_static", source="static"),
            _effect("other", kind="other"),
            _effect("deep", via=("a", "b")),
            _effect("param", kind="parameter"),
            _effect("shallow", via=("a",)),
            _effect("b_global"),
            _effect("a_global"),
            _effect("read_global", access="read"),
            _effect("read_param", kind="parameter", access="read"),
        ]
        data = self.__query(effects)
        self.assertEqual(
            [entry["name"] for entry in data["writes"]],
            ["a_global", "b_global", "z_static", "shallow", "deep", "param", "other"],
        )
        self.assertEqual([entry["name"] for entry in data["reads"]], ["read_global", "read_param"])
        self.assertFalse(data["truncated"])
        self.assertNotIn("next_step", data)

    def test_an_own_site_ranks_an_effect_with_callee_sites_as_own(self) -> None:
        mixed = _effect("mixed")
        mixed.sites.append(EffectSite(file_id=1, line=50, via=("a", "b", "c")))
        data = self.__query([_effect("callee_only", via=("a",)), mixed])
        self.assertEqual([entry["name"] for entry in data["writes"]], ["mixed", "callee_only"])

    def test_a_cut_keeps_the_highest_ranked_entries_and_the_full_summary(self) -> None:
        effects = [_effect(f"r{i:03}", access="read") for i in range(get_side_effects.MAX_EFFECTS)]
        effects += [_effect(f"w{i}", kind="parameter") for i in range(5)]
        data = self.__query(effects)
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["writes"]) + len(data["reads"]), get_side_effects.MAX_EFFECTS)
        self.assertEqual(len(data["writes"]), 5)
        self.assertNotIn(f"r{get_side_effects.MAX_EFFECTS - 1:03}", [entry["name"] for entry in data["reads"]])
        self.assertEqual(data["summary"]["num_effects"], get_side_effects.MAX_EFFECTS + 5)
        self.assertEqual(data["summary"]["by_access"], {"write": 5, "read": get_side_effects.MAX_EFFECTS, "unknown": 0})
        self.assertEqual(data["summary"]["by_kind"], {"global": 100, "parameter": 5, "other": 0})
        self.assertIn(f"first {get_side_effects.MAX_EFFECTS} of {get_side_effects.MAX_EFFECTS + 5}", data["next_step"])
        self.assertIn("var_name", data["next_step"])

    def test_the_summary_names_the_contributing_callees(self) -> None:
        data = self.__query([_effect("g", via=("a", "b")), _effect("h", via=("c",)), _effect("own")])
        self.assertEqual(data["summary"]["contributing_callees"], ["b", "c"])

    def test_flags_are_passed_through(self) -> None:
        extra = {"pure_on_observed_inputs": False, "performs_file_io": True, "unprofiled_calls": ["printf"]}
        data = self.__query([], result_extra={**extra, "unmapped_records": 4})
        self.assertIs(data["pure_on_observed_inputs"], False)
        self.assertIs(data["performs_file_io"], True)
        self.assertEqual(data["unprofiled_calls"], ["printf"])
        self.assertEqual(data["unmapped_records"], 4)
        self.assertEqual(data["coverage"], "executed")

    # --- filters

    def test_access_filter_keeps_entries_of_unknown_access(self) -> None:
        effects = [_effect("w"), _effect("r", access="read"), _effect("u", access="unknown", source="static")]
        data = self.__query(effects, access="read")
        self.assertEqual(data["writes"], [])
        self.assertEqual([entry["name"] for entry in data["reads"]], ["r"])
        self.assertEqual([entry["name"] for entry in data["unknown_access"]], ["u"])
        self.assertEqual(data["summary"]["num_effects"], 2)
        data = self.__query(effects, access="write")
        self.assertEqual([entry["name"] for entry in data["writes"]], ["w"])
        self.assertEqual(data["reads"], [])
        self.assertEqual(len(data["unknown_access"]), 1)

    def test_unknown_access_is_listed_apart_and_only_when_present(self) -> None:
        data = self.__query([_effect("w")])
        self.assertNotIn("unknown_access", data)
        data = self.__query([_effect("u", access="unknown", source="static")])
        self.assertEqual(data["unknown_access"][0]["source"], "static")
        self.assertEqual(data["summary"]["by_access"]["unknown"], 1)

    def test_kinds_filter(self) -> None:
        effects = [_effect("g"), _effect("p", kind="parameter"), _effect("o", kind="other")]
        data = self.__query(effects, kinds=["parameter", "other"])
        self.assertEqual([entry["name"] for entry in data["writes"]], ["p", "o"])
        self.assertEqual(data["summary"]["by_kind"], {"global": 0, "parameter": 1, "other": 1})
        # an empty list means no restriction
        self.assertEqual(len(self.__query(effects, kinds=[])["writes"]), 3)

    def test_var_name_filter_matches_name_member_base_and_outside_names(self) -> None:
        effects = [
            _effect("buf", kind="parameter"),
            _effect("second", kind="parameter", member_of="s"),
            _effect("p", kind="parameter", outside_names=["GEPRESULT_arr"]),
            _effect("g"),
        ]
        for var_name, expected in (("buf", "buf"), ("GEPRESULT_buf", "buf"), ("s", "second"), ("arr", "p")):
            with self.subTest(var_name=var_name):
                data = self.__query(effects, var_name=var_name)
                self.assertEqual([entry["name"] for entry in data["writes"]], [expected])

    def test_without_callees_only_own_sites_remain(self) -> None:
        mixed = _effect("mixed", lines=(12,))
        mixed.sites.append(EffectSite(file_id=1, line=50, via=("a",)))
        data = self.__query([mixed, _effect("callee_only", via=("a",))], include_callees=False)
        self.assertEqual([entry["name"] for entry in data["writes"]], ["mixed"])
        self.assertEqual(data["writes"][0]["sites"], [{"line": 12, "via": None}])
        self.assertEqual(data["summary"]["contributing_callees"], [])

    def test_an_invalid_access_or_kind_is_rejected(self) -> None:
        self.assertEqual(self.__query([], access="modify")["status"], "error")
        self.assertEqual(self.__query([], kinds=["local"])["status"], "error")
        schema = get_side_effects.TOOL.inputSchema
        self.assertIsNotNone(validation_error("get_side_effects", {"project_path": "/p"}, schema))
        self.assertIsNotNone(
            validation_error("get_side_effects", {"project_path": "/p", "function": "f", "kinds": ["x"]}, schema)
        )

    def test_string_typed_arguments_are_coerced(self) -> None:
        schema = get_side_effects.TOOL.inputSchema
        arguments, _changes = coerce_arguments(
            {"project_path": "/p", "function": "f", "include_callees": "false", "line": "12"}, schema
        )
        self.assertIsNone(validation_error("get_side_effects", arguments, schema))
        self.assertIs(arguments["include_callees"], False)

    # --- sites

    def test_sites_are_capped_unless_var_name_is_given(self) -> None:
        effects = [_effect("g", lines=(15, 11, 13, 12, 14))]
        data = self.__query(effects)
        entry = data["writes"][0]
        self.assertEqual(entry["num_sites"], 5)
        self.assertEqual([site["line"] for site in entry["sites"]], [11, 12, 13])
        data = self.__query(effects, var_name="g")
        self.assertEqual([site["line"] for site in data["writes"][0]["sites"]], [11, 12, 13, 14, 15])

    def test_sites_in_other_files_carry_the_file(self) -> None:
        effect = _effect("g", lines=(12,))
        effect.sites.append(EffectSite(file_id=2, line=4, via=("helper(int)",)))
        entry = self.__query([effect])["writes"][0]
        self.assertEqual(
            entry["sites"],
            [{"line": 12, "via": None}, {"file": OTHER_FILE, "line": 4, "via": ["helper(int)"]}],
        )

    def test_entry_shape(self) -> None:
        effect = _effect(
            "second", kind="parameter", through_pointer=True, member_of="s", outside_names=["GEPRESULT_buf"]
        )
        entry = self.__query([effect])["writes"][0]
        self.assertEqual(
            entry,
            {
                "name": "second",
                "kind": "parameter",
                "through_pointer": True,
                "source": "observed",
                "member_of": "s",
                "num_sites": 1,
                "sites": [{"line": 12, "via": None}],
                "outside_names": ["GEPRESULT_buf"],
            },
        )
        plain = self.__query([_effect("g")])["writes"][0]
        self.assertNotIn("member_of", plain)
        self.assertNotIn("outside_names", plain)

    # --- notes and coverage

    def test_the_profiled_inputs_note_is_always_there(self) -> None:
        data = self.__query([])
        self.assertIn("profiled inputs", data["notes"][0])
        data = self.__query([], result_extra={"ast_facts": False, "notes": ["x", "x", "y"]})
        self.assertEqual(len(data["notes"]), 4)
        self.assertIn(get_side_effects.NO_AST_NOTE, data["notes"])

    def test_coverage_next_steps(self) -> None:
        expectations = {
            "not_executed": "never executed",
            "untracked": "could be attributed",
            "partial": "may be missing",
        }
        for coverage, phrase in expectations.items():
            with self.subTest(coverage=coverage):
                data = self.__query([], result_extra={"coverage": coverage})
                self.assertEqual(data["coverage"], coverage)
                self.assertIn(phrase, data["next_step"])
        self.assertNotIn("next_step", self.__query([], result_extra={"coverage": "executed"}))

    def test_truncation_and_coverage_next_steps_are_combined(self) -> None:
        with mock.patch.object(get_side_effects, "MAX_EFFECTS", 1):
            data = self.__query([_effect("a"), _effect("b")], result_extra={"coverage": "partial"})
        self.assertTrue(data["truncated"])
        self.assertIn("first 1 of 2", data["next_step"])
        self.assertIn("may be missing", data["next_step"])

    # --- export problems

    def test_an_export_problem_becomes_an_error_with_a_next_step(self) -> None:
        problem = SideEffectDataProblem("stale", "The data is stale. Run gather_data again.", "Run gather_data.")
        data = self.__call(None, problem)
        self.assertEqual(data["status"], "error")
        self.assertIn("gather_data", data["message"])
        self.assertEqual(data["next_step"], "Run gather_data.")


def _export(dependency_file: Any, ignore_states: bool = False, version: int = FORMAT_VERSION) -> Any:
    return {
        "format_version": version,
        "discopop_version": "test",
        "ignore_dependency_states": ignore_states,
        "dependency_file": dependency_file,
        "files": {},
        "globals": [],
        "functions": [],
        "instances": [],
        "work_contexts": {},
        "records": [],
        "instruction_names": {},
        "executed_calls": [],
        "unmapped_records": {},
    }


class TestSideEffectIndexLoading(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project = self._tmp_dir.name
        self.dep_file = dynamic_dependencies_path(self.project)
        self.dep_file.parent.mkdir(parents=True)
        self.dep_file.write_text("1:1 NOM\n")
        self.ctx = ToolContext(debug=False)
        self.constructed: list[Any] = []
        constructed = self.constructed

        class _Index:
            def __init__(self, export: Any) -> None:
                self.export = export
                constructed.append(self)

        patcher = mock.patch("discopop_explorer.side_effects.analysis.SideEffectIndex", _Index)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, export: Any) -> None:
        save_export(export, export_path(self.project))

    def __load(self) -> tuple[Any, Optional[SideEffectDataProblem]]:
        return self.ctx.get_side_effect_index(self.project)

    def test_missing_export(self) -> None:
        index, problem = self.__load()
        self.assertIsNone(index)
        assert problem is not None
        self.assertEqual(problem.reason, "missing")
        self.assertIn("gather_data", problem.message)

    def test_unreadable_export(self) -> None:
        path = export_path(self.project)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not gzip")
        index, problem = self.__load()
        self.assertIsNone(index)
        assert problem is not None
        self.assertEqual(problem.reason, "unreadable")
        self.assertIn("gather_data again", problem.message)

    def test_other_format_version(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file), version=FORMAT_VERSION + 1))
        index, problem = self.__load()
        self.assertIsNone(index)
        assert problem is not None
        self.assertEqual(problem.reason, "unreadable")
        self.assertIn("format version", problem.message)

    def test_a_current_export_is_loaded_once(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file)))
        first, problem = self.__load()
        self.assertIsNone(problem)
        second, _problem = self.__load()
        self.assertIs(first, second)
        self.assertEqual(len(self.constructed), 1)

    def test_a_changed_export_is_reloaded(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file)))
        first, _problem = self.__load()
        path = export_path(self.project)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        second, problem = self.__load()
        self.assertIsNone(problem)
        self.assertIsNot(first, second)
        self.assertEqual(len(self.constructed), 2)

    def test_new_profiling_data_makes_the_export_stale(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file)))
        self.assertIsNotNone(self.__load()[0])
        # profiled again: the export is unchanged and cached, the dependency file is not
        self.dep_file.write_text("1:1 NOM\n1:2 NOM\n")
        index, problem = self.__load()
        self.assertIsNone(index)
        assert problem is not None
        self.assertEqual(problem.reason, "stale")
        self.assertIn("gather_data again", problem.message)

    def test_a_missing_dependency_file_makes_the_export_stale(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file)))
        self.dep_file.unlink()
        _index, problem = self.__load()
        assert problem is not None
        self.assertEqual(problem.reason, "stale")

    def test_an_export_without_dependency_states_is_refused(self) -> None:
        self.__write(_export(dependency_file_info(self.dep_file), ignore_states=True))
        index, problem = self.__load()
        self.assertIsNone(index)
        assert problem is not None
        self.assertEqual(problem.reason, "ignore_dependency_states")
        self.assertIn("--ignore-dependency-states", problem.message)
        self.assertEqual(self.constructed, [])

    def test_the_tool_reports_a_missing_export(self) -> None:
        data = json.loads(get_side_effects.handle({"project_path": self.project, "function": "f"}, self.ctx)[0].text)
        self.assertEqual(data["status"], "error")
        self.assertIn("gather_data", data["message"])
        self.assertIn("next_step", data)


if __name__ == "__main__":
    unittest.main()
