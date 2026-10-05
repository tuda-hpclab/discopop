# type: ignore
"""Profiles src/code.cpp and checks that the dependency records of stack locals, which the hybrid
analysis of the profiler hands over statically (memory regions S<n>) instead of profiling their
accesses, carry the callpath states of both of their ends like the dynamically profiled records:
- a loop-carried accumulation (s += t, and the conditional c += 1.0) has its source in the
  previous iteration bucket of its sink,
- an intra-iteration temporary (t), also with a call in between, has both ends in the same state,
- a dependency from before the loop into it, or from the loop to after it, has the state of sum
  outside of the loop at that end,
- in sum_guarded the basic block holding the write of t ends with the invoke of observe_or_throw, whose call
  instrumentation enters the call's state: the write must keep the state of its iteration.
Records are compared via source lines and callpath labels, not via the (unstable) ids."""

import os
import pathlib
import re
import unittest

from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd

SUM = "_Z3sumPKdi"
LS = [SUM + "_loopstate" + str(i) for i in range(3)]
GUARDED = "_Z11sum_guardedPKdi"
GLS = [GUARDED + "_loopstate" + str(i) for i in range(3)]
NESTED_LS = "_Z6nestedPKdi_loopstate"


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
        profiler_dir = os.path.join(self.src_dir, ".discopop", "profiler")

        labels = dict()
        with open(os.path.join(profiler_dir, "stateID_to_callpath_mapping.txt")) as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 3 and not line.startswith("#"):
                    labels[fields[0]] = fields[2]
        lines = dict()
        with open(os.path.join(profiler_dir, "instructionID_to_lineID_mapping.txt")) as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 2 and fields[1] != "*":
                    lines[fields[0]] = int(fields[1].split(":")[1])

        def end(token):
            """(line, label of the callpath state) of a record end '<instruction id>@<state id>'"""
            if token == "*":
                return ("*", None)
            instruction, _, state = token.partition("@")
            return (lines.get(instruction), labels.get(state) if state else None)

        # (sink line, sink state label, type, source line, source state label, variable, memory region)
        self.records = set()
        self.raw_stack_records = []
        self.dynamic_sink_labels = dict()  # sink line -> state labels of the dynamically profiled records
        with open(os.path.join(profiler_dir, "dynamic_dependencies.txt")) as f:
            for line in f:
                fields = line.split()
                if len(fields) < 3 or fields[1] != "NOM":
                    continue
                sink_line, sink_label = end(fields[0])
                for dep_type, source, variable, region in re.findall(
                    r"(RAW|WAR|WAW|INIT) (\S+)\|([^\s(]+)\(([^)\s]*)\)", line
                ):
                    source_line, source_label = end(source)
                    if region.startswith("S"):
                        self.raw_stack_records.append(fields[0] + " " + dep_type + " " + source)
                        self.records.add((sink_line, sink_label, dep_type, source_line, source_label, variable, region))
                    else:
                        self.dynamic_sink_labels.setdefault(sink_line, set()).add(sink_label)

    @classmethod
    def tearDownClass(self):
        run_cmd("make veryclean", self.src_dir, self.env_vars)

    def state_pairs(self, sink_line, dep_type, source_line, variable):
        return {
            (r[1], r[4])
            for r in self.records
            if r[0] == sink_line and r[2:4] == (dep_type, source_line) and r[5] == variable
        }

    def test_stack_records_exist(self):
        self.assertGreater(len(self.records), 0)

    def test_every_stack_record_carries_states(self):
        for record in self.raw_stack_records:
            with self.subTest(record=record):
                sink, dep_type, source = record.split(" ")
                self.assertRegex(sink, r"^\d+@\d+$")
                if dep_type == "INIT":
                    self.assertEqual(source, "*")
                else:
                    self.assertRegex(source, r"^\d+@\d+$")

    def test_loop_carried_accumulation_crosses_one_iteration(self):
        # s += t (line 14): read of s <- write of s in the previous iteration
        self.assertEqual(self.state_pairs(14, "RAW", 14, "s"), {(LS[i], LS[(i - 1) % 3]) for i in range(3)})
        # s = 0.0 (line 9) is only the source in the first iteration, the later ones read the loop's write
        from_init = self.state_pairs(14, "RAW", 9, "s")
        self.assertEqual(len(from_init), 1)
        self.assertIn(next(iter(from_init))[0], LS)
        self.assertEqual(next(iter(from_init))[1], SUM)
        # the write of s follows its read in the same iteration
        self.assertEqual(self.state_pairs(14, "WAR", 14, "s"), {(LS[i], LS[i]) for i in range(3)})

    def test_conditional_accumulation_crosses_one_iteration(self):
        # c += 1.0 (line 16), executed in the iterations with t > 4.0 (i >= 3, consecutive)
        self.assertEqual(self.state_pairs(16, "RAW", 16, "c"), {(LS[i], LS[(i - 1) % 3]) for i in range(3)})
        # c = 0.0 (line 10) is only the source in the first of them
        from_init = self.state_pairs(16, "RAW", 10, "c")
        self.assertEqual(len(from_init), 1)
        self.assertEqual(next(iter(from_init))[1], SUM)

    def test_intra_iteration_temporary_stays_in_its_iteration(self):
        # t = a[i] * 2.0 (line 12); observe(i) (line 13); s += t (line 14); if (t > 4.0) (line 15)
        self.assertEqual(self.state_pairs(14, "RAW", 12, "t"), {(LS[i], LS[i]) for i in range(3)})
        self.assertEqual(self.state_pairs(15, "RAW", 12, "t"), {(LS[i], LS[i]) for i in range(3)})
        # the next iteration's write of t follows this iteration's last read of t
        self.assertEqual(self.state_pairs(12, "WAR", 15, "t"), {(LS[i], LS[(i - 1) % 3]) for i in range(3)})

    def test_dependency_after_the_loop(self):
        # return s + c (line 19) reads the s of the last iteration (8 iterations: bucket of the last one)
        pairs = self.state_pairs(19, "RAW", 14, "s")
        self.assertEqual(len(pairs), 1)
        sink_label, source_label = next(iter(pairs))
        self.assertEqual(sink_label, SUM)
        self.assertIn(source_label, LS)

    def test_states_agree_with_dynamically_profiled_records(self):
        # a[i] (line 12) is profiled dynamically; the hybrid records of the loop body have the same states
        hybrid = {r[1] for r in self.records if r[0] in (12, 14, 15, 16)}
        self.assertEqual(hybrid, set(LS))
        self.assertEqual(self.dynamic_sink_labels.get(12), set(LS))

    def test_source_block_ending_with_an_invoke_keeps_its_iteration_state(self):
        # double t = a[i] (line 40); observe_or_throw(i) (line 41, invoke); s += t (line 42)
        self.assertEqual(self.state_pairs(42, "RAW", 40, "t"), {(GLS[i], GLS[i]) for i in range(3)})
        self.assertEqual(self.state_pairs(42, "RAW", 42, "s"), {(GLS[i], GLS[(i - 1) % 3]) for i in range(3)})

    def test_reinitialised_inner_loop_variable_stays_in_its_outer_iteration(self):
        # nested (line 49): for i (line 51) { for (int j = 0; j < 4; j++) (line 52) { ... } }
        # "j = 0" replaces the "j++" of the previous outer iteration as the source of the header's read
        # (anti and output dependencies of j do cross it: the last "j < 4" / "j++" precede the next "j = 0")
        pairs = {
            (r[1], r[4], r[2]) for r in self.records if r[0] == 52 and r[3] == 52 and r[5] == "j" and r[2] == "RAW"
        }
        self.assertGreater(len(pairs), 0)
        crossing_inner = 0
        for sink_label, source_label, dep_type in pairs:
            with self.subTest(sink=sink_label, source=source_label, type=dep_type):
                self.assertTrue(sink_label.startswith(NESTED_LS) and source_label.startswith(NESTED_LS))
                # loopstate<outer bucket><inner bucket>, 3 = outside of the loop
                outer_sink, inner_sink = sink_label[len(NESTED_LS) :]
                outer_source, inner_source = source_label[len(NESTED_LS) :]
                self.assertEqual(outer_sink, outer_source)
                if inner_sink != inner_source:
                    crossing_inner += 1
        # the inner loop's own iterations are crossed (j++ -> j < 4, j++ -> j++)
        self.assertGreater(crossing_inner, 0)


if __name__ == "__main__":
    unittest.main()
