# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unit tests for the full-fidelity Hotspots.json loader."""

import json
import os
import tempfile
import unittest
from typing import Any, Dict, List

from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    hotspots_are_degenerate,
    load_detailed_hotspots,
)


def _region(csid: int, hotness: str, runtimes: List[float], typ: str = "LOOP") -> Dict[str, Any]:
    """One Hotspots.json entry, with the derived fields computed as the analyzer does."""
    return {
        "csid": csid,
        "typ": typ,
        "fid": 1,
        "lineNum": 100 + csid,
        "name": "" if typ == "LOOP" else "func" + str(csid),
        "runtimes": runtimes,
        "level": 0,
        "hot": True,
        "hotness": hotness,
        "delta": max(runtimes) - min(runtimes),
        "avr": sum(runtimes) / len(runtimes),
        "sum": sum(runtimes),
        "minVal": min(runtimes),
        "maxVal": max(runtimes),
        "ratio": 1.0 / ((min(runtimes) / max(runtimes)) + 1.0),
        "topAvr": True,
        "topRatio": True,
    }


def _write(directory: str, regions: List[Dict[str, Any]]) -> None:
    hotspot_dir = os.path.join(directory, "hotspot_detection")
    os.makedirs(hotspot_dir, exist_ok=True)
    with open(os.path.join(hotspot_dir, "Hotspots.json"), "w") as f:
        json.dump({"code_regions": regions}, f)


class TestDetailedHotspotLoader(unittest.TestCase):
    def test_missing_results_yield_an_empty_list(self) -> None:
        """The caller decides whether absent hotspot data is an error."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual([], load_detailed_hotspots(tmp))

    def test_every_field_survives_the_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, [_region(1, "YES", [1.0, 4.0])])
            regions = load_detailed_hotspots(tmp)

            self.assertEqual(1, len(regions))
            region = regions[0]
            self.assertEqual(1, region.csid)
            self.assertEqual(HotspotNodeType.LOOP, region.node_type)
            self.assertEqual(1, region.file_id)
            self.assertEqual(101, region.start_line)
            self.assertEqual(HotspotType.YES, region.hotness)
            self.assertEqual([1.0, 4.0], region.runtimes)
            self.assertAlmostEqual(2.5, region.avr)
            self.assertAlmostEqual(1.0, region.min_val)
            self.assertAlmostEqual(4.0, region.max_val)
            self.assertAlmostEqual(0.8, region.ratio)
            self.assertTrue(region.top_avr)
            self.assertTrue(region.top_ratio)

    def test_functions_and_loops_are_both_returned_unfiltered(self) -> None:
        """Unlike hostpot_loader.run(), this loader never drops entries."""
        with tempfile.TemporaryDirectory() as tmp:
            _write(
                tmp,
                [
                    _region(1, "YES", [1.0, 4.0]),
                    _region(2, "MAYBE", [0.5, 0.6]),
                    _region(3, "NO", [0.01, 0.01], typ="FUNCTION"),
                ],
            )
            regions = load_detailed_hotspots(tmp)

            self.assertEqual(3, len(regions))
            self.assertEqual([HotspotType.YES, HotspotType.MAYBE, HotspotType.NO], [r.hotness for r in regions])
            self.assertEqual(
                [HotspotNodeType.LOOP, HotspotNodeType.LOOP, HotspotNodeType.FUNCTION],
                [r.node_type for r in regions],
            )

    def test_older_files_without_the_derived_flags_still_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = _region(1, "YES", [1.0, 4.0])
            del entry["topAvr"]
            del entry["topRatio"]
            _write(tmp, [entry])

            region = load_detailed_hotspots(tmp)[0]
            self.assertFalse(region.top_avr)
            self.assertFalse(region.top_ratio)
            self.assertAlmostEqual(4.0, region.max_val)

    def test_single_run_measurements_are_reported_as_degenerate(self) -> None:
        """One profiling run means ratio == 0.5 everywhere, so it carries no information."""
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, [_region(1, "YES", [3.0]), _region(2, "MAYBE", [1.0])])
            self.assertTrue(hotspots_are_degenerate(load_detailed_hotspots(tmp)))

    def test_multiple_runs_are_not_degenerate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, [_region(1, "YES", [1.0, 4.0]), _region(2, "MAYBE", [1.0])])
            self.assertFalse(hotspots_are_degenerate(load_detailed_hotspots(tmp)))

    def test_no_regions_counts_as_degenerate(self) -> None:
        self.assertTrue(hotspots_are_degenerate([]))
