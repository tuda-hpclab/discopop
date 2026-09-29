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

from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_compile_script_path,
    get_per_config_validation_compile_script_path,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
    resolve_compile_script_path,
    resolve_validation_compile_script_path,
    validation_needs_separate_compile,
)


class TestCompileScriptResolution(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_config_dir = self._tmp_dir.name
        os.makedirs(os.path.join(self.project_config_dir, "foo"))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_path_builder_helpers_join_correctly(self) -> None:
        self.assertEqual(
            get_shared_compile_script_path(self.project_config_dir),
            os.path.join(self.project_config_dir, "compile.sh"),
        )
        self.assertEqual(
            get_per_config_compile_script_path(self.project_config_dir, "foo"),
            os.path.join(self.project_config_dir, "foo", "compile.sh"),
        )

    def test_resolve_falls_back_to_shared_when_no_override(self) -> None:
        shared_path = get_shared_compile_script_path(self.project_config_dir)
        with open(shared_path, "w") as f:
            f.write("#!/bin/bash\nexit 0\n")

        self.assertEqual(
            resolve_compile_script_path(self.project_config_dir, "foo"),
            shared_path,
        )

    def test_resolve_prefers_per_config_when_present(self) -> None:
        shared_path = get_shared_compile_script_path(self.project_config_dir)
        with open(shared_path, "w") as f:
            f.write("#!/bin/bash\nexit 0\n")

        per_config_path = get_per_config_compile_script_path(self.project_config_dir, "foo")
        with open(per_config_path, "w") as f:
            f.write("#!/bin/bash\nexit 1\n")

        self.assertEqual(
            resolve_compile_script_path(self.project_config_dir, "foo"),
            per_config_path,
        )

    def test_resolve_handles_nonexistent_config_dir(self) -> None:
        # no "bar" subdirectory exists under project_config_dir
        self.assertEqual(
            resolve_compile_script_path(self.project_config_dir, "bar"),
            get_shared_compile_script_path(self.project_config_dir),
        )


class TestValidationCompileScriptResolution(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_config_dir = self._tmp_dir.name
        os.makedirs(os.path.join(self.project_config_dir, "foo"))
        self.shared_compile = self.__write(get_shared_compile_script_path(self.project_config_dir))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __write(self, path: str) -> str:
        with open(path, "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        return path

    def test_path_builder_helpers_join_correctly(self) -> None:
        self.assertEqual(
            get_shared_validation_compile_script_path(self.project_config_dir),
            os.path.join(self.project_config_dir, "compile_validate.sh"),
        )
        self.assertEqual(
            get_per_config_validation_compile_script_path(self.project_config_dir, "foo"),
            os.path.join(self.project_config_dir, "foo", "compile_validate.sh"),
        )

    def test_falls_back_to_shared_compile_script(self) -> None:
        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            self.shared_compile,
        )
        self.assertFalse(validation_needs_separate_compile(self.project_config_dir, "foo"))

    def test_falls_back_to_per_config_compile_override(self) -> None:
        per_config_compile = self.__write(get_per_config_compile_script_path(self.project_config_dir, "foo"))

        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            per_config_compile,
        )
        self.assertFalse(validation_needs_separate_compile(self.project_config_dir, "foo"))

    def test_shared_validation_script_is_used_when_present(self) -> None:
        shared_validation = self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            shared_validation,
        )
        self.assertTrue(validation_needs_separate_compile(self.project_config_dir, "foo"))

    def test_per_config_validation_script_beats_shared_one(self) -> None:
        self.__write(get_shared_validation_compile_script_path(self.project_config_dir))
        per_config_validation = self.__write(
            get_per_config_validation_compile_script_path(self.project_config_dir, "foo")
        )

        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            per_config_validation,
        )
        self.assertTrue(validation_needs_separate_compile(self.project_config_dir, "foo"))

    def test_role_wins_over_specificity(self) -> None:
        """A shared compile_validate.sh outranks a per-configuration compile.sh override."""
        self.__write(get_per_config_compile_script_path(self.project_config_dir, "foo"))
        shared_validation = self.__write(get_shared_validation_compile_script_path(self.project_config_dir))

        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            shared_validation,
        )
        self.assertTrue(validation_needs_separate_compile(self.project_config_dir, "foo"))

    def test_per_config_validation_script_of_other_config_is_ignored(self) -> None:
        os.makedirs(os.path.join(self.project_config_dir, "bar"))
        self.__write(get_per_config_validation_compile_script_path(self.project_config_dir, "bar"))

        self.assertEqual(
            resolve_validation_compile_script_path(self.project_config_dir, "foo"),
            self.shared_compile,
        )
        self.assertFalse(validation_needs_separate_compile(self.project_config_dir, "foo"))


if __name__ == "__main__":
    unittest.main()
