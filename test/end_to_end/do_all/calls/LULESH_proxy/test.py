# type: ignore
import os
import pathlib
from typing import cast
import unittest

import jsonpickle

from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_library.result_classes.DetectionResult import DetectionResult
from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd
from test.utils.validator_classes.DoAllInfoForValidation import DoAllInfoForValidation
from discopop_library.ConfigProvider.config_provider import run as run_config_provider
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments
from discopop_library.DependencyComparator.DependencyComparatorArguments import DependencyComparatorArguments
from discopop_library.DependencyComparator.dependency_comparator import run as run_comparator


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
        cmd = "make"
        run_cmd(cmd, src_dir, env_vars)
        # execute instrumented program
        cmd = "./prog"
        run_cmd(cmd, src_dir, env_vars)
        # execute DiscoPoP analysis
        cwd = os.path.join(src_dir, ".discopop")
        cmd = "discopop_explorer --enable-patterns doall,reduction"
        run_cmd(cmd, cwd, env_vars)

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

    def test(self):
        """Check that main loop do-all is suggested"""
        found_main_loop = False

        for pattern_type in self.test_output.patterns.__dict__:
            amount_of_identified_patterns = len(self.test_output.patterns.__dict__[pattern_type])
            if pattern_type == "do_all":
                do_all_patterns = self.test_output.patterns.__dict__[pattern_type]

                for pattern in do_all_patterns:
                    if cast(DoAllInfo, pattern).start_line == "1:271":
                        found_main_loop = True
            else:
                self.assertEqual(amount_of_identified_patterns, 0)

        self.assertTrue(found_main_loop, "main loop not detected as do-all.")

    # def test_deps(self) -> None:
    #     # compare detected dependencies to gold standard
    #     current_dir = pathlib.Path(__file__).parent.resolve()
    #     gold_standard_dir = os.path.join(current_dir, "gold_std")
    #     test_output_dir = os.path.join(self.src_dir, ".discopop", "profiler")
    #     dynamic_gold_std = os.path.join(gold_standard_dir, "dynamic_dependencies.txt")
    #     static_gold_std = os.path.join(gold_standard_dir, "dynamic_dependencies.txt")
    #     dynamic_test_result = os.path.join(test_output_dir, "dynamic_dependencies.txt")
    #     static_test_result = os.path.join(test_output_dir, "dynamic_dependencies.txt")
    #     self.assertEqual(
    #         run_comparator(
    #             DependencyComparatorArguments(
    #                 dynamic_gold_std, static_gold_std, dynamic_test_result, static_test_result, "None", False
    #             )
    #         ),
    #         0,
    #     )
