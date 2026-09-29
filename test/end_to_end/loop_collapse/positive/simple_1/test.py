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

    def test_two_level_collapse_identified(self):
        """The loops at lines 16 and 18 are perfectly nested do-all loops, so a collapse of both
        must be suggested based on the outer one."""
        collapsed = [p for p in self.test_output.patterns.do_all if p.collapse_level == 2]
        self.assertEqual(len(collapsed), 1, "expected exactly one two level collapse")
        self.assertEqual(collapsed[0].start_line, "1:16", "the collapse must be based on the outer loop")

    def test_collapse_records_the_patterns_it_replaces(self):
        """Applying the collapse excludes applying the do-all patterns of the collapsed loops, so
        both of them must be recorded."""
        collapsed = [p for p in self.test_output.patterns.do_all if p.collapse_level == 2]
        self.assertEqual(len(collapsed[0].collapsed_pattern_ids), 2)
        collapsed_lines = [
            p.start_line for p in self.test_output.patterns.do_all if p.pattern_id in collapsed[0].collapsed_pattern_ids
        ]
        self.assertEqual(sorted(collapsed_lines), ["1:16", "1:18"])

    def test_no_deeper_collapse_identified(self):
        """The nest is only two loops deep."""
        for do_all_info in self.test_output.patterns.do_all:
            self.assertLessEqual(do_all_info.collapse_level, 2)

    def test_the_collapsed_patterns_are_kept_as_alternatives(self):
        """The collapse is an additional suggestion, it does not remove the individual do-all
        suggestions for the loops it folds in."""
        start_lines = [p.start_line for p in self.test_output.patterns.do_all if p.collapse_level == 1]
        for expected_line in ["1:10", "1:16", "1:18"]:
            self.assertIn(expected_line, start_lines)
