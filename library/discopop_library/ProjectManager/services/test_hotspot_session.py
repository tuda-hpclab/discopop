# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import os
import queue
import threading
from pathlib import Path
from typing import List

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import MeasurementLog, MeasurementRun
from discopop_library.ProjectManager.services import hotspot_session
from discopop_library.ProjectManager.services.hotspot_session import HOTSPOT_ANALYZER, HotspotSession
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkOutput


def make_session(tmp_path: Path) -> HotspotSession:
    (tmp_path / ".discopop" / "project" / "configs").mkdir(parents=True)
    arguments = ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(tmp_path),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions="1",
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="x",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
    )
    return HotspotSession(arguments)


def context() -> "tuple[WorkContext, queue.Queue[WorkEvent]]":
    events: "queue.Queue[WorkEvent]" = queue.Queue()
    return WorkContext(events, threading.Event()), events


def output(events: "queue.Queue[WorkEvent]") -> str:
    texts: List[str] = []
    while not events.empty():
        event = events.get_nowait()
        if isinstance(event, WorkOutput):
            texts.append(event.text)
    return "".join(texts)


def test_the_request_is_a_private_copy_with_the_timeouts(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    request = session.make_request("cfg", needs_compile=True, repetitions=2, timeouts=(1.0, 2.0, 3.0))
    assert (request.arguments.timeout_execution, request.arguments.timeout_compilation) == (1.0, 2.0)
    assert request.arguments.timeout_validation == 3.0
    assert request.arguments.execute_inplace and not request.arguments.skip_cleanup
    assert request.arguments.apply_suggestions is None and request.arguments.label_prefix == ""
    assert session.arguments.skip_cleanup and session.arguments.timeout_execution is None
    assert request.config_path == os.path.join(session.arguments.project_config_dir, "cfg")
    assert request.settings_path.endswith("hd_settings.json") and request.repetitions == 2


def test_the_log_round_trips_and_a_missing_one_is_empty(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert session.load_log() == MeasurementLog()
    log = MeasurementLog(compile_script="/x/compile.sh", runs=[MeasurementRun(0, "c", "t", 1.0, 0, {"k": 1.0})])
    session.save_log(log)
    assert session.load_log() == log


def test_a_different_compile_script_needs_its_own_build(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    assert not session.compile_script_differs("cfg")
    session.save_log(MeasurementLog(compile_script=str(tmp_path / "other.sh")))
    assert session.compile_script_differs("cfg") and not session.compile_script_differs(None)


def test_a_run_resolves_to_region_keys_and_drops_idle_regions(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    keys = {1: hotspot_data.RegionKey("/p/a.cpp", 3, hotspot_data.KIND_LOOP)}
    (tmp_path / "hotspot_result_4.txt").write_text("1 2.5\n2 1.0\n3 0\n")
    assert session.resolve_run_regions(str(tmp_path), 4, keys) == {keys[1].serialize(): 2.5}
    assert session.resolve_run_regions(str(tmp_path), 5, keys) == {}


def test_without_settings_nothing_runs(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    ctx, events = context()
    request = session.make_request("cfg", needs_compile=True, repetitions=1, timeouts=(None, None, None))
    assert session.run(ctx, request) is False
    assert "hd_settings.json not found" in output(events)


def test_the_analysis_is_skipped_without_data_or_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = make_session(tmp_path)
    ctx, events = context()
    assert session.invoke_analyzer(ctx) is False and "no profiling data found" in output(events)
    private = Path(hotspot_data.private_dir(session.arguments.dot_dp))
    private.mkdir(parents=True)
    assert session.invoke_analyzer(ctx) is False and "no accumulated runs" in output(events)

    (private / "cs_id.txt").write_text("1 loop 3 1\n")
    (private / "hotspot_result_0.txt").write_text("1 2.0\n")
    Path(session.arguments.dot_dp, "FileMapping.txt").write_text(f"1\t{tmp_path}/a.cpp\n")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(hotspot_session, "environment_with_interpreter_on_path", lambda: {"PATH": str(tmp_path)})
    assert session.invoke_analyzer(ctx) is False
    text = output(events)
    assert "Merged 1 run(s) over 1 code region(s)" in text and f"{HOTSPOT_ANALYZER} not found on PATH" in text
    assert os.path.exists(hotspot_data.merged_cs_id_path(session.arguments.dot_dp))


def test_clearing_keeps_the_file_mapping(tmp_path: Path) -> None:
    session = make_session(tmp_path)
    Path(hotspot_data.private_dir(session.arguments.dot_dp)).mkdir(parents=True)
    Path(session.arguments.dot_dp, "FileMapping.txt").write_text("")
    assert session.has_data()
    session.delete_hotspot_dir()
    assert not session.has_data() and os.path.exists(os.path.join(session.arguments.dot_dp, "FileMapping.txt"))
    session.delete_hotspot_dir()  # nothing left: no error
