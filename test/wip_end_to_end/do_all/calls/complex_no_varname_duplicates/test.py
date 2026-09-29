# type: ignore
import os
import pathlib
import subprocess
import unittest

import jsonpickle

from discopop_library.result_classes.DetectionResult import DetectionResult
from test.utils.subprocess_wrapper.command_execution_wrapper import run_cmd
from test.utils.validator_classes.DoAllInfoForValidation import DoAllInfoForValidation
from subprocess import DEVNULL
from discopop_library.ConfigProvider.config_provider import run as run_config_provider
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments
from discopop_library.DependencyComparator.DependencyComparatorArguments import DependencyComparatorArguments
from discopop_library.DependencyComparator.dependency_comparator import run as run_comparator


class TestMethods(unittest.TestCase):
    def test(self):
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
        # create FileMapping
        cmd = os.path.join(dp_build_dir, "scripts", "dp-fmap")
        run_cmd(cmd, src_dir, env_vars)

        # build
        env_vars["CC"] = os.path.join(dp_build_dir, "scripts", "CC_wrapper.sh")
        env_vars["CXX"] = os.path.join(dp_build_dir, "scripts", "CXX_wrapper.sh")
        cmd = "make"
        run_cmd(cmd, src_dir, env_vars)

        # execute instrumented program
        run_cmd("./prog", src_dir, env_vars)

        # execute DiscoPoP analysis
        cmd = "discopop_explorer --enable-patterns doall,reduction"
        run_cmd(cmd, os.path.join(src_dir, ".discopop"), env_vars)
        # validate results
        try:
            self.validate_results(current_dir, src_dir)
            # clean environment
            run_cmd("make veryclean", src_dir, env_vars)
        except Exception as ex:
            # clean environment
            run_cmd("make veryclean", src_dir, env_vars)
            raise ex

    def validate_results(self, test_dir, src_dir):
        """Check that exactly one do-all is suggested"""
        test_output_file = os.path.join(src_dir, ".discopop", "explorer", "detection_result_dump.json")
        # load detection results
        with open(test_output_file, "r") as f:
            tmp_str = f.read()
        test_output: DetectionResult = jsonpickle.decode(tmp_str, keys=True)

        for pattern_type in test_output.patterns.__dict__:
            amount_of_identified_patterns = len(test_output.patterns.__dict__[pattern_type])
            if pattern_type == "do_all":
                expected = ["1:19", "1:24"]
                for pattern in test_output.patterns.__dict__[pattern_type]:
                    self.assertTrue(
                        pattern.start_line in expected,
                        "False positive: Pattern at "
                        + pattern.start_line
                        + " not in expected result: "
                        + str(expected),
                    )
                self.assertTrue(
                    len(test_output.patterns.__dict__[pattern_type]) == 2,
                    "False negative: Missed pattern. \nFound: "
                    + " ".join([p.start_line for p in test_output.patterns.__dict__[pattern_type]])
                    + "\nExpected: "
                    + " ".join(expected),
                )
            else:
                self.assertEqual(amount_of_identified_patterns, 0)
