# type: ignore
"""Profiles the two translation units of src/ and checks that the profiler's callpath state keeps
advancing. It used to freeze (two distinct states in dynamic_dependencies.txt) when
- main's state was not the initial one, because another module's function whose mangled name
  contains "main" (_Z12setup_domainP6Domain) was taken as the entry point,
- a call to a function without instrumentation (here: std::vector's, defined in a system header,
  outside of DP_PROJECT_ROOT_DIR) disabled the state transitions for good, as it waited for the
  callee's function exit,
- a function of another translation unit (helper) left the caller's state on its exit, although
  its call did not enter a state,
- an indirect call of a function without instrumentation (std::abs through a function pointer)
  disabled the state transitions for good.
Constructors never entered a state: the calls of `new Buffer(...)` and `Buffer b(...)` go to the
complete-object constructor, an alias of the base-object constructor, and a function of another
translation unit (Table's constructor), or one reached only indirectly (a virtual method), was no
entry point of its module's call paths when it contained a loop.
After an exception was caught, the state stayed in the function that threw it. All iterations of a
do-while loop shared one state."""

import os
import pathlib
import re
import unittest

from test.end_to_end.pipeline import PipelineTestCase


class TestCallpathStates(PipelineTestCase):
    SRC_DIR = pathlib.Path(__file__).parent / "src"

    @classmethod
    def setUpClass(self):
        super().setUpClass()
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

    def test_initial_state_is_main(self):
        with open(os.path.join(self.profiler_dir, "initial_stateID.txt")) as f:
            initial_state = f.read().split()[-1]
        self.assertEqual(self.callpath(initial_state), ["main"])

    def test_loop_iterations_after_untracked_calls_have_their_states(self):
        reached = {self.callpath(state)[-1] for state in self.used_states if len(self.callpath(state)) > 0}
        for iteration in range(3):
            with self.subTest(iteration=iteration):
                self.assertIn("_Z4workPdi_loopstate" + str(iteration), reached)

    def reached_loopstates(self, function):
        """the callpaths of the used states ending in an iteration state of the function's loop"""
        return [
            self.callpath(state)
            for state in self.used_states
            if len(self.callpath(state)) > 0 and self.callpath(state)[-1].startswith(function + "_loopstate")
        ]

    def test_constructor_called_through_alias_has_states_below_main(self):
        paths = self.reached_loopstates("_ZN6BufferC2Ei")
        self.assertEqual({path[-1] for path in paths}, {"_ZN6BufferC2Ei_loopstate" + str(i) for i in range(3)})
        for path in paths:
            self.assertEqual([label for label in path if not label.startswith("call_")][:2], ["main", "_ZN6BufferC2Ei"])
        # one call path per constructor call (new and stack object)
        self.assertEqual(len({path[1] for path in paths}), 2)

    def test_constructor_of_another_translation_unit_has_states(self):
        paths = self.reached_loopstates("_ZN5TableC2Ei")
        self.assertEqual({path[-1] for path in paths}, {"_ZN5TableC2Ei_loopstate" + str(i) for i in range(3)})
        # the call path starts at the constructor, the entry point of its translation unit
        for path in paths:
            self.assertEqual(path[0], "_ZN5TableC2Ei")

    def test_loop_after_indirect_call_of_uninstrumented_function_has_its_states(self):
        paths = self.reached_loopstates("_Z19after_indirect_callPdi")
        self.assertEqual(
            {path[-1] for path in paths}, {"_Z19after_indirect_callPdi_loopstate" + str(i) for i in range(3)}
        )
        for path in paths:
            self.assertEqual(path[0], "main")

    def test_virtual_method_has_states(self):
        paths = self.reached_loopstates("_ZN6Square4areaEPdi")
        self.assertEqual({path[-1] for path in paths}, {"_ZN6Square4areaEPdi_loopstate" + str(i) for i in range(3)})

    def test_states_after_a_caught_exception_leave_the_throwing_function(self):
        paths = self.reached_loopstates("_Z15after_exceptionPdi")
        self.assertEqual({path[-1] for path in paths}, {"_Z15after_exceptionPdi_loopstate" + str(i) for i in range(3)})
        for path in paths:
            self.assertEqual(path[0], "main")
            self.assertNotIn("_Z9may_throwPdi", path)

    def test_do_while_iterations_have_their_states(self):
        paths = self.reached_loopstates("_Z13bottom_testedPdi")
        self.assertEqual({path[-1] for path in paths}, {"_Z13bottom_testedPdi_loopstate" + str(i) for i in range(3)})

    def test_states_of_work_lie_below_driver(self):
        for state in self.used_states:
            path = self.callpath(state)
            if len(path) > 0 and path[-1].startswith("_Z4workPdi"):
                self.assertEqual(
                    [label for label in path if not label.startswith("call_")][:3],
                    ["main", "_Z6driverPdi", "_Z4workPdi"],
                )
