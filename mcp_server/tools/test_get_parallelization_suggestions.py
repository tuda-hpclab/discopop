# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from discopop_explorer.classes.patterns.PatternDecisions import CodeRegion, PatternDecisionLog
from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import get_parallelization_suggestions, task_groups
from mcp_server.tools.fft_task_groups_fixture import ENTRIES
from mcp_server.tools.helpers import ToolContext


def _patch(line: int, pragma: str) -> str:
    return (
        f"--- original/main.cpp\n+++ main.cpp\n@@ -{line},6 +{line},7 @@\n"
        f"+  {pragma}\n   for (int i = 0; i < N; i++) {{\n"
    )


def _loop(csid: int, line: int, hotness: str, longest: float) -> dict[str, Any]:
    runtimes = [longest / 10, longest]
    return {
        "csid": csid,
        "typ": "LOOP",
        "fid": 1,
        "lineNum": line,
        "name": "",
        "runtimes": runtimes,
        "hotness": hotness,
        "avr": sum(runtimes) / 2,
        "minVal": runtimes[0],
        "maxVal": longest,
        "ratio": 0.1,
    }


DETECTOR = "doall_reduction"
TYPES = ("doall", "reduction")


class _Pattern:
    def __init__(self, node_id: str, pattern_id: int) -> None:
        self.node_id = node_id
        self.pattern_id = pattern_id


_MAIN = {**_loop(9, 1, "YES", 10.0), "typ": "FUNCTION", "name": "main"}


