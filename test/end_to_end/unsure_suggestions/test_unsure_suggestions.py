# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""End-to-end test of the unsure suggestions (discopop_explorer --unsure-suggestions): loops which are not
parallelizable only because of a few dependencies between their iterations are written to
explorer/unsure_suggestions.json, and nowhere else. See design/agent_checked_suggestions.md."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set

from test.end_to_end.pipeline import _environment, _run, build_and_profile

HERE = Path(__file__).parent

APPEND_LOOP = 17
RANDOM_LOOP = 21
INDEPENDENT_LOOP = 25
REDUCTION_LOOP = 29


def _line(location: str) -> int:
    return int(location.split(":")[1])


class TestUnsureSuggestions(unittest.TestCase):
    dot_discopop: Path
    without: Dict[str, Any]
    with_unsure: Dict[str, Any]
    unsure: Dict[str, Any]
    patches_without: Set[str]
    patches_with_unsure: Set[str]

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="discopop_e2e_")
        cls.addClassCleanup(tmp.cleanup)
        cls.dot_discopop = build_and_profile(HERE / "src", Path(tmp.name) / "src")
        env = _environment(cls.dot_discopop.parent)
        explorer = cls.dot_discopop / "explorer"
        patches = cls.dot_discopop / "patch_generator"

        _run("explorer", "discopop_explorer", cls.dot_discopop, env)
        cls.without = json.loads((explorer / "patterns.json").read_text())
        cls.patches_without = {p.name for p in patches.iterdir()}
        cls.unsure_file_without_flag = (explorer / "unsure_suggestions.json").exists()

        _run("explorer", "discopop_explorer --unsure-suggestions", cls.dot_discopop, env)
        cls.with_unsure = json.loads((explorer / "patterns.json").read_text())
        cls.patches_with_unsure = {p.name for p in patches.iterdir()}
        cls.unsure = json.loads((explorer / "unsure_suggestions.json").read_text())

    def _unsure_at(self, line: int) -> List[Dict[str, Any]]:
        return [s for s in self.unsure["suggestions"] if _line(s["start_line"]) == line]

    @staticmethod
    def _ids(patterns: Dict[str, Any]) -> Dict[int, Any]:
        return {
            entry["pattern_id"]: (key, entry["start_line"])
            for key, entries in patterns["patterns"].items()
            if isinstance(entries, list)
            for entry in entries
            if isinstance(entry, dict) and "pattern_id" in entry
        }

    def test_nothing_is_written_without_the_option(self) -> None:
        self.assertFalse(self.unsure_file_without_flag)

    def test_the_append_and_the_random_number_loops_are_unsure(self) -> None:
        self.assertEqual(len(self._unsure_at(APPEND_LOOP)), 1, self.unsure)
        self.assertEqual(len(self._unsure_at(RANDOM_LOOP)), 1, self.unsure)

    def test_the_blockers_are_the_dependencies_between_iterations(self) -> None:
        [random_loop] = self._unsure_at(RANDOM_LOOP)
        # the global, by its mangled name (_ZL5state)
        variables = {a["variable"] for b in random_loop["blockers"] for a in b["accesses"]}
        self.assertTrue(any("state" in v for v in variables), variables)
        for suggestion in self.unsure["suggestions"]:
            self.assertGreater(len(suggestion["blockers"]), 0)
            self.assertLessEqual(len(suggestion["blockers"]), self.unsure["max_blockers"])

    def test_the_region_covers_the_whole_loop(self) -> None:
        [append_loop] = self._unsure_at(APPEND_LOOP)
        [random_loop] = self._unsure_at(RANDOM_LOOP)
        self.assertEqual((append_loop["region"]["start_line"], append_loop["region"]["end_line"]), (17, 19))
        self.assertEqual((random_loop["region"]["start_line"], random_loop["region"]["end_line"]), (21, 23))

    def test_parallelizable_loops_are_suggestions_not_unsure(self) -> None:
        do_all_lines = {_line(p["start_line"]) for p in self.with_unsure["patterns"]["do_all"]}
        reduction_lines = {_line(p["start_line"]) for p in self.with_unsure["patterns"]["reduction"]}
        self.assertIn(INDEPENDENT_LOOP, do_all_lines)
        self.assertIn(REDUCTION_LOOP, reduction_lines)
        self.assertEqual(self._unsure_at(INDEPENDENT_LOOP), [])
        self.assertEqual(self._unsure_at(REDUCTION_LOOP), [])

    def test_the_suggestions_and_their_ids_are_unchanged(self) -> None:
        self.assertEqual(self._ids(self.with_unsure), self._ids(self.without))
        self.assertEqual(self.patches_with_unsure, self.patches_without)

    def test_unsure_suggestions_are_not_among_the_suggestions(self) -> None:
        safe_ids = set(self._ids(self.with_unsure))
        unsure_ids = {s["pattern_id"] for s in self.unsure["suggestions"]}
        self.assertTrue(unsure_ids)
        self.assertEqual(unsure_ids & safe_ids, set())
        # allocated after all suggestions
        self.assertGreater(min(unsure_ids), max(safe_ids))
        self.assertEqual({str(i) for i in unsure_ids} & self.patches_with_unsure, set())


if __name__ == "__main__":
    unittest.main()
