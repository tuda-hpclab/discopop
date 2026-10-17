# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Launching Visual Studio Code (``code``) for a DiscoPoP project or a source location."""

import os
import shutil
import subprocess
from typing import Optional
from urllib.parse import quote

VSCODE_NOT_FOUND_MESSAGE = (
    "Could not find the 'code' command on your PATH.\n\n"
    "Install Visual Studio Code and, from within VSCode, run "
    "'Shell Command: Install \"code\" command in PATH' to enable this feature."
)

_EXTENSION_FOCUS_URI = "vscode://TUDarmstadt-LaboratoryforParallelProgramming.discopop/focus"


def find_code_executable() -> Optional[str]:
    return shutil.which("code")


def focus_uri(dot_dp_path: str) -> str:
    """The URI that makes the DiscoPoP extension select the project of ``dot_dp_path``."""
    dot_dp = os.path.abspath(dot_dp_path)
    project_root = os.path.dirname(dot_dp)
    return _EXTENSION_FOCUS_URI + f"?dotDiscopop={quote(dot_dp, safe='')}&projectPath={quote(project_root, safe='')}"


def _launch(arguments: list[str]) -> None:
    subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def open_project(code_executable: str, dot_dp_path: str) -> None:
    """Open the project root (the parent of ``.discopop``) and focus the extension's sidebar.

    The extension activates on a workspace that *contains* a ``.discopop`` directory, so the project root is
    opened, not the directory itself. Opening the folder alone only focuses the sidebar of a fresh window;
    dispatching the URI to the extension focuses it on every invocation. Raises OSError when ``code`` cannot be
    started; a failure of the second, best-effort call is ignored.
    """
    project_root = os.path.dirname(os.path.abspath(dot_dp_path))
    _launch([code_executable, project_root])
    try:
        _launch([code_executable, "--open-url", focus_uri(dot_dp_path)])
    except OSError:
        pass


def open_file_at(code_executable: str, path: str, line: int) -> None:
    """Open ``path`` at ``line``. Raises OSError when ``code`` cannot be started."""
    _launch([code_executable, "--goto", f"{path}:{line}"])
