# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The test compilation of the compilation editor runs ``compile.sh`` for real but records no result."""

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest import mock

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.gui.mixins import compilation_editor
from discopop_library.ProjectManager.gui.mixins.compilation_editor import CompilationEditorMixin
from discopop_library.ProjectManager.services.jobs import WorkEvent, WorkFinished


def _arguments(project_root: Path) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=True,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=True,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


def _run_work_inline(_widget: Any, work: Callable[[Any], Any], handler: Callable[[WorkEvent], None]) -> None:
    handler(WorkFinished(result=work(mock.MagicMock()), error=None))


def test_the_test_compilation_records_no_result(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    os.makedirs(arguments.project_config_dir)
    with open(os.path.join(arguments.project_config_dir, "seq_settings.json"), "w") as f:
        json.dump({"CC": "clang", "CXX": "clang++"}, f)
    compile_sh = os.path.join(arguments.project_config_dir, "compile.sh")
    with open(compile_sh, "w") as f:
        f.write("#!/bin/bash\necho compiled\n")
    os.chmod(compile_sh, os.stat(compile_sh).st_mode | stat.S_IEXEC)

    editor: Any = SimpleNamespace(
        arguments=arguments,
        compilation_modified_files={},
        test_compilation_button=mock.MagicMock(),
        status_label=mock.MagicMock(),
        _show_test_compilation_result=mock.MagicMock(),
    )
    with mock.patch.object(compilation_editor, "start_work", _run_work_inline):
        CompilationEditorMixin._test_compilation_from_editor(editor)

    assert "Compilation successful" in editor.status_label.config.call_args.kwargs["text"]
    results_path = os.path.join(arguments.project_dir, "execution_results.json")
    if os.path.exists(results_path):
        with open(results_path) as f:
            assert json.load(f) == {}
