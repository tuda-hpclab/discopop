# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import shutil
from pathlib import Path
from typing import List

import pytest

from discopop_library import AnalysisRecord as ar
from discopop_library.AnalysisRecord import (
    DEFAULT_PATTERNS,
    RECORD_FILENAME,
    STEPS,
    analysis_status,
    clear_record,
    covers,
    record_hotspot_run,
    record_step,
    step_status,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "md.cpp").write_text("int main() { return 0; }\n")
    (root / ".discopop").mkdir()
    return root


def _touch(dot: Path, rel: str, text: str = "x") -> None:
    p = dot / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _outputs(dot: Path, step: str) -> None:
    if step == "hotspot_detection":
        _touch(dot, "hotspot_detection/private/hotspot_result_0.txt")
    elif step == "hotspot_analysis":
        _touch(dot, "hotspot_detection/Hotspots.json", "{}")
    elif step == "dependence_profiling":
        _touch(dot, "profiler/Data.xml")
        _touch(dot, "profiler/dynamic_dependencies.txt")
    elif step == "pattern_detection":
        _touch(dot, "explorer/patterns.json", json.dumps({"enabled_patterns": list(DEFAULT_PATTERNS)}))
    elif step == "patch_generation":
        _touch(dot, "patch_generator/1/patch.diff")


def _full(project: Path) -> Path:
    dot = project / ".discopop"
    for s in STEPS:
        _outputs(dot, s)
    record_hotspot_run(str(dot), "tiny", "compile.sh")
    record_step(str(dot), "hotspot_analysis", {})
    record_step(str(dot), "dependence_profiling", {"config": "tiny", "compile_script": "compile.sh"})
    record_step(str(dot), "pattern_detection", {"enabled_patterns": sorted(DEFAULT_PATTERNS), "options": {}})
    record_step(str(dot), "patch_generation", {})
    return dot


def _record(dot: Path) -> dict:  # type: ignore[type-arg]
    return json.loads((dot / RECORD_FILENAME).read_text())  # type: ignore[no-any-return]


def test_public_api() -> None:
    for name in ar.__all__:
        assert hasattr(ar, name)
    assert DEFAULT_PATTERNS == ("doall", "reduction", "task")


def test_all_current_after_recording(project: Path) -> None:
    dot = _full(project)
    st = analysis_status(str(dot))
    assert list(st) == list(STEPS)
    for s in STEPS:
        assert st[s].state == "current", (s, st[s].reason)
        assert st[s].basis == "fingerprint"
        assert st[s].completed_at
    assert st["hotspot_analysis"].params["configs"] == ["tiny"]
    assert _record(dot)["format"] == 1
    assert _record(dot)["project_root"] == os.path.realpath(project)


def test_missing_outputs_win_over_record(project: Path) -> None:
    dot = _full(project)
    shutil.rmtree(dot / "profiler")
    st = analysis_status(str(dot))
    assert st["dependence_profiling"].state == "missing"
    assert st["dependence_profiling"].basis == "none"
    assert st["hotspot_detection"].state == "current"
    # the dependent step notices the removed upstream
    assert st["pattern_detection"].state == "stale"
    assert "dependence_profiling" in st["pattern_detection"].reason


def test_source_change_makes_stale_and_lists_files(project: Path) -> None:
    dot = _full(project)
    (project / "md.cpp").write_text("int main() { return 1; }\n")
    st = analysis_status(str(dot))
    for s in STEPS:
        assert st[s].state == "stale"
    assert st["pattern_detection"].changed_files == ["md.cpp"]
    assert "md.cpp" in st["pattern_detection"].reason
    (project / "md.cpp").write_text("int main() { return 0; }\n")
    assert step_status(str(dot), "pattern_detection").state == "current"


def test_new_source_file_makes_stale(project: Path) -> None:
    dot = _full(project)
    (project / "extra.h").write_text("int y;\n")
    assert step_status(str(dot), "patch_generation").changed_files == ["extra.h"]


