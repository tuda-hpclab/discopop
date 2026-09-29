# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
import tempfile
import unittest
from typing import Any, Dict, List

from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots


def _region(csid: int, hotness: str, typ: str = "LOOP") -> Dict[str, Any]:
    return {
        "csid": csid,
        "typ": typ,
        "fid": 1,
        "lineNum": 10 * csid,
        "name": "",
        "hotness": hotness,
        "avr": 0.001 * csid,
    }


class TestHotspotLoaderSelection(unittest.TestCase):
    """The loader is what turns a hotspot type selection into an actual filter."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.dot_discopop = self._tmp_dir.name
        hotspot_detection_dir = os.path.join(self.dot_discopop, "hotspot_detection")
        os.makedirs(hotspot_detection_dir)
        with open(os.path.join(hotspot_detection_dir, "Hotspots.json"), "w") as f:
            json.dump(
                {
                    "code_regions": [
                        _region(1, "YES"),
                        _region(2, "MAYBE"),
                        _region(3, "NO"),
                        _region(4, "YES", typ="FUNCTION"),
                    ]
                },
                f,
            )

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _load(self, types: List[HotspotType]) -> Dict[HotspotType, List[Any]]:
        return load_hotspots(
            HotspotLoaderArguments(
                verbose=False,
                dot_discopop_path=self.dot_discopop,
                get_loops=True,
                get_functions=True,
                get_YES=HotspotType.YES in types,
                get_MAYBE=HotspotType.MAYBE in types,
                get_NO=HotspotType.NO in types,
                log_level="WARNING",
                write_log=False,
            )
        )

    def test_default_selection_keeps_yes_and_maybe(self) -> None:
        loaded = self._load([HotspotType.YES, HotspotType.MAYBE])
        self.assertEqual(sorted(loaded.keys()), sorted([HotspotType.YES, HotspotType.MAYBE]))
        self.assertEqual(len(loaded[HotspotType.YES]), 2)  # the LOOP and the FUNCTION region
        self.assertEqual(len(loaded[HotspotType.MAYBE]), 1)

    def test_yes_only_drops_the_maybe_regions(self) -> None:
        loaded = self._load([HotspotType.YES])
        self.assertEqual(list(loaded.keys()), [HotspotType.YES])

    def test_no_can_be_selected_as_well(self) -> None:
        loaded = self._load([HotspotType.NO])
        self.assertEqual(list(loaded.keys()), [HotspotType.NO])
        fid, start_line, node_type, name, average_runtime = loaded[HotspotType.NO][0]
        self.assertEqual((fid, start_line, node_type, name), (1, 30, HotspotNodeType.LOOP, ""))
        self.assertAlmostEqual(average_runtime, 0.003)

    def test_missing_hotspot_information_yields_no_filter(self) -> None:
        with tempfile.TemporaryDirectory() as empty_dir:
            loaded = load_hotspots(
                HotspotLoaderArguments(
                    verbose=False,
                    dot_discopop_path=empty_dir,
                    get_loops=True,
                    get_functions=True,
                    get_YES=True,
                    get_MAYBE=True,
                    get_NO=False,
                    log_level="WARNING",
                    write_log=False,
                )
            )
        self.assertEqual(loaded, {})
