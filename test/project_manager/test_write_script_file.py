# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import tempfile
import unittest

from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file


class TestWriteScriptFile(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp_dir.name, "compile.sh")

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_prepends_shebang_when_missing(self) -> None:
        write_script_file(self.path, "$CXX $CXXFLAGS main.cpp -o a.out\n")
        with open(self.path, "r") as f:
            content = f.read()
        self.assertTrue(content.startswith("#!/bin/bash\n"))

    def test_preserves_existing_shebang(self) -> None:
        write_script_file(self.path, "#!/bin/sh\nexit 0\n")
        with open(self.path, "r") as f:
            content = f.read()
        self.assertEqual(content, "#!/bin/sh\nexit 0\n")

    def test_marks_file_executable(self) -> None:
        write_script_file(self.path, "exit 0\n")
        self.assertTrue(os.access(self.path, os.X_OK))

    def test_make_executable_false_leaves_permissions_unchanged(self) -> None:
        write_script_file(self.path, "exit 0\n", make_executable=False)
        self.assertFalse(os.access(self.path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