class TestGetParallelizationSuggestions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "main.cpp"
        self.source.write_text("int main() {}\n")
        self.dot_discopop = Path(self.project_path) / ".discopop"
        (self.dot_discopop / "explorer").mkdir(parents=True)
        (self.dot_discopop / "hotspot_detection").mkdir(parents=True)
        (self.dot_discopop / "FileMapping.txt").write_text(f"1\t{self.source}\n")
        self.ctx = ToolContext(debug=False)
        # 3: a cold loop, 5: a hotspot reduction, 7: a potential hotspot, without any competitor on its code
        self.__suggest(
            {
                3: (30, "doall", "#pragma omp parallel for firstprivate(n)"),
                5: (10, "reduction", "#pragma omp parallel for reduction(+:sum)"),
                7: (20, "doall", "#pragma omp parallel for shared(a)"),
            }
        )
        self.__hotspots([_MAIN, _loop(1, 10, "YES", 9.0), _loop(2, 20, "MAYBE", 3.0), _loop(3, 30, "NO", 0.01)])

    def __suggest(self, suggestions: dict[int, tuple[int, str, str]]) -> None:
        patterns: dict[str, list[dict[str, Any]]] = {"do_all": [], "reduction": []}
        for pid, (line, kind, pragma) in suggestions.items():
            key = "reduction" if kind == "reduction" else "do_all"
            patterns[key].append({"pattern_id": pid, "start_line": f"1:{line}"})
            patch_dir = self.dot_discopop / "patch_generator" / str(pid)
            patch_dir.mkdir(parents=True, exist_ok=True)
            (patch_dir / "1.patch").write_text(_patch(line, pragma))
        (self.dot_discopop / "explorer" / "patterns.json").write_text(json.dumps({"patterns": patterns}))

    def __hotspots(self, regions: list[dict[str, Any]]) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))

    def __handle(self, **arguments: Any) -> str:
        return get_parallelization_suggestions.handle({"project_path": self.project_path, **arguments}, self.ctx)[
            0
        ].text

    def test_the_suggestions_come_hottest_first_with_their_weight_and_pragma(self) -> None:
        lines = self.__handle().splitlines()
        self.assertEqual(lines[0], "3 parallelization suggestions, hottest first:")
        self.assertEqual(
            lines[1],
            "Suggestion 5: Hotspot Loop main.cpp:10 (9.00 s, 90% of runtime): reduction, "
            "#pragma omp parallel for reduction(+:sum)",
        )
        self.assertEqual(
            lines[2],
            "Suggestion 7: Potential Hotspot Loop main.cpp:20 (3.00 s, 30% of runtime): doall, "
            "#pragma omp parallel for shared(a)",
        )
        # code that is no hotspot is described by its kind, with what was measured
        self.assertEqual(
            lines[3],
            "Suggestion 3: Loop main.cpp:30 (0.01 s, 0% of runtime): doall, #pragma omp parallel for firstprivate(n)",
        )

    def test_the_limit_says_how_many_suggestions_are_not_shown(self) -> None:
        lines = self.__handle(limit=1).splitlines()
        self.assertEqual(len([line for line in lines if line.startswith("Suggestion")]), 1)
        self.assertIn("2 more suggestions not shown (limit=1)", self.__handle(limit=1))
        self.assertNotIn("not shown", self.__handle(limit=3))

    def test_the_default_limit_is_fixed(self) -> None:
        self.__suggest({pid: (pid, "doall", "#pragma omp parallel for") for pid in range(1, 16)})
        text = self.__handle()
        self.assertEqual(text.count("\nSuggestion "), get_parallelization_suggestions.DEFAULT_LIMIT)
        self.assertIn("5 more suggestions not shown", text)

    def test_suggestions_without_hotspot_results_are_listed_unweighted(self) -> None:
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").unlink()
        text = self.__handle()
        self.assertIn("Suggestion 5: Loop main.cpp:10: reduction", text)

    def test_a_file_filter_takes_absolute_and_relative_paths(self) -> None:
        for path in (str(self.source), "main.cpp"):
            self.assertIn("3 parallelization suggestions", self.__handle(file_path=path))
        self.assertIn("is not part of the analysed program", self.__handle(file_path="other.cpp"))

    def test_nested_and_alternative_suggestions_are_marked(self) -> None:
        log = PatternDecisionLog()
        log.ran(DETECTOR, TYPES)
        # the reduction covers the whole loop nest, the doall its inner loop; a second doall is the
        # same code as the first one
        log.consider(DETECTOR, TYPES, CodeRegion("1:10", 1, 10, 50, "loop"))
        log.consider(DETECTOR, TYPES, CodeRegion("1:20", 1, 20, 25, "loop"))
        log.consider(DETECTOR, TYPES, CodeRegion("1:21", 1, 20, 25, "loop"))
        log.finalize(
            DETECTOR, [cast(Any, _Pattern("1:10", 5)), cast(Any, _Pattern("1:20", 7)), cast(Any, _Pattern("1:21", 3))]
        )
        log.save(str(self.dot_discopop / "explorer" / "pattern_decisions.json"))

        lines = {line.split(":")[0]: line for line in self.__handle().splitlines() if line.startswith("Suggestion")}
        self.assertIn("Loop main.cpp:10-50", lines["Suggestion 5"])
        self.assertIn("main.cpp:20-25", lines["Suggestion 7"])
        self.assertTrue(lines["Suggestion 7"].endswith("nested in suggestion 5; alternative to suggestion 3"))
        self.assertTrue(lines["Suggestion 3"].endswith("nested in suggestion 5; alternative to suggestion 7"))
        self.assertNotIn("nested in", lines["Suggestion 5"])

    def test_a_region_that_is_not_a_loop_is_named_by_its_kind_and_weighed_as_that_kind(self) -> None:
        # a function region at the line of a (cold) loop must not take the loop's weight, nor the other way round
        self.__suggest({9: (40, "doall", "#pragma omp task")})
        self.__hotspots(
            [_MAIN, {**_loop(5, 40, "YES", 8.0), "typ": "FUNCTION", "name": "work"}, _loop(6, 40, "NO", 0.01)]
        )
        log = PatternDecisionLog()
        log.ran(DETECTOR, TYPES)
        log.consider(DETECTOR, TYPES, CodeRegion("1:40", 1, 40, 60, "function"))
        log.finalize(DETECTOR, [cast(Any, _Pattern("1:40", 9))])
        log.save(str(self.dot_discopop / "explorer" / "pattern_decisions.json"))

        [line] = [text for text in self.__handle().splitlines() if text.startswith("Suggestion 9")]
        self.assertTrue(line.startswith("Suggestion 9: Hotspot Function main.cpp:40-60 (8.00 s, 80% of runtime)"))

    def test_the_closing_hint_is_not_specific_to_loops_or_to_a_pragma_alone(self) -> None:
        hint = self.__handle().splitlines()[-1]
        self.assertNotIn("loop", hint.lower())
        self.assertIn("change", hint)

    def test_the_description_does_not_limit_suggestions_to_loops(self) -> None:
        description = get_parallelization_suggestions.TOOL.description or ""
        self.assertNotIn("loop", description.lower())

    def test_no_suggestions_are_reported_as_such(self) -> None:
        for patch in (self.dot_discopop / "patch_generator").glob("*/1.patch"):
            patch.unlink()
        self.assertTrue(self.__handle().startswith("No parallelization suggestions."))

    def test_without_an_analysis_the_call_names_the_tool_that_makes_one(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            text = get_parallelization_suggestions.handle({"project_path": empty}, self.ctx)[0].text
        self.assertIn("gather_data", json.loads(text)["message"])

    def test_the_schema_accepts_what_it_documents(self) -> None:
        schema = get_parallelization_suggestions.TOOL.inputSchema
        arguments, _ = coerce_arguments({"project_path": "/p", "limit": "5"}, schema)
        self.assertEqual(arguments["limit"], 5)
        self.assertIsNone(validation_error("get_parallelization_suggestions", arguments, schema))


FIB = """\
#include <stdio.h>

long long fib(int n)
{
    long long x, y;
    if (n < 2)
        return n;
    x = fib(n - 1);
    y = fib(n - 2);
    return x + y;
}
"""


def _task(pid: int, start: int, end: int, **dependences: list[str]) -> dict[str, Any]:
    return {
        "pattern_id": pid,
        "type": "TASK",
        "region_start_line": str(start),
        "region_end_line": str(end),
        **dependences,
    }


class TestTaskGroups(unittest.TestCase):
    """Task groups as the explorer writes them for BOTS fib: one region and two tasks, patch for the region only."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.project_path = self._tmp_dir.name
        self.source = Path(self.project_path) / "fib.c"
        self.source.write_text(FIB)
        self.dot_discopop = Path(self.project_path) / ".discopop"
        (self.dot_discopop / "explorer").mkdir(parents=True)
        (self.dot_discopop / "hotspot_detection").mkdir(parents=True)
        (self.dot_discopop / "FileMapping.txt").write_text(f"3\t{self.source}\n")
        self.ctx = ToolContext(debug=False)
        self.__group([_task(3, 8, 8), _task(4, 9, 9)], 8, 9)
        # the function starts one line later in the hotspot detection than in the side-effect export
        self.__export([{"file_id": 3, "name": "fib", "start_line": 3, "end_line": 11}])
        function = {**_loop(1, 4, "MAYBE", 2.0), "fid": 3, "typ": "FUNCTION", "name": "fib"}
        main = {**_loop(2, 1, "YES", 10.0), "fid": 3, "typ": "FUNCTION", "name": "main"}
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").write_text(
            json.dumps({"code_regions": [main, function]})
        )

    def __group(
        self,
        tasks: list[dict[str, Any]],
        start: int,
        end: int,
        loop_start_line: str = "",
        data_flow: dict[str, Any] | None = None,
    ) -> None:
        region = {
            **(data_flow or {}),
            **({"loop_start_line": loop_start_line} if loop_start_line else {}),
            "pattern_id": 5,
            "type": "PARALLELREGION",
            "start_line": "3:4",
            "region_start_line": str(start),
            "region_end_line": str(end),
            "contains_patterns": [t["pattern_id"] for t in tasks],
        }
        (self.dot_discopop / "explorer" / "patterns.json").write_text(
            json.dumps({"patterns": {"task": tasks + [region]}})
        )
        patch_dir = self.dot_discopop / "patch_generator" / "5"
        patch_dir.mkdir(parents=True, exist_ok=True)
        (patch_dir / "3.patch").write_text(_patch(start - 3, "#pragma omp parallel"))

    def __export(self, functions: list[dict[str, Any]]) -> None:
        with gzip.open(self.dot_discopop / "explorer" / "side_effects.json.gz", "wt") as f:
            json.dump({"functions": functions}, f)

    def __handle(self) -> str:
        return get_parallelization_suggestions.handle({"project_path": self.project_path}, self.ctx)[0].text

    def test_a_group_names_its_function_region_tasks_and_dependences_but_no_pragma(self) -> None:
        text = self.__handle()
        self.assertIn(
            "Suggestion 5: Task group in Potential Hotspot Function fib (fib.c:3-11; 2.00 s, 20% of runtime", text
        )
        self.assertIn("  parallel region: fib.c:8-9\n", text)
        self.assertIn("  task 3: fib.c:8-8   x = fib(n - 1);\n", text)
        self.assertIn("  task 4: fib.c:9-9   y = fib(n - 2);\n", text)
        self.assertIn("  dependences between the tasks: none recorded", text)
        self.assertNotIn("flag:", text)
        self.assertNotIn("#pragma omp parallel", text)
        self.assertNotIn("Loop", text)

    def test_the_join_names_the_line_after_the_region_and_what_it_reads(self) -> None:
        self.__group(
            [_task(3, 8, 8, shared=["x"], first_private=["n"]), _task(4, 9, 9, shared=["y"], first_private=["n"])],
            8,
            9,
            data_flow={
                "task_dependences": [],
                "after_dependences": [
                    {"task": 3, "variable": "x", "kind": "RAW", "line": "3:11"},
                    {"task": 4, "variable": "y", "kind": "RAW", "line": "3:11"},
                ],
            },
        )
        text = self.__handle()
        self.assertIn("  dependences between the tasks: none\n", text)
        self.assertIn(
            "  join: the tasks have to be complete before fib.c:11, which reads x (task 3), reads y (task 4)\n", text
        )
        self.assertIn("  data sharing of task 3: shared x; firstprivate n\n", text)
        self.assertIn("  data sharing of task 4: shared y; firstprivate n\n", text)

    def test_a_reader_in_the_caller_makes_the_join_before_the_function_returns(self) -> None:
        self.__group(
            [_task(3, 8, 8, first_private=["r1", "k"]), _task(4, 9, 9, first_private=["r2", "n"])],
            8,
            9,
            data_flow={
                "task_dependences": [],
                "after_dependences": [
                    {"task": 3, "variable": "r1", "kind": "RAW", "line": None, "at_return": True},
                    {"task": 4, "variable": "r2", "kind": "RAW", "line": None, "at_return": True},
                    {"task": 4, "variable": "y", "kind": "RAW", "line": "3:11", "at_return": False},
                ],
            },
        )
        text = self.__handle()
        self.assertIn(
            "  join: the tasks have to be complete before the function returns, because its caller "
            "reads r1 (task 3), reads r2 (task 4)\n",
            text,
        )
        # a reader in the function keeps its line
        self.assertIn("  join: the tasks have to be complete before fib.c:11, which reads y (task 4)\n", text)
        self.assertNotIn("no later code depends", text)

    def test_a_reader_in_the_caller_without_a_name_is_still_a_join_before_the_return(self) -> None:
        self.__group(
            [_task(3, 8, 8), _task(4, 9, 9)],
            8,
            9,
            data_flow={
                "task_dependences": [],
                "after_dependences": [{"task": 3, "variable": "", "kind": "RAW", "line": None, "at_return": True}],
            },
        )
        text = self.__handle()
        self.assertIn(
            "  join: the tasks have to be complete before the function returns, because its caller "
            "reads what the tasks write through a pointer (task 3)\n",
            text,
        )

    def test_a_task_per_iteration_names_a_join_before_the_function_returns(self) -> None:
        self.__group(
            [_task(3, 8, 8)],
            7,
            9,
            loop_start_line="3:7",
            data_flow={
                "after_dependences": [{"task": 3, "variable": "out", "kind": "RAW", "line": None, "at_return": True}]
            },
        )
        text = self.__handle()
        self.assertIn("because its caller reads out (task 3)", text)
        self.assertNotIn("wait for the tasks after the loop", text)

    def test_a_dependence_between_tasks_names_the_variable_and_marks_an_anti_dependence(self) -> None:
        self.__group(
            [_task(3, 8, 8), _task(4, 9, 9)],
            8,
            9,
            data_flow={
                "task_dependences": [
                    {"from_task": 3, "to_task": 4, "variable": "a", "kind": "RAW"},
                    {"from_task": 3, "to_task": 4, "variable": "b", "kind": "WAR"},
                ],
                "after_dependences": [],
            },
        )
        text = self.__handle()
        self.assertIn("  dependences between the tasks: task 3 -> task 4: a; task 3 -> task 4: b (anti)\n", text)
        self.assertIn("  join: no later code depends on the tasks", text)

    def test_an_output_dependence_between_tasks_is_marked_and_the_join_says_overwrites(self) -> None:
        self.__group(
            [_task(3, 8, 8), _task(4, 9, 9)],
            8,
            9,
            data_flow={
                "task_dependences": [{"from_task": 3, "to_task": 4, "variable": "d", "kind": "WAW"}],
                "after_dependences": [{"task": 4, "variable": "d", "kind": "WAW", "line": "3:11"}],
            },
        )
        text = self.__handle()
        self.assertIn("  dependences between the tasks: task 3 -> task 4: d (output)\n", text)
        self.assertIn("which overwrites d (task 4)\n", text)

    def test_reductions_and_last_private_variables_are_named_in_the_data_sharing(self) -> None:
        self.__group(
            [
                _task(3, 8, 8, shared=["x"], reduction=["+:sum"], last_private=["x"]),
                _task(4, 9, 9, reduction=["?:acc"]),
            ],
            8,
            9,
        )
        text = self.__handle()
        self.assertIn("  data sharing of task 3: shared x; reduction +:sum; lastprivate x\n", text)
        self.assertIn("  data sharing of task 4: reduction acc (operation unknown)\n", text)

    def test_a_task_per_iteration_names_the_loop_and_the_join_after_it(self) -> None:
        self.__group([_task(3, 8, 8)], 7, 9, loop_start_line="3:7")
        text = self.__handle()
        self.assertIn("  one task per iteration of the loop at fib.c:7", text)
        self.assertIn("  task body 3: fib.c:8-8   x = fib(n - 1);\n", text)
        self.assertIn("  join: wait for the tasks after the loop", text)
        self.assertNotIn("parallel region:", text)
        self.assertNotIn("fewer than two tasks", text)

    def test_a_task_per_iteration_names_the_line_after_the_loop_that_reads_the_results(self) -> None:
        self.__group(
            [{**_task(3, 8, 8), "shared": ["res"], "first_private": ["n"]}],
            7,
            9,
            loop_start_line="3:7",
            data_flow={"after_dependences": [{"task": 3, "variable": "res", "kind": "RAW", "line": "3:10"}]},
        )
        text = self.__handle()
        self.assertIn("  join: the tasks have to be complete before fib.c:10, which reads res (task 3)\n", text)
        self.assertNotIn("wait for the tasks after the loop", text)
        self.assertIn("  data sharing of task 3: shared res; firstprivate n\n", text)

    def test_a_group_inside_a_suggested_loop_is_nested_in_it_and_the_loop_contains_it(self) -> None:
        log = PatternDecisionLog()
        log.ran(DETECTOR, TYPES)
        log.consider(DETECTOR, TYPES, CodeRegion("3:7", 3, 7, 10, "loop"))
        log.finalize(DETECTOR, [cast(Any, _Pattern("3:7", 7))])
        log.save(str(self.dot_discopop / "explorer" / "pattern_decisions.json"))
        patterns = json.loads((self.dot_discopop / "explorer" / "patterns.json").read_text())
        patterns["patterns"]["do_all"] = [{"pattern_id": 7, "start_line": "3:7"}]
        (self.dot_discopop / "explorer" / "patterns.json").write_text(json.dumps(patterns))
        patch_dir = self.dot_discopop / "patch_generator" / "7"
        patch_dir.mkdir()
        (patch_dir / "3.patch").write_text(_patch(7, "#pragma omp parallel for"))

        text = self.__handle()
        self.assertIn("  nested in suggestion 7", text)
        self.assertIn("doall, #pragma omp parallel for; contains task group 5", text)

    def test_the_groups_of_a_real_run_of_bots_fft_are_flagged_where_they_look_implausible(self) -> None:
        # the task entries of patterns.json from a run of BOTS fft: 26 groups, 52 tasks
        groups = task_groups.task_groups({"task": ENTRIES})
        self.assertEqual(len(groups), 26)
        self.assertEqual(sum(len(g.tasks) for g in groups.values()), 52)
        flagged = {pid: task_groups.flags(g, []) for pid, g in groups.items()}
        self.assertEqual(flagged["2"], ["an end line is unknown"])
        self.assertEqual(flagged["8"], ["an end line is unknown"])
        self.assertEqual(flagged["5"], ["tasks 3 and 4 have the same lines"])
        self.assertEqual(flagged["81"], ["the lines of tasks 79 and 80 overlap"])
        self.assertEqual(flagged["84"], [])
        self.assertEqual(len([pid for pid, f in flagged.items() if f]), 16)

    def test_dependences_are_printed_as_the_explorer_recorded_them(self) -> None:
        self.__group([_task(3, 8, 8, out_dep=["x"]), _task(4, 9, 9, in_dep=["x"], in_out_dep=["y"])], 8, 9)
        self.assertIn("dependences between the tasks: task 3: out x; task 4: in x; in/out y", self.__handle())

    def test_without_function_table_or_hotspots_the_group_is_still_listed(self) -> None:
        (self.dot_discopop / "explorer" / "side_effects.json.gz").unlink()
        self.assertIn("Suggestion 5: Task group in fib.c\n  parallel region: fib.c:8-9", self.__handle())
        self.__export([{"file_id": 3, "name": "fib", "start_line": 3, "end_line": 11}])
        (self.dot_discopop / "hotspot_detection" / "Hotspots.json").unlink()
        self.assertIn("Task group in Function fib (fib.c:3-11; no hotspot data)", self.__handle())

    def test_overlapping_and_identical_tasks_are_flagged_not_dropped(self) -> None:
        self.__group([_task(3, 8, 8), _task(4, 8, 9)], 8, 9)
        self.assertIn("flag: the lines of tasks 3 and 4 overlap", self.__handle())
        self.__group([_task(3, 8, 8), _task(4, 8, 8)], 8, 8)
        self.assertIn("flag: tasks 3 and 4 have the same lines", self.__handle())

    def test_tasks_that_are_a_brace_or_end_in_a_return_are_flagged(self) -> None:
        self.__group([_task(3, 6, 7), _task(4, 11, 11)], 6, 11)
        text = self.__handle()
        self.assertIn("flag: task 3 ends in a return", text)
        self.assertIn("flag: task 4 is only a brace", text)

    def test_an_unknown_end_line_is_flagged(self) -> None:
        self.__group([_task(3, 8, 8), _task(4, 9, 262143)], 8, 262143)
        text = self.__handle()
        self.assertIn("flag: an end line is unknown", text)
        self.assertNotIn("+262", text)

    def test_the_closing_hint_says_that_the_agent_places_the_pragmas(self) -> None:
        self.assertIn("not where to put the pragmas", self.__handle().splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
