from typing import List
import unittest
import os
import pathlib
from ...utilities import get_dependencies
from .required_dependencies import required_dependencies_list


class TestMethods(unittest.TestCase):
    home_dir: str = ""
    parent_dir: str = ""

    @classmethod
    def setUpClass(self) -> None:
        self.home_dir = os.getcwd()
        self.parent_dir = str(pathlib.Path(__file__).parent.resolve())

        os.chdir(self.parent_dir)

        os.system("make")

    @classmethod
    def tearDownClass(self) -> None:
        os.chdir(self.parent_dir)
        skip_cleanup = False
        if "DP_TEST_PROFILER_SKIP_CLEANUP" in os.environ:
            if os.environ["DP_TEST_PROFILER_SKIP_CLEANUP"] == "y" or os.environ["DP_TEST_PROFILER_SKIP_CLEANUP"] == "Y":
                skip_cleanup = True
        if not skip_cleanup:
            os.system("make clean")
        os.chdir(self.home_dir)

    def test(self) -> None:
        self.assertTrue(len(required_dependencies_list) != 0, "No required dependencies specified!")
        dynamic_deps_path = os.path.join(self.parent_dir, ".discopop", "profiler", "dynamic_dependencies.txt")
        static_deps_path = os.path.join(self.parent_dir, ".discopop", "profiler", "static_dependencies.txt")
        dynamic_deps = get_dependencies(dynamic_deps_path)
        static_deps: List[str] = []
        if os.path.exists(static_deps_path):
            static_deps = get_dependencies(static_deps_path)

        print("DYNAMIC_DEPS: \n", dynamic_deps)
        print("STATIC_DEPS: \n", static_deps)

        deps = dynamic_deps + static_deps

        print("REQUIRED_DEPS: \n", required_dependencies_list)

        missing_deps: List[str] = []

        for required_dep in required_dependencies_list:
            found_required_dep = False
            for dep in deps:
                if required_dep in dep:
                    # required_dep is substring of dep
                    found_required_dep = True
                    break
            if not found_required_dep:
                missing_deps.append(required_dep)

        print("MISSING_DEPS: \n", missing_deps)

        self.assertEqual(len(missing_deps), 0, "Not all required dependencies found!")