def test_upstream_rerun_invalidates_downstream_even_within_a_second(project: Path) -> None:
    dot = _full(project)
    record_step(str(dot), "dependence_profiling", {"config": "tiny", "compile_script": "compile.sh"})
    st = analysis_status(str(dot))
    assert st["dependence_profiling"].state == "current"
    assert st["pattern_detection"].state == "stale"
    assert "dependence_profiling" in st["pattern_detection"].reason
    assert st["patch_generation"].state == "stale"  # transitively
    record_step(str(dot), "pattern_detection", {"enabled_patterns": list(DEFAULT_PATTERNS)})
    st = analysis_status(str(dot))
    assert st["pattern_detection"].state == "current"
    assert st["patch_generation"].state == "stale"
    assert "pattern_detection" in st["patch_generation"].reason


def test_unique_run_ids(project: Path) -> None:
    dot = project / ".discopop"
    record_step(str(dot), "patch_generation", {})
    first = _record(dot)["steps"]["patch_generation"]["run_id"]
    record_step(str(dot), "patch_generation", {})
    assert _record(dot)["steps"]["patch_generation"]["run_id"] != first


def test_upstream_recorded_later_invalidates(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "dependence_profiling")
    _outputs(dot, "pattern_detection")
    record_step(str(dot), "dependence_profiling", {})
    record_step(str(dot), "pattern_detection", {})  # no hotspot_analysis recorded yet
    assert step_status(str(dot), "pattern_detection").state == "current"
    _outputs(dot, "hotspot_detection")
    _outputs(dot, "hotspot_analysis")
    record_step(str(dot), "hotspot_analysis", {})
    assert step_status(str(dot), "pattern_detection").state == "stale"


def test_relocation_is_stale(project: Path, tmp_path: Path) -> None:
    dot = _full(project)
    other = tmp_path / "copy"
    shutil.copytree(project, other)
    st = analysis_status(str(other / ".discopop"))
    for s in STEPS:
        assert st[s].state == "stale"
        assert "another location" in st[s].reason
        assert str(project) in st[s].reason or os.path.realpath(project) in st[s].reason
    assert step_status(str(dot), "patch_generation").state == "current"


def test_write_at_new_location_drops_foreign_steps(project: Path, tmp_path: Path) -> None:
    _full(project)
    other = tmp_path / "copy"
    shutil.copytree(project, other)
    record_step(str(other / ".discopop"), "patch_generation", {})
    assert list(_record(other / ".discopop")["steps"]) == ["patch_generation"]
    assert step_status(str(other / ".discopop"), "pattern_detection").basis == "mtime"  # no record -> legacy


def test_variant_copy_default_project_root(project: Path) -> None:
    dot = project / ".discopop_no_states"
    dot.mkdir()
    _outputs(dot, "patch_generation")
    record_step(str(dot), "patch_generation", {})
    assert _record(dot)["project_root"] == os.path.realpath(project)
    assert step_status(str(dot), "patch_generation").state == "current"


def test_explicit_project_root(project: Path, tmp_path: Path) -> None:
    dot = tmp_path / "elsewhere" / ".discopop"
    dot.mkdir(parents=True)
    _outputs(dot, "patch_generation")
    record_step(str(dot), "patch_generation", {}, project_root=str(project))
    assert step_status(str(dot), "patch_generation", project_root=str(project)).state == "current"
    assert step_status(str(dot), "patch_generation").state == "stale"


def test_hotspot_accumulates_across_scripts_with_same_digest(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "hotspot_detection")
    record_hotspot_run(str(dot), "tiny", str(project / "configs" / "tiny" / "compile.sh"))
    first = _record(dot)["steps"]["hotspot_detection"]["run_id"]
    record_hotspot_run(str(dot), "small", str(project / "configs" / "small" / "compile.sh"))
    entry = _record(dot)["steps"]["hotspot_detection"]
    assert entry["params"]["configs"] == {
        "tiny": "configs/tiny/compile.sh",
        "small": "configs/small/compile.sh",
    }
    assert entry["run_id"] != first
    s = step_status(str(dot), "hotspot_detection")
    assert covers(s, configs=["small", "tiny"])
    assert not covers(s, configs=["tiny"])
    assert not covers(s, configs=["tiny", "small", "large"])


def test_hotspot_outside_script_kept_absolute(project: Path, tmp_path: Path) -> None:
    dot = project / ".discopop"
    outside = str(tmp_path / "other" / "compile.sh")
    record_hotspot_run(str(dot), "a", outside)
    assert _record(dot)["steps"]["hotspot_detection"]["params"]["configs"] == {"a": outside}


