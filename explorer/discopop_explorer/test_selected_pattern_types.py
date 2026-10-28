# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.pattern_detection import PATTERN_TYPES, selected_pattern_types


def test_the_selection_lists_the_pattern_types_in_a_fixed_order() -> None:
    assert selected_pattern_types("task,doall,reduction") == ["reduction", "doall", "task"]
    assert selected_pattern_types("doall") == ["doall"]


def test_a_star_selects_every_pattern_type() -> None:
    assert selected_pattern_types("*") == PATTERN_TYPES


def test_blanks_and_unknown_names_are_ignored() -> None:
    assert selected_pattern_types(" doall , nonsense") == ["doall"]
