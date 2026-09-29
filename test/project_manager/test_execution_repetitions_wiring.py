# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which runs ``--execution-repetitions`` actually reaches.

Repeating a run costs a full program execution every time, so where the count is
applied is a decision worth pinning down: the seq and par ``execute.sh`` runs
measure a runtime and are repeated, while dp and hd are instrumented profiling
runs whose output feeds the Explorer, and compile.sh produces no measurement at
all. ``execute_configuration`` is stubbed here, so these tests assert on the
dispatch rather than on running anything.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import get_shared_compile_script_path
from discopop_library.ProjectManager.utilities.CLI import listConfiguration
from discopop_library.ProjectManager.utilities.CLI.listConfiguration import show_configurations_with_execution

CONFIG_NAME = "tiny"
MODES = ("dp", "hd", "seq", "par")


class TestRepetitionWiring(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project_root = self._tmp_dir.name
        self.arguments = self.__arguments(repetitions=5)

        config_path = os.path.join(self.arguments.project_config_dir, CONFIG_NAME)
        os.makedirs(config_path)
        self.__write_script(get_shared_compile_script_path(self.arguments.project_config_dir))
        self.__write_script(os.path.join(config_path, "execute.sh"))
        for mode in MODES:
            with open(os.path.join(self.arguments.project_config_dir, mode + "_settings.json"), "w") as f:
                json.dump({}, f)

        # (script name, settings name, repetitions) per call, in call order
        self.calls: List[Tuple[str, str, int]] = []

        def fake_execute_configuration(
            arguments: Any,
            project_copy_root_path: str,
            config_path: str,
            settings_path: str,
            script_path: str,
            thread_count: int,
            timeout: Optional[float] = None,
            process_started_callback: Any = None,
            execution_time_regex: Optional[str] = None,
            measurement: Optional[Dict[str, Any]] = None,
            repetitions: int = 1,
            should_abort: Any = None,
        ) -> Tuple[int, float, str, str]:
            self.calls.append((os.path.basename(script_path), os.path.basename(settings_path), repetitions))
            return (0, 1.0, "", "")

        # autospec: the mock enforces the real execute_configuration's signature on
        # its callers, and hands the bound arguments to the stub. A signature change
        # there therefore raises here instead of silently letting these tests assert
        # on a default nobody passed.
        patcher = mock.patch.object(
            listConfiguration, "execute_configuration", autospec=True, side_effect=fake_execute_configuration
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def __arguments(self, repetitions: int) -> ProjectManagerArguments:
        return ProjectManagerArguments(
            log_level="WARNING",
            write_log=False,
            project_root=self.project_root,
            full_execute=False,
            list=False,
            execute_configurations=CONFIG_NAME,
            # in place: the run then needs neither a project copy nor its deletion,
            # neither of which this test is about
            execute_inplace=True,
            skip_cleanup=True,
            generate_report=False,
            show_report=False,
            initialize_directory=True,
            apply_suggestions=None,
            reset=False,
            reset_execution_results=False,
            gui=False,
            label_prefix="",
            timeout_execution=None,
            timeout_compilation=None,
            timeout_validation=None,
            execution_repetitions=repetitions,
        )

    def __write_script(self, path: str) -> None:
        with open(path, "w") as f:
            f.write("#!/bin/bash\nexit 0\n")

    def __run(self) -> None:
        # the function tabulates its findings on stdout; not what is under test
        with contextlib.redirect_stdout(io.StringIO()):
            show_configurations_with_execution(self.arguments, restricted_configurations=[CONFIG_NAME])

    def __repetitions_of(self, script: str, settings: str) -> int:
        matching = [reps for name, used_settings, reps in self.calls if name == script and used_settings == settings]
        self.assertEqual(1, len(matching), "expected exactly one " + script + " run with " + settings)
        return matching[0]

    def test_the_measuring_runs_are_repeated(self) -> None:
        self.__run()
        for mode in ("seq", "par"):
            with self.subTest(mode=mode):
                self.assertEqual(5, self.__repetitions_of("execute.sh", mode + "_settings.json"))

    def test_the_profiling_runs_are_not_repeated(self) -> None:
        """dp and hd produce profiler output, not a runtime worth a median."""
        self.__run()
        for mode in ("dp", "hd"):
            with self.subTest(mode=mode):
                self.assertEqual(1, self.__repetitions_of("execute.sh", mode + "_settings.json"))

    def test_compilation_is_never_repeated(self) -> None:
        self.__run()
        compile_runs = [reps for name, _, reps in self.calls if name != "execute.sh"]
        self.assertTrue(compile_runs)
        self.assertEqual([1] * len(compile_runs), compile_runs)

    def test_the_default_repeats_nothing(self) -> None:
        """Without the flag every run is dispatched exactly as it was before."""
        self.arguments = self.__arguments(repetitions=1)
        self.__run()
        self.assertEqual([1] * len(self.calls), [reps for _, _, reps in self.calls])


if __name__ == "__main__":
    unittest.main()
