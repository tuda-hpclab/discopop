# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Merging profiling runs that come from separately instrumented builds."""

import os
import tempfile
import unittest
from typing import Dict, List

from discopop_hotspot_analyzer.region_keys import (
    collect_runs,
    parse_cs_id,
    parse_hotspot_result,
    render_merged_analysis_input,
    resolve_keys,
)


class TestMergeAcrossBuilds(unittest.TestCase):
    """Two builds of a two-region program, as the instrumentation pass leaves them.

    ``cs_id.txt`` is append-only, so the second build numbers the *same* two
    source regions 3 and 4. Its binary emits a row for every id in the table, so
    run 1 reports 0.0 for the first build's ids 1 and 2.
    """

    CS_ID = "1 loop 10 1\n" "2 func 20 1 kernel\n" "3 loop 10 1\n" "4 func 20 1 kernel\n"
    FILE_MAPPING = "1\t/src/main.c\n"
    RUN_0 = "1 0.500000000\n2 0.250000000\n"
    RUN_1 = "1 0.000000000\n2 0.000000000\n3 0.900000000\n4 0.100000000\n"

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.dot_dp = self._tmp_dir.name
        self.private = os.path.join(self.dot_dp, "hotspot_detection", "private")
        os.makedirs(self.private)
        self._write(os.path.join(self.dot_dp, "FileMapping.txt"), self.FILE_MAPPING)
        self._write(os.path.join(self.private, "cs_id.txt"), self.CS_ID)
        self._write(os.path.join(self.private, "hotspot_result_0.txt"), self.RUN_0)
        self._write(os.path.join(self.private, "hotspot_result_1.txt"), self.RUN_1)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    @staticmethod
    def _write(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text)

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r") as f:
            return f.read()

    def _merged(self, name: str) -> str:
        return os.path.join(self.dot_dp, "hotspot_detection", "merged", name)

    def test_four_ids_collapse_to_two_source_regions(self) -> None:
        keys = resolve_keys(parse_cs_id(self.CS_ID), {1: "/src/main.c"})
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys.values())), 2)

    def test_each_run_resolves_to_the_regions_it_actually_measured(self) -> None:
        keys = resolve_keys(parse_cs_id(self.CS_ID), {1: "/src/main.c"})
        runs = collect_runs(self.private, keys)
        self.assertEqual([run.index for run in runs], [0, 1])
        for run in runs:
            self.assertEqual(len(run.regions), 2, f"run {run.index}")
        # both runs measured the same two source regions, under different ids
        self.assertEqual(set(runs[0].regions), set(runs[1].regions))

    def test_merged_input_holds_one_entry_per_source_region(self) -> None:
        self.assertEqual(render_merged_analysis_input(self.dot_dp), 2)
        merged_cs_id = parse_cs_id(self._read(self._merged("cs_id.txt")))
        self.assertEqual(sorted(merged_cs_id), [1, 2])
        # the fid survives the round trip through the file mapping
        self.assertEqual({fid for _, _, fid, _ in merged_cs_id.values()}, {1})

    def test_every_merged_run_carries_a_real_measurement_for_both_regions(self) -> None:
        render_merged_analysis_input(self.dot_dp)
        for index in (0, 1):
            runtimes = parse_hotspot_result(self._read(self._merged(f"hotspot_result_{index}.txt")))
            self.assertEqual(sorted(runtimes), [1, 2], f"run {index}")
            self.assertTrue(all(value > 0 for value in runtimes.values()), f"run {index}")

    def test_the_two_runs_of_a_region_keep_their_distinct_runtimes(self) -> None:
        """What makes the analyzer's min/max ratio criterion meaningful at all."""
        render_merged_analysis_input(self.dot_dp)
        per_region: Dict[int, List[float]] = {}
        for index in (0, 1):
            for csid, runtime in parse_hotspot_result(self._read(self._merged(f"hotspot_result_{index}.txt"))).items():
                per_region.setdefault(csid, []).append(runtime)
        self.assertEqual(sorted(per_region[1]), [0.5, 0.9])  # the loop at line 10
        self.assertEqual(sorted(per_region[2]), [0.1, 0.25])  # the function at line 20

    def test_stale_zero_rows_are_not_carried_into_the_merged_input(self) -> None:
        render_merged_analysis_input(self.dot_dp)
        text = self._read(self._merged("hotspot_result_1.txt"))
        self.assertNotIn(" 0.000000000", text)


class TestMergeDegenerateInputs(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.dot_dp = self._tmp_dir.name
        self.private = os.path.join(self.dot_dp, "hotspot_detection", "private")
        os.makedirs(self.private)

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def _write(self, path: str, text: str) -> None:
        with open(os.path.join(self.private, path), "w") as f:
            f.write(text)

    def test_missing_cs_id_is_reported_as_nothing_to_merge(self) -> None:
        self.assertIsNone(render_merged_analysis_input(self.dot_dp))

    def test_no_runs_is_reported_as_nothing_to_merge(self) -> None:
        self._write("cs_id.txt", "1 loop 10 1\n")
        self.assertIsNone(render_merged_analysis_input(self.dot_dp))

    def test_runs_without_any_nonzero_measurement_are_nothing_to_merge(self) -> None:
        self._write("cs_id.txt", "1 loop 10 1\n")
        self._write("hotspot_result_0.txt", "1 0.000000000\n")
        self.assertIsNone(render_merged_analysis_input(self.dot_dp))

    def test_a_single_build_merges_to_its_own_regions(self) -> None:
        self._write("cs_id.txt", "1 loop 10 1\n2 loop 20 1\n")
        self._write("hotspot_result_0.txt", "1 0.500000000\n2 0.000000000\n")
        # region 2 never ran, so it carries no measurement and is left out
        self.assertEqual(render_merged_analysis_input(self.dot_dp), 1)

    def test_a_missing_file_mapping_keeps_regions_identifiable(self) -> None:
        self._write("cs_id.txt", "1 loop 10 7\n")
        self._write("hotspot_result_0.txt", "1 0.500000000\n")
        self.assertEqual(render_merged_analysis_input(self.dot_dp), 1)
        merged = os.path.join(self.dot_dp, "hotspot_detection", "merged", "cs_id.txt")
        with open(merged, "r") as f:
            # the original fid is recovered from the "file_<fid>" placeholder
            self.assertEqual(parse_cs_id(f.read())[1], ("LOOP", 10, 7, ""))
