# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Collapse suggestions for do-all loop nests: one class per program below this directory."""

from pathlib import Path

from test.end_to_end.pipeline import PipelineTestCase

HERE = Path(__file__).parent


class LoopCollapseTestCase(PipelineTestCase):
    ENABLE_PATTERNS = "doall,reduction"


class NoCollapseChecks:
    """Mixin of the negative cases (no TestCase itself, so it is not collected): no do-all suggestion may collapse
    loops."""

    def test_no_collapse_identified(self: LoopCollapseTestCase) -> None:  # type: ignore[misc]
        for do_all_info in self.test_output.patterns.do_all:
            self.assertEqual(
                do_all_info.collapse_level,
                1,
                "unexpected collapse suggested at " + str(do_all_info.start_line),
            )
        for do_all_info in self.test_output.patterns.do_all:
            self.assertEqual(do_all_info.collapsed_pattern_ids, [])


class TestNotNested(NoCollapseChecks, LoopCollapseTestCase):
    """None of the loops is nested, so there is nothing to collapse."""

    SRC_DIR = HERE / "negative" / "simple_1" / "src"


class TestInnerLoopDoallOnly(NoCollapseChecks, LoopCollapseTestCase):
    """Only the inner loop is a do-all loop. Collapsing requires every loop of the nest to be parallelizable, so the
    enclosing loop must not be folded into it."""

    SRC_DIR = HERE / "negative" / "inner_loop_doall_only" / "src"


class TestOuterLoopDoallOnly(NoCollapseChecks, LoopCollapseTestCase):
    """Only the outer loop is a do-all loop. The nested loop carries a dependency, so it must not be folded into the
    outer loop."""

    SRC_DIR = HERE / "negative" / "outer_loop_doall_only" / "src"


class TestImperfectNesting(NoCollapseChecks, LoopCollapseTestCase):
    """The assignment at line 20 sits in the outer loop body next to the inner loop, so the two loops are not
    perfectly nested. Collapsing them would execute the assignment once per combined iteration instead of once per
    iteration of the outer loop."""

    SRC_DIR = HERE / "negative" / "imperfect_nesting" / "src"

    def test_both_loops_of_the_nest_are_do_all(self) -> None:
        """Pins the reason the collapse is rejected. Both loops of the nest at lines 19 and 22 are
        parallelizable, so it is only the imperfect nesting which prevents collapsing them. Without
        this the negative result could be caused by a missing do-all suggestion instead."""
        start_lines = [p.start_line for p in self.test_output.patterns.do_all]
        self.assertIn("1:19", start_lines, "the outer loop of the nest must be a do-all loop")
        self.assertIn("1:22", start_lines, "the inner loop of the nest must be a do-all loop")


class TestTwoLevelCollapse(LoopCollapseTestCase):
    """The loops at lines 16 and 18 are perfectly nested do-all loops."""

    SRC_DIR = HERE / "positive" / "simple_1" / "src"

    def test_two_level_collapse_identified(self) -> None:
        """A collapse of both loops must be suggested based on the outer one."""
        collapsed = [p for p in self.test_output.patterns.do_all if p.collapse_level == 2]
        self.assertEqual(len(collapsed), 1, "expected exactly one two level collapse")
        self.assertEqual(collapsed[0].start_line, "1:16", "the collapse must be based on the outer loop")

    def test_collapse_records_the_patterns_it_replaces(self) -> None:
        """Applying the collapse excludes applying the do-all patterns of the collapsed loops, so
        both of them must be recorded."""
        collapsed = [p for p in self.test_output.patterns.do_all if p.collapse_level == 2]
        self.assertEqual(len(collapsed[0].collapsed_pattern_ids), 2)
        collapsed_lines = [
            p.start_line for p in self.test_output.patterns.do_all if p.pattern_id in collapsed[0].collapsed_pattern_ids
        ]
        self.assertEqual(sorted(collapsed_lines), ["1:16", "1:18"])

    def test_no_deeper_collapse_identified(self) -> None:
        """The nest is only two loops deep."""
        for do_all_info in self.test_output.patterns.do_all:
            self.assertLessEqual(do_all_info.collapse_level, 2)

    def test_the_collapsed_patterns_are_kept_as_alternatives(self) -> None:
        """The collapse is an additional suggestion, it does not remove the individual do-all
        suggestions for the loops it folds in."""
        start_lines = [p.start_line for p in self.test_output.patterns.do_all if p.collapse_level == 1]
        for expected_line in ["1:10", "1:16", "1:18"]:
            self.assertIn(expected_line, start_lines)
