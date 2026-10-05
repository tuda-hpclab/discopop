# type: ignore
"""Profiles src/code.cpp and checks the profiler's loopstate_positions.txt against the source: every
loop of a function has one loopstate digit, numbered in the pre-order of the loop nesting forest, and
names its loop node in Data.xml. Covers a loop nested in an `else` inside another loop, whose exit
block carries no debug location (it used to be skipped by the loop entry/exit instrumentation), and
sibling loops in if / else, and an early return placed before an inner loop. The nesting of the loops
(from LoopInfo, independent of the basic block layout) is checked on the loopstate labels: a loop is
active only while its parent loop is active, and loops that are not nested are never active together.
The END line of a loop lies after its start, also for a loop ending an `else` arm inside another loop,
whose exit block has no debug location."""

import os
import pathlib
import re
import unittest

from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd

# {function: [start line of the loop at each loopstate position]}
EXPECTED_POSITIONS = {
    "_Z6kerneliiPdS_": [8, 13, 20, 21],
    "_Z8siblingsiPd": [32, 36, 40, 41],
    "_Z12early_returniPiPd": [50, 54],
}

# {function: [position of the parent loop of the loop at each loopstate position, or None]}
EXPECTED_PARENTS = {
    "_Z6kerneliiPdS_": [None, 0, None, 2],
    "_Z8siblingsiPd": [None, None, None, 2],
    "_Z12early_returniPiPd": [None, 0],
}


class TestMethods(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        current_dir = pathlib.Path(__file__).parent.resolve()
        self.src_dir = os.path.join(current_dir, "src")
        self.env_vars = dict(os.environ)
        self.env_vars["CC"] = "discopop_cc"
        self.env_vars["CXX"] = "discopop_cxx"
        self.env_vars["DP_PROJECT_ROOT_DIR"] = self.src_dir
        run_cmd("make", self.src_dir, self.env_vars)
        run_cmd("./prog", self.src_dir, self.env_vars)
        self.profiler_dir = os.path.join(self.src_dir, ".discopop", "profiler")

    @classmethod
    def tearDownClass(self):
        run_cmd("make veryclean", self.src_dir, self.env_vars)

    def __read_positions(self):
        positions = dict()
        with open(os.path.join(self.profiler_dir, "loopstate_positions.txt")) as f:
            for line in f:
                function, position, loop_id, loop_node_id, start_location = line.split()
                positions.setdefault(function, []).append((int(position), int(loop_id), loop_node_id, start_location))
        return positions

    def test_positions_match_the_source(self):
        positions = self.__read_positions()
        for function, lines in EXPECTED_POSITIONS.items():
            with self.subTest(function=function):
                self.assertEqual([p for p, _, _, _ in positions[function]], list(range(len(lines))))
                self.assertEqual([int(loc.split(":")[1]) for _, _, _, loc in positions[function]], lines)

    def test_digit_count_matches_the_positions(self):
        digits = dict()
        with open(os.path.join(self.profiler_dir, "stateID_to_callpath_mapping.txt")) as f:
            for function, state in re.findall(r"(\S+)_loopstate(\d+)", f.read()):
                digits.setdefault(function, set()).add(len(state))
        for function, lines in EXPECTED_POSITIONS.items():
            with self.subTest(function=function):
                self.assertEqual(digits[function], {len(lines)})

    def test_loop_node_ids_name_the_loops_of_data_xml(self):
        with open(os.path.join(self.profiler_dir, "Data.xml")) as f:
            loop_nodes = dict(re.findall(r'id="([0-9:]+)" type="2" name="[^"]*" startsAtLine = "([0-9:]+)"', f.read()))
        for function in EXPECTED_POSITIONS:
            for _, _, loop_node_id, start_location in self.__read_positions()[function]:
                with self.subTest(function=function, loop=start_location):
                    self.assertEqual(loop_nodes.get(loop_node_id), start_location)

    def test_loop_in_else_branch_is_profiled(self):
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt")) as f:
            content = f.read()
        self.assertRegex(content, r"\b1:13 BGN loop 80 10 ")

    def test_loopstates_follow_the_loop_nesting(self):
        with open(os.path.join(self.profiler_dir, "stateID_to_callpath_mapping.txt")) as f:
            labels = set(re.findall(r"(\S+)_loopstate(\d+)", f.read()))
        for function, parents in EXPECTED_PARENTS.items():

            def ancestors(position):
                result = set()
                while parents[position] is not None:
                    position = parents[position]
                    result.add(position)
                return result

            states = [digits for name, digits in labels if name == function]
            with self.subTest(function=function):
                # every loop has states in which it is active
                for position in range(len(parents)):
                    self.assertTrue(any(digits[position] != "3" for digits in states), position)
                for digits in states:
                    active = [position for position, digit in enumerate(digits) if digit != "3"]
                    for position in active:
                        # the parent loop is active, too
                        self.assertTrue(ancestors(position) <= set(active), digits)
                        # loops that are not nested are not active together
                        for other in active:
                            if other != position:
                                self.assertTrue(other in ancestors(position) or position in ancestors(other), digits)

    def test_loop_end_lines_lie_after_the_loop_starts(self):
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt")) as f:
            lines = f.read().splitlines()
        loops = set()
        for index, line in enumerate(lines[:-1]):
            begin = re.match(r"^1:(\d+) BGN loop", line)
            end = re.match(r"^1:(\d+) END loop", lines[index + 1])
            if begin and end:
                loops.add(int(begin.group(1)))
                with self.subTest(loop=line):
                    self.assertGreater(int(end.group(1)), int(begin.group(1)))
        # every executed loop: 8, 13 (in the else arm), 32, 40, 41, 50 and 54 (after the early return)
        self.assertTrue({8, 13, 32, 40, 41, 50, 54} <= loops, loops)
