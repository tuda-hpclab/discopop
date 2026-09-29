# type: ignore
import os
import pathlib
import unittest

import jsonpickle

from discopop_library.result_classes.DetectionResult import DetectionResult
from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd
from discopop_library.ConfigProvider.config_provider import run as run_config_provider
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments


class TestMethods(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        current_dir = pathlib.Path(__file__).parent.resolve()
        dp_build_dir = run_config_provider(
            ConfigProviderArguments(
                return_dp_build_dir=True,
                return_llvm_bin_dir=False,
                return_full_config=False,
                return_version_string=False,
            )
        )

        env_vars = dict(os.environ)

        src_dir = os.path.join(current_dir, "src")

        # build
        env_vars["CC"] = "discopop_cc"
        env_vars["CXX"] = "discopop_cxx"
        env_vars["DP_PROJECT_ROOT_DIR"] = src_dir
        run_cmd("make", src_dir, env_vars)
        # execute instrumented program
        run_cmd("./prog", src_dir, env_vars)
        # execute DiscoPoP analysis
        run_cmd("discopop_explorer --enable-patterns doall,reduction", os.path.join(src_dir, ".discopop"), env_vars)

        self.src_dir = src_dir
        self.env_vars = env_vars

        test_output_file = os.path.join(self.src_dir, ".discopop", "explorer", "detection_result_dump.json")
        # load detection results
        with open(test_output_file, "r") as f:
            tmp_str = f.read()
        self.test_output: DetectionResult = jsonpickle.decode(tmp_str, keys=True)

    @classmethod
    def tearDownClass(self):
        run_cmd("make veryclean", self.src_dir, self.env_vars)

    def test_both_loops_of_the_nest_are_do_all(self):
        """Pins the reason the collapse is rejected. Both loops of the nest at lines 19 and 22 are
        parallelizable, so it is only the imperfect nesting which prevents collapsing them. Without
        this the negative result below could be caused by a missing do-all suggestion instead."""
        start_lines = [p.start_line for p in self.test_output.patterns.do_all]
        self.assertIn("1:19", start_lines, "the outer loop of the nest must be a do-all loop")
        self.assertIn("1:22", start_lines, "the inner loop of the nest must be a do-all loop")

    def test_no_collapse_identified(self):
        """The assignment at line 20 sits in the outer loop body next to the inner loop, so the two
        loops are not perfectly nested. Collapsing them would execute the assignment once per
        combined iteration instead of once per iteration of the outer loop."""
        for do_all_info in self.test_output.patterns.do_all:
            self.assertEqual(
                do_all_info.collapse_level,
                1,
                "unexpected collapse suggested at " + str(do_all_info.start_line),
            )
        for do_all_info in self.test_output.patterns.do_all:
            self.assertEqual(do_all_info.collapsed_pattern_ids, [])
