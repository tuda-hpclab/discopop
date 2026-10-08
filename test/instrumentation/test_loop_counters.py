"""Tests for the loop iteration counters the pass inserts.

Next to the loop entry and exit callbacks, the pass puts a ``__dp_loop_incr`` into the body of
every loop and a single ``__dp_loop_output`` into ``main``, which writes the collected counts out.
The counts tell the later phases how often a loop actually ran, which is what makes a suggestion
worth acting on or not, and they are keyed by the same loop ids that ``loop_meta.txt`` maps to
source lines -- so the ids in the IR and in that file have to agree.
"""

from typing import List, Tuple

from .utilities import InstrumentationTestCase


class TestLoopCounters(InstrumentationTestCase):
    SOURCE = """
        int main() {
          int matrix[4][4];
          for (int i = 0; i < 4; ++i) {       // @outer
            for (int j = 0; j < 4; ++j) {     // @inner
              matrix[i][j] = i + j;
            }
          }
          int total = 0;
          for (int k = 0; k < 4; ++k) {       // @third
            total += matrix[k][k];
          }
          return total;
        }
        """

    def loop_ids(self, callee: str) -> List[int]:
        """The loop ids reported by ``callee``.

        The entry and exit callbacks take the packed source location first and the loop id second,
        the counter takes the loop id first and an instruction id second.
        """
        position = 0 if callee == "__dp_loop_incr" else 1
        return sorted(call.required_arg_int(position) for call in self.program.calls(callee))

    def entered_loops(self) -> List[Tuple[int, int]]:
        """``(loop id, line)`` for every instrumented loop, taken from the entry callbacks."""
        pairs = []
        for call in self.program.calls("__dp_loop_entry"):
            line = self.program.source_line(call)
            assert line is not None
            pairs.append((call.required_arg_int(1), line))
        return sorted(pairs)

    def test_every_loop_body_is_counted(self) -> None:
        self.assertCallbackCount("__dp_loop_incr", 3)
        self.assertEqual(
            self.loop_ids("__dp_loop_entry"),
            self.loop_ids("__dp_loop_incr"),
            "the counted loops are not the same ones that report entry",
        )

    def test_the_counter_sits_in_the_body_not_in_the_header(self) -> None:
        # The header runs once more than the body -- it is what evaluates the exit condition. A
        # counter placed there would report one iteration too many for every loop.
        headers = {call.required_arg_int(1): call.block for call in self.program.calls("__dp_loop_entry")}
        for call in self.program.calls("__dp_loop_incr"):
            loop_id = call.required_arg_int(0)
            self.assertNotEqual(
                headers[loop_id],
                call.block,
                f"the counter of loop {loop_id} sits in its header block '{call.block}'",
            )

    def test_the_loop_metadata_file_matches_the_instrumented_loops(self) -> None:
        # loop_meta.txt is how the later phases resolve a loop id back to a source line; if it
        # drifts from the IR, counts are attributed to the wrong loop
        metadata = sorted((loop_id, line) for _, loop_id, line in self.program.loop_metadata())
        self.assertEqual(self.entered_loops(), metadata)

    def test_each_loop_is_recorded_under_its_own_line(self) -> None:
        lines = {marker: self.program.line_of_marker(marker) for marker in ("outer", "inner", "third")}
        recorded = {line for _, line in self.entered_loops()}
        self.assertEqual(set(lines.values()), recorded, f"expected the loops at {lines}, recorded {recorded}")

    def test_the_counters_are_dumped_once_from_main(self) -> None:
        self.assertCallbackCount("__dp_loop_output", 1)
        self.assertEqual("main", self.program.calls("__dp_loop_output")[0].function)

    def test_the_counters_are_dumped_at_the_end_of_main(self) -> None:
        # The runtime is torn down from a .fini_array entry, so there is no __dp_finalize left in
        # the IR to place the dump in front of. It goes immediately before main's return instead,
        # which is still well before the loop manager is destroyed.
        dump = self.program.calls("__dp_loop_output")[0]
        following = self.program.next_instruction(dump)
        self.assertIsNotNone(following, "__dp_loop_output is the last instruction of main")
        assert following is not None
        self.assertTrue(
            following.text.startswith("ret"),
            f"__dp_loop_output is followed by '{following.text}' instead of main's return",
        )
