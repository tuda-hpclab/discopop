# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Hotspots stage of the GUI (``HotspotSession``) compiles into the kept hd build and runs in it, with the real
hotspot detection: the build is listed with the others, a second measurement does not compile again, and the runs of
two configurations of one compile script are stored in the data of the project and analyzed together."""

import json
import pathlib
import queue
import threading
from typing import List

from discopop_library.ProjectManager.configurations.builds import list_builds
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.services.hotspot_session import HotspotSession
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkOutput

MAIN_CPP = """#include <cstdio>
#include <cstdlib>
int main(int argc, char** argv) {
  const int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  long sum = 0;
  for (int i = 0; i < n; ++i) { sum += i; }
  for (int j = 0; j < 2 * n; ++j) { sum += j % 7; }
  std::printf("%ld\\n", sum);
  return 0;
}
"""


def _write(path: pathlib.Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _arguments(root: pathlib.Path) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )


def _context() -> "tuple[WorkContext, queue.Queue[WorkEvent]]":
    events: "queue.Queue[WorkEvent]" = queue.Queue()
    return WorkContext(events, threading.Event()), events


def _text(events: "queue.Queue[WorkEvent]") -> str:
    texts: List[str] = []
    while not events.empty():
        event = events.get_nowait()
        if isinstance(event, WorkOutput):
            texts.append(event.text)
    return "".join(texts)


def test_the_hotspot_stage_runs_in_the_kept_hd_build(tmp_path: pathlib.Path) -> None:
    import subprocess

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.cpp").write_text(MAIN_CPP)
    subprocess.run(["discopop_project_manager", "-p", str(root), "--init"], check=True, capture_output=True)
    configs = root / ".discopop" / "project" / "configs"
    _write(configs / "compile.sh", "#!/bin/bash\n$CXX $CXXFLAGS main.cpp -o prog\n")
    (configs / "hd_settings.json").write_text(
        json.dumps(
            {"CC": "discopop_hotspot_cc", "CXX": "discopop_hotspot_cxx", "CFLAGS": "-fopenmp", "CXXFLAGS": "-fopenmp"}
        )
    )
    for name, argument in (("small", "100"), ("big", "5000")):
        (configs / name).mkdir()
        _write(configs / name / "execute.sh", f"#!/bin/bash\n./prog {argument}\n")
    # "big" runs in the build of "small" (sharing is declared, no longer implied by an equal compile script)
    (configs / "big" / "build_from.json").write_text(json.dumps({"build_from": "small"}))

    session = HotspotSession(_arguments(root))
    ctx, events = _context()
    timeouts = (600.0, 600.0, None)
    assert session.run_batch(ctx, ["small", "big"], repetitions=1, timeouts=timeouts), _text(events)

    # one build serves both configurations and is listed with the others
    assert [record.build_id for record in list_builds(str(root / ".discopop" / "project"))] == ["small_hd"]
    assert (tmp_path / "proj_discopop_builds" / "small_hd" / "prog").exists()
    assert not (root / "prog").exists()
    # the two runs are stored in the project, by source location
    private = hotspot_data.private_dir(str(root / ".discopop"))
    assert hotspot_data.result_file_indices(private) == [0, 1]
    results = session.load_results()
    assert [run.config for run in results.runs] == ["small", "big"]
    assert results.regions and all(region.key.path.startswith(str(root)) for region in results.regions)

    # measuring again does not compile
    ctx, events = _context()
    succeeded = session.run_batch(ctx, ["big"], repetitions=1, timeouts=timeouts)
    text = _text(events)
    assert succeeded, text
    assert "Using the current build small_hd" in text and "Instrumentation succeeded" not in text
    assert [record.build_id for record in list_builds(str(root / ".discopop" / "project"))] == ["small_hd"]
    assert hotspot_data.result_file_indices(private) == [0, 1, 2]
