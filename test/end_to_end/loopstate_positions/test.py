# type: ignore
"""Profiles src/code.cpp and checks the profiler's loopstate_positions.txt against the source: every
loop of a function has one loopstate digit, numbered in the pre-order of the loop nesting forest, and
names its loop node in Data.xml. Covers a loop nested in an `else` inside another loop, whose exit
block carries no debug location (it used to be skipped by the loop entry/exit instrumentation), and
sibling loops in if / else."""

import os
import pathlib
import re
import unittest

from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd

# {function: [start line of the loop at each loopstate position]}
EXPECTED_POSITIONS = {
    "_Z6kerneliiPdS_": [8, 13, 20, 21],
    "_Z8siblingsiPd": [32, 36, 40, 41],
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