def test_hotspot_resets_on_changed_digest(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "hotspot_detection")
    record_hotspot_run(str(dot), "tiny", "c.sh")
    (project / "md.cpp").write_text("int changed;\n")
    record_hotspot_run(str(dot), "small", "c.sh")
    assert _record(dot)["steps"]["hotspot_detection"]["params"]["configs"] == {"small": "c.sh"}


def test_hotspot_rerun_invalidates_analysis(project: Path) -> None:
    dot = _full(project)
    record_hotspot_run(str(dot), "small", "compile.sh")
    st = analysis_status(str(dot))
    assert st["hotspot_analysis"].state == "stale"
    assert st["pattern_detection"].state == "stale"
    assert st["dependence_profiling"].state == "current"


def test_hotspot_analysis_configs_default_from_detection(project: Path) -> None:
    dot = project / ".discopop"
    record_hotspot_run(str(dot), "b", "c.sh")
    record_hotspot_run(str(dot), "a", "c.sh")
    record_step(str(dot), "hotspot_analysis", {})
    assert _record(dot)["steps"]["hotspot_analysis"]["params"]["configs"] == ["a", "b"]
    record_step(str(dot), "hotspot_analysis", {"configs": ["z"]})
    assert _record(dot)["steps"]["hotspot_analysis"]["params"]["configs"] == ["z"]


def test_unreadable_record_is_absent_and_overwritten(project: Path, caplog: pytest.LogCaptureFixture) -> None:
    dot = project / ".discopop"
    _outputs(dot, "patch_generation")
    (dot / RECORD_FILENAME).write_text("{not json")
    with caplog.at_level("WARNING"):
        st = step_status(str(dot), "patch_generation")
    assert st.basis == "mtime"  # legacy
    assert "unreadable" in caplog.text
    record_step(str(dot), "patch_generation", {})
    assert step_status(str(dot), "patch_generation").basis == "fingerprint"
    (dot / RECORD_FILENAME).write_text("[1, 2]")
    assert step_status(str(dot), "patch_generation").basis == "mtime"


def test_atomic_write_leaves_no_temp_files(project: Path) -> None:
    dot = project / ".discopop"
    record_step(str(dot), "patch_generation", {})
    record_step(str(dot), "pattern_detection", {})
    assert sorted(os.listdir(dot)) == [RECORD_FILENAME]


def test_recording_never_raises(project: Path, caplog: pytest.LogCaptureFixture) -> None:
    missing = project / "nope" / ".discopop"
    with caplog.at_level("WARNING"):
        record_step(str(missing), "patch_generation", {})
        record_hotspot_run(str(missing), "a", "c.sh")
        record_step(str(project / ".discopop"), "bogus", {})
    assert caplog.text.count("Could not record") == 3
    clear_record(str(missing))  # no raise


def test_unserializable_params_do_not_raise_or_corrupt(project: Path) -> None:
    dot = project / ".discopop"
    record_step(str(dot), "patch_generation", {})
    record_step(str(dot), "pattern_detection", {"bad": object()})
    assert list(_record(dot)["steps"]) == ["patch_generation"]
    assert sorted(os.listdir(dot)) == [RECORD_FILENAME]


def test_clear_record(project: Path) -> None:
    dot = project / ".discopop"
    record_step(str(dot), "patch_generation", {})
    clear_record(str(dot))
    assert not (dot / RECORD_FILENAME).exists()
    clear_record(str(dot))


# ---------------------------------------------------------------- legacy


def _age(path: Path, seconds: float) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + seconds))


def test_legacy_mtime_current_and_stale(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "pattern_detection")
    src = project / "md.cpp"
    os.utime(src, (1_000_000, 1_000_000))
    st = step_status(str(dot), "pattern_detection")
    assert (st.state, st.basis) == ("current", "mtime")
    os.utime(src, (4_000_000_000, 4_000_000_000))
    st = step_status(str(dot), "pattern_detection")
    assert (st.state, st.basis) == ("stale", "mtime")


