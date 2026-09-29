import os
import unittest

if os.getenv("DP_RUN_WIP_TESTS", "0") != "1":
    raise unittest.SkipTest("work-in-progress tests; set DP_RUN_WIP_TESTS=1 to run them")
