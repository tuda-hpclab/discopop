"""Tests for the basic block machinery that replaces omitted instrumentation.

Accesses to variables the pass can resolve statically do not get their own ``__dp_read`` or
``__dp_write`` call. Their dependencies are computed at compile time instead and handed to the
runtime as one table, keyed by an id per basic block (``__dp_report_bb``) or per ordered pair of
basic blocks (``__dp_report_bb_pair``). At run time, reporting such an id confirms that the block
ran, and only then do the dependencies stored under it count as real.

That makes the table the only remaining record of those dependencies, so the tests here check the
two halves against each other: every id the instrumented program can report has to exist in the
table, and every entry of the table has to be reachable from the program.
"""

from typing import List

from .utilities import InstrumentationTestCase


class TestOmittedScalarDependencies(InstrumentationTestCase):
    SOURCE = """
        int main() {
          int values[8];
          int sum = 0;                  // @sum_init
          for (int i = 0; i < 8; ++i) {
            if (i % 2 == 0) {           // @branch
              sum += i;                 // @even
            } else {
              sum -= i;                 // @odd
            }
          }
          values[0] = sum;              // @store
          return values[0];
        }
        """

    def reported_ids(self) -> List[int]:
        """Every dependency table id the instrumented program can report at run time."""
        # __dp_report_bb takes the id first, __dp_report_bb_pair takes the semaphore first
        ids = [call.required_arg_int(0) for call in self.program.calls("__dp_report_bb")]
        ids += [call.required_arg_int(1) for call in self.program.calls("__dp_report_bb_pair")]
        return ids

    def test_the_scalar_accesses_are_omitted(self) -> None:
        # the premise of the whole mechanism: sum and i are resolved statically, so only the
        # accesses to the array remain instrumented
        for marker in ("sum_init", "even", "odd"):
            self.assertDoesNotInstrumentLine("__dp_write", marker)
            self.assertDoesNotInstrumentLine("__dp_read", marker)
        self.assertInstrumentsLine("__dp_write", "store")

    def test_both_kinds_of_block_reports_are_inserted(self) -> None:
        # the branch makes the dependencies of the two arms conditional on the arm running, and the
        # loop makes some of them depend on the order two blocks ran in
        self.assertGreater(len(self.program.calls("__dp_report_bb")), 0)
        self.assertGreater(len(self.program.calls("__dp_report_bb_pair")), 0)

    def test_reported_ids_are_unique(self) -> None:
        # both callbacks draw from the same counter; a collision would merge the dependencies of
        # two unrelated blocks and report whichever ran as if both had
        ids = self.reported_ids()
        duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
        self.assertEqual([], duplicates, f"dependency table ids reported more than once: {duplicates}")

    def test_every_reported_id_has_an_entry_in_the_dependency_table(self) -> None:
        table = self.program.basic_block_dependencies()
        missing = sorted(set(self.reported_ids()) - set(table))
        self.assertEqual(
            [],
            missing,
            f"the program reports ids that __dp_add_bb_deps never registered: {missing}",
        )

    def test_the_dependency_table_has_no_unreachable_entries(self) -> None:
        table = self.program.basic_block_dependencies()
        unreachable = sorted(set(table) - set(self.reported_ids()))
        self.assertEqual(
            [],
            unreachable,
            f"the table holds dependencies under ids no block reports, so they can never be "
            f"confirmed: {unreachable}",
        )

    def test_each_basic_block_is_reported_at_most_once(self) -> None:
        blocks = [call.block for call in self.program.calls("__dp_report_bb")]
        duplicates = sorted({block for block in blocks if blocks.count(block) > 1})
        self.assertEqual([], duplicates, f"a basic block reports itself twice: {duplicates}")

    def test_the_block_pair_semaphore_is_read_at_run_time(self) -> None:
        # The first argument distinguishes "the source block ran before this one" from "it did
        # not". A constant there would make every pair look as if it had executed in order.
        for call in self.program.calls("__dp_report_bb_pair"):
            self.assertIsNone(
                call.arg_int(0),
                f"the semaphore of {call.text} is a constant instead of a loaded value",
            )

    def test_the_semaphore_is_initialised_and_set(self) -> None:
        body = [instruction.text for instruction in self.program.functions["main"]]
        self.assertTrue(
            any("alloca" in text and "__dp_bb" in text for text in body),
            "no __dp_bb semaphore was allocated although block pairs are reported",
        )
        self.assertTrue(
            any(text.startswith("store i32 0, ptr %__dp_bb") for text in body),
            "the __dp_bb semaphore is never initialised to 0",
        )
        self.assertTrue(
            any(text.startswith("store i32 1, ptr %__dp_bb") for text in body),
            "the __dp_bb semaphore is never set, so no block pair can ever be reported in order",
        )


class TestDependencyTableRegistration(InstrumentationTestCase):
    """The table has to reach the runtime from every translation unit, not just the one with main."""

    SOURCE = """
        int main() {
          int values[4];
          int sum = 0;
          for (int i = 0; i < 4; ++i) {
            sum += i;                   // @accumulate
          }
          values[0] = sum;
          return values[0];
        }
        """

    def registration_function(self) -> str:
        calls = self.program.calls("__dp_add_bb_deps")
        self.assertEqual(1, len(calls), "the dependency table is not registered exactly once")
        return calls[0].function

    def test_the_table_is_registered_exactly_once(self) -> None:
        self.registration_function()

    def test_the_registration_runs_as_a_global_constructor(self) -> None:
        # A module without main has no __dp_finalize to hang the handover on, so registering from
        # there dropped the dependencies of every translation unit but one. Running the
        # registration as a global constructor reaches all of them, independent of link order.
        self.assertIn(
            self.registration_function(),
            self.program.global_constructors(),
            "the dependency table is registered from a function that never runs without main",
        )

    def test_the_registration_function_is_named_after_its_module(self) -> None:
        # the name has to stay unique per translation unit, otherwise linking two of them collides
        self.assertTrue(
            self.registration_function().startswith("__dp_register_bb_deps."),
            f"unexpected registration function '{self.registration_function()}'",
        )

    def test_the_registered_table_is_not_empty(self) -> None:
        table = self.program.basic_block_dependencies()
        self.assertGreater(len(table), 0, "the accumulation in the loop produced no dependencies")
        for identifier, dependencies in table.items():
            self.assertNotEqual("", dependencies, f"entry {identifier} of the table carries no dependency")
