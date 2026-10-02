# type: ignore
"""Profiles the two translation units of src/ and checks that the profiler's callpath state keeps
advancing. It used to freeze (two distinct states in dynamic_dependencies.txt) when
- main's state was not the initial one, because another module's function whose mangled name
  contains "main" (_Z12setup_domainP6Domain) was taken as the entry point,
- a call to a function without instrumentation (here: std::vector's, defined in a system header,
  outside of DP_PROJECT_ROOT_DIR) disabled the state transitions for good, as it waited for the
  callee's function exit,
- a function of another translation unit (helper) left the caller's state on its exit, although
  its call did not enter a state."""

import os
import pathlib
import re
import unittest

from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd


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

        # callpath per state id, from the prefix tree "<state_id> <parent_state_id> <label>"
        tree = dict()
        with open(os.path.join(self.profiler_dir, "stateID_to_callpath_mapping.txt")) as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 3 and not line.startswith("#"):
                    tree[fields[0]] = (fields[1], fields[2])

        def callpath(state_id):
            labels = []
            while state_id in tree and tree[state_id][0] != state_id and len(labels) < 1000:
                labels.append(tree[state_id][1])
                state_id = tree[state_id][0]
            return list(reversed(labels))

        self.callpath = staticmethod(callpath)
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt")) as f:
            self.used_states = set(re.findall(r"@(\d+)", f.read()))

    @classmethod
    def tearDownClass(self):
        run_cmd("make veryclean", self.src_dir, self.env_vars)

    def test_initial_state_is_main(self):
        with open(os.path.join(self.profiler_dir, "initial_stateID.txt")) as f:
            initial_state = f.read().split()[-1]
        self.assertEqual(self.callpath(initial_state), ["main"])

    def test_loop_iterations_after_untracked_calls_have_their_states(self):
        reached = {self.callpath(state)[-1] for state in self.used_states if len(self.callpath(state)) > 0}
        for iteration in range(3):
            with self.subTest(iteration=iteration):
                self.assertIn("_Z4workPdi_loopstate" + str(iteration), reached)

    def test_states_of_work_lie_below_driver(self):
        for state in self.used_states:
            path = self.callpath(state)
            if len(path) > 0 and path[-1].startswith("_Z4workPdi"):
                self.assertEqual(
                    [label for label in path if not label.startswith("call_")][:3],
                    ["main", "_Z6driverPdi", "_Z4workPdi"],
                )
