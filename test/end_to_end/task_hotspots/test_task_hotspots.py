# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end test of the hotspot information of task patterns: the group of the recursive calls of fib carries the
class of the hotspot function fib, and the autotuner's classification (get_patterns_by_hotspot_type) uses it."""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from test.end_to_end.pipeline import build_and_profile, explore

import unittest

SRC = Path(__file__).parent.parent / "task_only" / "src"


def _file_id(dot_discopop: Path) -> int:
    """the id of the source file in the file mapping (lines: "<id>\t<path>")"""
    for line in (dot_discopop / "FileMapping.txt").read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and Path(parts[1]).suffix in (".c", ".cpp"):
            return int(parts[0])
    raise AssertionError("no source file in the file mapping")


def _write_hotspots(dot_discopop: Path, regions: List[Dict[str, Any]]) -> None:
    directory = dot_discopop / "hotspot_detection"
    directory.mkdir(exist_ok=True)
    (directory / "Hotspots.json").write_text(json.dumps({"code_regions": regions}))


def _region(file_id: int, typ: str, name: str, line: int, hotness: str = "YES") -> Dict[str, Any]:
    return {"csid": line, "typ": typ, "fid": file_id, "lineNum": line, "name": name, "hotness": hotness, "avr": 0.25}


class TestTaskHotspots(unittest.TestCase):
    dot_discopop: Path
    file_id: int

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="discopop_e2e_")
        cls.addClassCleanup(tmp.cleanup)
        cls.dot_discopop = build_and_profile(SRC, Path(tmp.name) / "src")
        cls.file_id = _file_id(cls.dot_discopop)

    def _regions(self, hotspots: List[Dict[str, Any]]) -> Any:
        _write_hotspots(self.dot_discopop, hotspots)
        result = explore(self.dot_discopop, "task")
        regions = [p for p in result.patterns.task if type(p) is ParallelRegionInfo]
        self.assertEqual(len(regions), 1)
        return result, regions[0]

    def test_the_group_of_the_recursive_calls_is_a_hotspot_if_the_function_is(self) -> None:
        result, region = self._regions([_region(self.file_id, "FUNCTION", "fib", 1)])
        self.assertEqual(region.hotspot_type, HotspotType.YES)
        self.assertEqual(region.hotspot_runtime, 0.25)
        for task in (p for p in result.patterns.task if type(p) is TaskParallelismInfo):
            self.assertEqual(task.hotspot_type, HotspotType.YES)

    def test_the_autotuner_classifies_the_group_by_the_attached_class(self) -> None:
        result, region = self._regions([_region(self.file_id, "FUNCTION", "fib", 1)])
        loaded = load_hotspots(
            HotspotLoaderArguments(
                verbose=False,
                dot_discopop_path=str(self.dot_discopop),
                get_loops=True,
                get_functions=True,
                get_YES=True,
                get_MAYBE=True,
                get_NO=True,
                log_level="WARNING",
                write_log=False,
            )
        )
        by_type = get_patterns_by_hotspot_type(result, loaded)
        self.assertIn(region.pattern_id, by_type[HotspotType.YES])

    def test_the_class_survives_the_patterns_json(self) -> None:
        self._regions([_region(self.file_id, "FUNCTION", "fib", 1, hotness="MAYBE")])
        patterns = json.loads((self.dot_discopop / "explorer" / "patterns.json").read_text())["patterns"]["task"]
        self.assertIn("hotspot_type", json.dumps(patterns))

    def test_a_hotspot_of_another_function_does_not_classify_the_group(self) -> None:
        _, region = self._regions([_region(self.file_id, "FUNCTION", "main", 1)])
        self.assertIsNone(region.hotspot_type)
        self.assertIsNone(region.hotspot_runtime)

    def test_without_hotspot_information_nothing_is_attached(self) -> None:
        hotspot_file = self.dot_discopop / "hotspot_detection" / "Hotspots.json"
        if hotspot_file.exists():
            hotspot_file.unlink()
        result = explore(self.dot_discopop, "task")
        region = [p for p in result.patterns.task if type(p) is ParallelRegionInfo][0]
        self.assertIsNone(region.hotspot_type)
