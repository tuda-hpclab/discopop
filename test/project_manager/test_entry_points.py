# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The contract of the two console scripts.

``discopop`` is the command line tool and ``discopop_gui`` opens the window.
Before this split, ``discopop`` forced ``--gui`` on top of the full command line
parser, so ``discopop -x 1024:dp`` opened a window, ignored the execution it was
asked for, and blocked until somebody closed it.
"""

import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from discopop_library.ProjectManager.__main__ import GUI_MOVED_NOTICE, gui_main, main
from discopop_library.ProjectManager.configurations.repetitions import DEFAULT_MEASURED_REPETITIONS
from discopop_library.ProjectManager.gui import display


class TestEntryPoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.project = self._tmp_dir.name
        # An initialized project: the command line path refuses to run without one.
        os.makedirs(os.path.join(self.project, ".discopop"))

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_bare_discopop_prints_help_instead_of_executing(self) -> None:
        # -x defaults to "tiny", so falling through would copy, build and run the
        # project in whatever directory the command happened to be typed in.
        out = io.StringIO()
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("sys.argv", ["discopop"]), contextlib.redirect_stdout(out):
                main()
        run_mock.assert_not_called()
        self.assertIn("usage: discopop", out.getvalue())
        self.assertIn(GUI_MOVED_NOTICE, out.getvalue())

    def test_bare_project_manager_prints_help_without_the_move_notice(self) -> None:
        # The notice is about a name that changed, and this name did not.
        out = io.StringIO()
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("sys.argv", ["discopop_project_manager"]), contextlib.redirect_stdout(out):
                main()
        run_mock.assert_not_called()
        self.assertIn("usage: discopop_project_manager", out.getvalue())
        self.assertNotIn(GUI_MOVED_NOTICE, out.getvalue())

    def test_discopop_executes_what_it_was_asked_for(self) -> None:
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop", "-p", self.project, "-x", "1024:dp"]):
                    main()
        run_mock.assert_called_once()
        arguments = run_mock.call_args[0][0]
        self.assertFalse(arguments.gui)
        self.assertEqual("1024:dp", arguments.execute_configurations)

    def test_the_repetition_count_reaches_the_run(self) -> None:
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop", "-p", self.project, "-xr", "5"]):
                    main()
        run_mock.assert_called_once()
        self.assertEqual(5, run_mock.call_args[0][0].execution_repetitions)

    def test_measurements_are_repeated_by_default(self) -> None:
        # A runtime nobody asked to be trustworthy is still read as one, so the
        # measured runs are repeated unless the caller says otherwise.
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop", "-p", self.project]):
                    main()
        self.assertEqual(DEFAULT_MEASURED_REPETITIONS, run_mock.call_args[0][0].execution_repetitions)
        self.assertEqual(3, DEFAULT_MEASURED_REPETITIONS)

    def test_a_single_measurement_can_still_be_asked_for(self) -> None:
        """The pre-option behaviour has to stay reachable in one flag."""
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop", "-p", self.project, "-xr", "1"]):
                    main()
        self.assertEqual(1, run_mock.call_args[0][0].execution_repetitions)

    def test_an_unusable_repetition_count_is_refused(self) -> None:
        # Refused before the project is copied and built, not after.
        out = io.StringIO()
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop", "-p", self.project, "-xr", "0"]):
                    with contextlib.redirect_stdout(out):
                        with self.assertRaises(SystemExit) as raised:
                            main()
        self.assertEqual(1, raised.exception.code)
        run_mock.assert_not_called()
        self.assertIn("--execution-repetitions", out.getvalue())

    def test_gui_entry_point_still_forces_the_window(self) -> None:
        with patch("discopop_library.ProjectManager.__main__.run") as run_mock:
            with patch("discopop_library.ProjectManager.__main__.setup_logger"):
                with patch("sys.argv", ["discopop_gui", "-p", self.project]):
                    gui_main()
        run_mock.assert_called_once()
        self.assertTrue(run_mock.call_args[0][0].gui)


class TestDisplayGuard(unittest.TestCase):
    def test_no_display_exits_with_a_message(self) -> None:
        with patch.object(display.sys, "platform", "linux"), patch.dict(display.os.environ, clear=False):
            display.os.environ.pop("DISPLAY", None)
            display.os.environ.pop("WAYLAND_DISPLAY", None)
            self.assertFalse(display.have_display())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised:
                    display.require_display()
            self.assertEqual(1, raised.exception.code)
            self.assertIn("no display is available", err.getvalue())

    def test_a_display_is_enough(self) -> None:
        with patch.object(display.sys, "platform", "linux"):
            with patch.dict(display.os.environ, {"DISPLAY": ":0"}):
                self.assertTrue(display.have_display())
                display.require_display()

    def test_platforms_without_a_display_server(self) -> None:
        for platform in ("darwin", "win32"):
            with self.subTest(platform=platform):
                with patch.object(display.sys, "platform", platform), patch.dict(display.os.environ, clear=False):
                    display.os.environ.pop("DISPLAY", None)
                    display.os.environ.pop("WAYLAND_DISPLAY", None)
                    self.assertTrue(display.have_display())


if __name__ == "__main__":
    unittest.main()
