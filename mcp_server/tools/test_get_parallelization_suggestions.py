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
from typing import Any, cast

from discopop_explorer.classes.patterns.PatternDecisions import CodeRegion, PatternDecisionLog
from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.tools import get_parallelization_suggestions
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


if __name__ == "__main__":
    unittest.main()
