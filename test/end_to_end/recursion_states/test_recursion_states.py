# type: ignore
"""A function that calls itself from inside one of its loops: the loop accounting of the profiler and the call path
states.

The loop stack of the runtime used to compare the loop only by its id, so the entry of a recursive instance of a loop
counted as one more iteration of the loop of the caller (wrong iteration counts, and the explorer saw "fewer than two
iterations"). The entry of a deeper function level is a loop of its own now.

Still open: the call paths of the profiler are cut at a recursive call, so every recursion level shares the states of
the first one, and a dependence between an iteration of the caller (a write) and an iteration of the callee (a read)
looks like a dependence between iterations of one loop execution: the explorer rejects such loops as not parallel
(uts of the omp-tasks tests). Giving the levels states of their own was tried and dropped: the number of states grows
multiplicatively (strassen: 660 -> 2 million), and a bounded number of levels cannot be exact (see
design/task_suggestions.md, "Recursion in the call path states")."""

import json
import os
import pathlib
import re
import unittest

from test.end_to_end.pipeline import PipelineTestCase

SRC = pathlib.Path(__file__).parent / "src" / "code.cpp"


def loop_lines():
    """{name: line of the loop marked "// LOOP:<name>" in code.cpp}"""
    lines = dict()
    for number, text in enumerate(SRC.read_text().splitlines(), start=1):
        marker = re.search(r"// LOOP:(\w+)", text)
        if marker:
            lines[marker.group(1)] = number
    return lines


class TestRecursionStates(PipelineTestCase):
    SRC_DIR = SRC.parent
    ENABLE_PATTERNS = "doall,reduction"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(os.path.join(cls.profiler_dir, "dynamic_dependencies.txt")) as f:
            text = f.read()
        # {line: (total iterations, executions, average, maximum)} of the loop records of the run
        cls.loop_records = {
            int(line): tuple(int(v) for v in values)
            for _, line, *values in re.findall(r"(\d+):(\d+) BGN loop (\d+) (\d+) (\d+) (\d+)", text)
        }

    # --- the loop accounting of the runtime -----------------------------------------------------------------------

    def test_a_recursive_loop_is_counted_like_a_plain_loop_with_the_same_executions(self):
        lines = loop_lines()
        for recursive, plain in [("walk_uniform", "plain_uniform"), ("walk_zero", "plain_zero")]:
            with self.subTest(loop=recursive):
                self.assertIn(lines[plain], self.loop_records)
                self.assertEqual(self.loop_records.get(lines[recursive]), self.loop_records[lines[plain]])

    # --- the decision of the explorer -----------------------------------------------------------------------------

    @unittest.expectedFailure  # the call paths are cut at a recursive call: caller and callee share their states
    def test_a_loop_is_not_rejected_for_the_reads_of_its_recursive_callee(self):
        fill_line = loop_lines()["fill"]
        with open(os.path.join(self.dot_discopop, "explorer", "pattern_decisions.json")) as f:
            decisions = json.load(f)["decisions"]
        reasons = [
            reason["kind"]
            for decision in decisions
            if decision["region"]["start_line"] == fill_line
            for reason in decision["reasons"]
        ]
        self.assertNotIn("loop_carried_dependency", reasons)

    def notes_of(self, loop_name):
        """the kinds of the notes of the explorer on the loop"""
        line = loop_lines()[loop_name]
        with open(os.path.join(self.dot_discopop, "explorer", "pattern_decisions.json")) as f:
            decisions = json.load(f)["decisions"]
        return [n["kind"] for d in decisions if d["region"]["start_line"] == line for n in d.get("notes", [])]

    def test_a_loop_which_calls_its_own_function_is_noted(self):
        # whatever the outcome: the fill loop is rejected today, the loops of walk_uniform are accepted or not
        self.assertEqual(self.notes_of("fill"), ["recursion_in_loop"])
        self.assertEqual(self.notes_of("walk_uniform"), ["recursion_in_loop"])
        self.assertEqual(self.notes_of("walk_zero"), ["recursion_in_loop"])

    def test_a_loop_without_a_recursive_call_is_not_noted(self):
        # a loop in a function that is called from a recursive one is no loop with recursive calls
        self.assertEqual(self.notes_of("plain_uniform"), [])
        self.assertEqual(self.notes_of("plain_zero"), [])