def test_legacy_reads_enabled_patterns(project: Path) -> None:
    dot = project / ".discopop"
    _touch(dot, "explorer/patterns.json", json.dumps({"enabled_patterns": ["task", "doall"]}))
    os.utime(project / "md.cpp", (1_000_000, 1_000_000))
    st = step_status(str(dot), "pattern_detection")
    assert st.params == {"enabled_patterns": ["doall", "task"]}
    assert not covers(st, enabled_patterns=DEFAULT_PATTERNS)
    assert covers(st, enabled_patterns=["doall"])
    _touch(dot, "explorer/patterns.json", "{}")
    assert step_status(str(dot), "pattern_detection").params == {"enabled_patterns": []}
    _touch(dot, "explorer/patterns.json", "garbage")
    assert step_status(str(dot), "pattern_detection").params == {}


def test_legacy_reads_profiled_configurations(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "hotspot_detection")
    _touch(dot, "hotspot_detection/profiled_configurations.json", json.dumps(["a", "b"]))
    os.utime(project / "md.cpp", (1_000_000, 1_000_000))
    st = step_status(str(dot), "hotspot_detection")
    assert set(st.params["configs"]) == {"a", "b"}
    assert covers(st, configs=["b", "a"])
    assert not covers(st, configs=["a"])


def test_legacy_directory_output_uses_newest_content(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "patch_generation")
    os.utime(project / "md.cpp", (1_000_000, 1_000_000))
    os.utime(dot / "patch_generator", (500_000, 500_000))
    assert step_status(str(dot), "patch_generation").state == "current"  # file inside is newer


def test_hotspot_detection_needs_a_result_file(project: Path) -> None:
    dot = project / ".discopop"
    (dot / "hotspot_detection" / "private").mkdir(parents=True)
    record_hotspot_run(str(dot), "a", "c.sh")
    assert step_status(str(dot), "hotspot_detection").state == "missing"
    _touch(dot, "hotspot_detection/private/other.txt")
    assert step_status(str(dot), "hotspot_detection").state == "missing"
    _outputs(dot, "hotspot_detection")
    assert step_status(str(dot), "hotspot_detection").state == "current"


def test_recorded_step_beside_legacy_upstream(project: Path) -> None:
    dot = project / ".discopop"
    _outputs(dot, "hotspot_detection")
    _outputs(dot, "hotspot_analysis")  # legacy, no record
    _outputs(dot, "dependence_profiling")
    _outputs(dot, "pattern_detection")
    record_step(str(dot), "pattern_detection", {})
    st = analysis_status(str(dot))
    assert st["hotspot_analysis"].basis in ("mtime", "none")
    assert st["pattern_detection"].state == "current"


# ---------------------------------------------------------------- covers


def test_covers_semantics(project: Path) -> None:
    dot = _full(project)
    s = step_status(str(dot), "pattern_detection")
    assert covers(s)
    assert covers(s, enabled_patterns=DEFAULT_PATTERNS)
    assert covers(s, enabled_patterns=["doall"])
    assert not covers(s, enabled_patterns=["doall", "geometric_decomposition"])
    assert covers(s, options={})
    assert not covers(s, options={"x": 1})
    assert not covers(s, unknown=1)
    d = step_status(str(dot), "dependence_profiling")
    assert covers(d, config="tiny")
    assert not covers(d, config="small")
    a = step_status(str(dot), "hotspot_analysis")
    assert covers(a, configs=["tiny"])


def test_covers_false_unless_current(project: Path) -> None:
    dot = _full(project)
    (project / "md.cpp").write_text("changed\n")
    assert not covers(step_status(str(dot), "pattern_detection"))
    shutil.rmtree(dot / "explorer")
    assert not covers(step_status(str(dot), "pattern_detection"))


def test_unknown_step_rejected(project: Path) -> None:
    with pytest.raises(ValueError):
        step_status(str(project / ".discopop"), "nope")


def test_changed_files_names_in_reason(project: Path) -> None:
    dot = _full(project)
    names: List[str] = []
    for i in range(5):
        (project / f"f{i}.c").write_text("x")
        names.append(f"f{i}.c")
    s = step_status(str(dot), "patch_generation")
    assert s.changed_files == names
    assert "2 more" in s.reason
