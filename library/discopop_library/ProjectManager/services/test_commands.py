# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import sys

from discopop_library.ProjectManager.services.commands import (
    autotuner_command,
    environment_with_interpreter_on_path,
    explorer_command,
    hotspot_analyzer_command,
    patch_repair_command,
)
from discopop_library.ProjectManager.services.requests import AutotunerRequest, ExplorerRequest, PatchRepairRequest


def _autotuner(**changes: object) -> AutotunerRequest:
    defaults = dict(
        configuration="tiny",
        hotspot_types="yes,maybe",
        threads="auto",
        repetitions=1,
        repetitions_warning=None,
        algorithm="0",
        log_level="INFO",
        mode="search",
        evaluate_ids=(),
        search_space_ids=None,
    )
    defaults.update(changes)
    return AutotunerRequest(**defaults)  # type: ignore[arg-type]


def test_explorer_command() -> None:
    plain = explorer_command(ExplorerRequest("doall", "auto", False), "py")
    assert plain == ["py", "-m", "discopop_explorer", "--enable-patterns", "doall", "--log", "WARNING"]
    full = explorer_command(ExplorerRequest("doall,reduction", "4", True), "py")
    assert full[-3:] == ["-j", "4", "--ignore-dependency-states"]
    visualized = explorer_command(ExplorerRequest("doall", "auto", False, visualize=True), "py")
    assert visualized == plain + ["--visualize"]


def test_default_autotuner_command_has_no_optional_flags() -> None:
    assert autotuner_command(_autotuner(), "/p/.discopop", "py") == [
        "py",
        "-m",
        "discopop_library.EmpiricalAutotuning",
        "--dot-dp-path",
        "/p/.discopop",
        "-c",
        "tiny",
        "-ht",
        "yes,maybe",
        "-A",
        "0",
        "--log",
        "INFO",
    ]


def test_autotuner_options() -> None:
    command = autotuner_command(_autotuner(threads="8", repetitions=3, search_space_ids=("1", "4")), "d", "py")
    assert command[-6:] == ["-t", "8", "-xr", "3", "--search-space", "1,4"]
    evaluate = autotuner_command(
        _autotuner(mode="evaluate", evaluate_ids=("2", "3"), search_space_ids=("9",)), "d", "py"
    )
    assert evaluate[-2:] == ["-s", "2,3"]
    assert "--search-space" not in evaluate
    # nothing selected to evaluate: the search algorithm runs instead
    assert "-s" not in autotuner_command(_autotuner(mode="evaluate"), "d", "py")


def test_patch_repair_command() -> None:
    request = PatchRepairRequest("tiny", "yes", 2, 1, 300, "INFO", "claude", "m", True, ("3",))
    command = patch_repair_command(request, "d", "py")
    assert command[:5] == ["py", "-m", "discopop_library.PatchRepair", "--dot-dp-path", "d"]
    assert command[-7:] == ["--backend", "claude", "--model", "m", "--dry-run", "-s", "3"]
    bare = patch_repair_command(PatchRepairRequest("tiny", "yes", 2, 1, 300, "INFO", "", "", False, None), "d", "py")
    assert bare[-2:] == ["--log", "INFO"]


def test_hotspot_analyzer_command() -> None:
    assert hotspot_analyzer_command("/bin/a", "merged") == ["/bin/a", "--input-dir", "merged"]


def test_the_interpreter_bin_is_put_on_the_path_once() -> None:
    interpreter_bin = os.path.dirname(sys.executable)
    environment = environment_with_interpreter_on_path({"PATH": "/usr/bin"})
    assert environment["PATH"] == interpreter_bin + os.pathsep + "/usr/bin"
    assert environment_with_interpreter_on_path(environment)["PATH"] == environment["PATH"]
