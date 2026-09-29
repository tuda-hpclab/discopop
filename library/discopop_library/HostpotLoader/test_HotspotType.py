# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import unittest

from discopop_library.HostpotLoader.HotspotType import HotspotType, parse_hotspot_types


class TestParseHotspotTypes(unittest.TestCase):
    def test_parses_the_explorer_default(self) -> None:
        self.assertEqual(parse_hotspot_types("yes,maybe"), [HotspotType.YES, HotspotType.MAYBE])

    def test_accepts_any_capitalization_and_surrounding_whitespace(self) -> None:
        self.assertEqual(parse_hotspot_types(" YES , Maybe "), [HotspotType.YES, HotspotType.MAYBE])

    def test_preserves_order_and_collapses_duplicates(self) -> None:
        self.assertEqual(parse_hotspot_types("maybe,yes,maybe"), [HotspotType.MAYBE, HotspotType.YES])

    def test_accepts_a_single_type(self) -> None:
        self.assertEqual(parse_hotspot_types("no"), [HotspotType.NO])

    def test_rejects_an_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            parse_hotspot_types("yes,perhaps")

    def test_rejects_an_empty_selection(self) -> None:
        for empty in ["", "   ", ",", " , "]:
            with self.subTest(input=empty):
                with self.assertRaises(ValueError):
                    parse_hotspot_types(empty)
