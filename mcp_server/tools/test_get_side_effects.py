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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from discopop_explorer.side_effects.result import Effect, EffectSite, FunctionInfo, OutsideName, SideEffects
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

    def __call(self, index: Any, problem: Optional[SideEffectDataProblem] = None, **arguments: Any) -> str:
        arguments.setdefault("function", "f")
        with mock.patch.object(self.ctx, "get_side_effect_index", return_value=(index, problem)):
            return get_side_effects.handle({"project_path": self.project, **arguments}, self.ctx)[0].text

    def __query(self, effects: list[Effect], **arguments: Any) -> str:
        extra = arguments.pop("result_extra", {})
        return self.__call(FakeIndex([_function()], {"1:5": _result(effects, **extra)}), **arguments)

    def __lines(self, effects: list[Effect], **arguments: Any) -> list[str]:
        return self.__query(effects, **arguments).splitlines()

    # --- name resolution

    def test_a_unique_name_is_resolved_with_or_without_signature(self) -> None:
        index = FakeIndex([_function()], {"1:5": _result([])})
        for name in ("f", "f(int*)", "_Zf"):
            with self.subTest(name=name):
                self.assertEqual(self.__call(index, function=name).splitlines()[0], f"f(int*) ({MAIN_FILE}:10-20)")

    def test_the_definition_is_shown_relative_to_the_project(self) -> None:
        index = FakeIndex([_function(file=f"{self.project}/src/main.cpp")], {"1:5": _result([])})
        index.results["1:5"] = _result([], function=_function(file=f"{self.project}/src/main.cpp"))
        self.assertEqual(self.__call(index).splitlines()[0], "f(int*) (src/main.cpp:10-20)")

    def test_an_ambiguous_name_lists_the_candidates(self) -> None:
        first = _function("1:5", "f(int*)", MAIN_FILE, 10, 20)
        second = _function("2:3", "f(double)", OTHER_FILE, 3, 8)
        text = self.__call(FakeIndex([first, second], {}))
        self.assertIn("'f' matches 2 functions:", text)
        self.assertIn(f"- f(int*) ({MAIN_FILE}:10-20)", text)
        self.assertIn(f"- f(double) ({OTHER_FILE}:3-8)", text)
        self.assertIn("full signature", text)

    def test_file_path_and_line_pick_one_definition(self) -> None:
        first = _function("1:5", "f(int*)", MAIN_FILE, 10, 20)
        second = _function("2:3", "f(double)", OTHER_FILE, 3, 8)
        index = FakeIndex([first, second], {"1:5": _result([], function=first), "2:3": _result([], function=second)})
        text = self.__call(index, file_path=OTHER_FILE)
        self.assertTrue(text.startswith(f"f(double) ({OTHER_FILE}:3-8)"))
        self.assertTrue(self.__call(index, line=15).startswith(f"f(int*) ({MAIN_FILE}:10-20)"))
        self.assertEqual(index.computed, ["2:3", "1:5"])

    def test_a_file_or_line_that_excludes_every_definition_names_the_existing_ones(self) -> None:
        index = FakeIndex([_function()], {})
        data = json.loads(self.__call(index, line=99))
        self.assertEqual(data["status"], "error")
        self.assertIn("at line 99", data["message"])
        self.assertIn(f"f(int*) ({MAIN_FILE}:10-20)", data["message"])

    def test_an_unknown_name_says_how_names_are_matched(self) -> None:
        data = json.loads(self.__call(FakeIndex([_function()], {}), function="nope"))
        self.assertEqual(data["status"], "error")
        self.assertIn("No profiled function named 'nope'", data["message"])
        self.assertIn("with or without signature", data["next_step"])

    # --- the answer

    def test_the_answer_is_a_text_with_the_verdict_first_and_the_profiled_inputs_last(self) -> None:
        lines = self.__lines([_effect("g", access="write")], result_extra={"pure_on_observed_inputs": False})
        self.assertEqual(lines[1], "Not pure: it writes g.")
        self.assertEqual(lines[-1], "Valid for the profiled inputs only.")

    def test_the_verdicts(self) -> None:
        cases = [
            (True, False, [], "Pure on the profiled inputs: it writes nothing and reads only its own parameters"),
            (False, False, [_effect("a"), _effect("b", kind="parameter")], "Not pure: it writes a, b."),
            (False, True, [], "Not pure: it performs file I/O."),
            (False, True, [_effect("a")], "Not pure: it writes a and it performs file I/O."),
            (None, False, [], "Purity is undecided."),
            (None, True, [], "Purity is undecided. It performs file I/O."),
        ]
        for pure, io, effects, expected in cases:
            with self.subTest(pure=pure, io=io):
                lines = self.__lines(effects, result_extra={"pure_on_observed_inputs": pure, "performs_file_io": io})
                self.assertTrue(lines[1].startswith(expected), lines[1])

    def test_many_written_names_are_cut_in_the_verdict(self) -> None:
        effects = [_effect(f"g{n}") for n in range(8)]
        lines = self.__lines(effects, result_extra={"pure_on_observed_inputs": False}, limit=100)
        self.assertEqual(lines[1], "Not pure: it writes g0, g1, g2, g3, g4 and 3 more.")

    def test_writes_come_before_reads_and_are_ranked_by_kind_then_depth(self) -> None:
        effects = [
            _effect("read_g", access="read"),
            _effect("w_other", kind="other"),
            _effect("w_param", kind="parameter"),
            _effect("w_callee", via=("g(int)",)),
            _effect("w_static", source="static"),
            _effect("w_own"),
        ]
        lines = self.__lines(effects, limit=100)
        names = [line.split(" ")[1] for line in lines if line.startswith("- ")]
        self.assertEqual(names, ["w_own", "w_static", "w_callee", "w_param", "w_other", "read_g"])
        self.assertEqual(lines[2], "Writes:")
        self.assertIn("Reads:", lines)

    def test_unknown_access_is_listed_apart_and_only_when_present(self) -> None:
        self.assertNotIn("access unknown", self.__query([_effect("a")]))
        text = self.__query([_effect("a"), _effect("u", access="unknown", source="static")])
        self.assertIn(
            "Referenced in the code, access unknown:\n- u (global, referenced in the code, not observed)", text
        )

    def test_the_limit_keeps_the_most_significant_effects_and_counts_the_rest(self) -> None:
        effects = [_effect("r1", access="read"), _effect("w1"), _effect("w2"), _effect("r2", access="read")]
        text = self.__query(effects, limit=2)
        self.assertIn("- w1 ", text)
        self.assertIn("- w2 ", text)
        self.assertNotIn("- r1 ", text)
        self.assertIn("2 more effects not shown (limit=2); pass a larger limit.", text)
        self.assertNotIn("not shown", self.__query(effects, limit=4))

    def test_the_default_limit_is_fixed(self) -> None:
        text = self.__query([_effect(f"g{n:02d}") for n in range(30)])
        self.assertEqual(text.count("\n- "), get_side_effects.DEFAULT_LIMIT)
        self.assertIn("10 more effects not shown", text)

    def test_no_effects_are_said_so_and_unknown_effects_too(self) -> None:
        self.assertIn("No effects.", self.__query([]))
        text = self.__query([], result_extra={"coverage": "not_executed"})
        self.assertIn("No effects are known.", text)

    # --- one entry

    def test_an_entry_names_kind_qualifiers_aliases_and_lines(self) -> None:
        effect = _effect(
            "p",
            kind="parameter",
            through_pointer=True,
            member_of="s",
            outside_names=[OutsideName("rij", 1), OutsideName("pos", 1)],
            lines=(12, 15),
        )
        self.assertIn(
            "- p (parameter, through pointer, member of s), also called rij, pos: line 12; line 15",
            self.__query([effect]),
        )

    def test_aliases_in_other_files_carry_the_file(self) -> None:
        effect = _effect("p", kind="parameter", outside_names=[OutsideName("rij", 1), OutsideName("pos", 2)])
        self.assertIn(f"p (parameter), also called rij, pos (in {OTHER_FILE}):", self.__query([effect]))

    def test_data_that_was_only_referenced_is_marked(self) -> None:
        self.assertIn("(global, referenced in the code, not observed)", self.__query([_effect("g", source="static")]))

    def test_sites_name_the_call_chain_and_collapse_recursion(self) -> None:
        effect = _effect("g", via=("r(int)",) * 5 + ("w(int)",))
        self.assertIn("line 12 via r(int) x5 > w(int)", self.__query([effect]))

    def test_sites_in_other_files_carry_the_file(self) -> None:
        effect = _effect("g", lines=(7,), file_id=2)
        self.assertIn(f"g (global): {OTHER_FILE}:7", self.__query([effect]))

    def test_the_sites_of_the_function_itself_come_first_and_are_capped(self) -> None:
        effect = Effect(
            name="g",
            kind="global",
            access="write",
            source="observed",
            sites=[
                EffectSite(file_id=1, line=30, via=("h()",)),
                EffectSite(file_id=1, line=14, via=()),
                EffectSite(file_id=1, line=12, via=()),
                EffectSite(file_id=1, line=40, via=()),
                EffectSite(file_id=1, line=50, via=()),
            ],
        )
        self.assertIn("g (global): line 12; line 14; line 40; 2 more", self.__query([effect]))

    # --- caveats

    def test_coverage_caveats(self) -> None:
        text = self.__query([], result_extra={"coverage": "not_executed"})
        self.assertIn("Caveat: Never executed during profiling", text)
        self.assertIn(
            "Caveat: Executed, but none of its calls", self.__query([], result_extra={"coverage": "untracked"})
        )
        self.assertIn(
            "Caveat: Some calls could not be followed", self.__query([], result_extra={"coverage": "partial"})
        )
        self.assertNotIn("Caveat", self.__query([]))

    def test_the_caveats_do_not_point_at_tools_that_are_gone(self) -> None:
        for text in get_side_effects.COVERAGE_TEXT.values():
            self.assertNotIn("get_data_dependencies", text)

    def test_unprofiled_calls_are_listed_and_capped(self) -> None:
        calls = [f"lib{n}" for n in range(8)]
        text = self.__query([], result_extra={"unprofiled_calls": calls})
        self.assertIn(
            "calls whose accesses were not observed (library code): lib0, lib1, lib2, lib3, lib4 and 3 more.", text
        )

    def test_missing_source_facts_are_noted_once(self) -> None:
        text = self.__query([], result_extra={"ast_facts": False})
        self.assertEqual(text.count("No source-level facts"), 1)
        own = "No source-level facts for this function."
        text = self.__query([], result_extra={"ast_facts": False, "notes": [own]})
        self.assertEqual(text.count("No source-level facts"), 1)
        self.assertIn(f"Note: {own}", text)

    # --- arguments, description and imports

    def test_the_schema_has_the_limit_and_no_filters(self) -> None:
        schema = get_side_effects.TOOL.inputSchema
        self.assertEqual(set(schema["properties"]), {"project_path", "function", "file_path", "line", "limit"})
        arguments, _ = coerce_arguments({"project_path": "/p", "function": "f", "limit": "5", "line": "7"}, schema)
        self.assertEqual((arguments["limit"], arguments["line"]), (5, 7))
        self.assertIsNone(validation_error(get_side_effects.TOOL_NAME, arguments, schema))

    def test_the_description_fits_before_the_client_cuts_it_off(self) -> None:
        # like the server instructions (test_server.py): clients show only the first 2048 characters
        self.assertLessEqual(len(get_side_effects.TOOL.description or ""), 2048)

    def test_the_tool_module_imports_without_discopop_explorer(self) -> None:
        # the server must start without the explorer installed; it is only needed on a call
        code = (
            "import sys; sys.modules['discopop_explorer'] = None; "
            "import mcp_server.tools.get_side_effects, mcp_server.tools.helpers"
        )
        root = Path(__file__).resolve().parents[2]
        proc = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- export problems

    def test_an_export_problem_becomes_an_error_with_a_next_step(self) -> None:
        problem = SideEffectDataProblem("stale", "The data is stale. Run gather_data again.", "Run gather_data.")
        data = json.loads(self.__call(None, problem))
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
