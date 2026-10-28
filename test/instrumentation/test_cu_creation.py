"""Tests for the instructions the pass assigns to CUs (``Data.xml``).

A CU is closed before a call instruction, so that a CU holds at most one call. The statement the call
belongs to must not be torn apart by that: the instructions that evaluate its operands go to the CU
of the call, and the call itself is listed in the CU that holds its instruction.
"""

import os
import re
from typing import Dict, List, Tuple

from .utilities import InstrumentationTestCase


class CuCreationCase(InstrumentationTestCase):
    def cus(self) -> Dict[str, Tuple[List[int], List[int]]]:
        """``id -> (instruction ids, call instruction ids)`` of the CUs of ``Data.xml``."""
        with open(os.path.join(self.program.directory, ".discopop", "profiler", "Data.xml")) as f:
            text = f.read()
        found: Dict[str, Tuple[List[int], List[int]]] = {}
        for node in re.finditer(r'<Node id="([^"]*)" type="0".*?</Node>', text, re.S):
            ids = re.search(r"<instructionIDs[^>]*>([^<]*)<", node.group(0))
            assert ids is not None
            found[node.group(1)] = (
                [int(i) for i in ids.group(1).split(",") if i],
                [int(i) for i in re.findall(r'callInstId="(\d+)"', node.group(0))],
            )
        return found

    def jump_lines(self) -> List[int]:
        """The lines of the instructions that ``Data.xml`` lists as jumps of a CU."""
        with open(os.path.join(self.program.directory, ".discopop", "profiler", "Data.xml")) as f:
            text = f.read()
        jumps = [
            int(i) for found in re.findall(r"<jumpInstructionIDs[^>]*>([^<]*)<", text) for i in found.split(",") if i
        ]
        return self.lines_of(jumps)

    def lines_of(self, instructions: List[int]) -> List[int]:
        return [self.program.instruction_locations[i].line for i in instructions]

    def cu_of_call_on(self, marker: str) -> Tuple[List[int], List[int]]:
        line = self.program.line_of_marker(marker)
        holders = [
            cu for cu in self.cus().values() if any(self.program.instruction_locations[c].line == line for c in cu[1])
        ]
        assert len(holders) == 1, holders
        return holders[0]


class TestCuCreation(CuCreationCase):
    SOURCE = """
        int fib(int n) {
          int x, y;
          if (n < 2) return n;
          x = fib(n - 1);                     // @first
          y = fib(n - 2);                     // @second
          return x + y;
        }
        int main() { return fib(6); }
        """

    def test_the_cu_of_a_call_holds_the_call_instruction(self) -> None:
        for marker in ("first", "second"):
            instructions, calls = self.cu_of_call_on(marker)
            for call in calls:
                self.assertIn(call, instructions)

    def test_the_operands_of_a_call_are_in_the_cu_of_the_call(self) -> None:
        for marker in ("first", "second"):
            instructions, calls = self.cu_of_call_on(marker)
            # everything up to the call belongs to the statement of the call, e.g. not the store of the one before
            up_to_call = instructions[: instructions.index(calls[0]) + 1]
            self.assertEqual({self.program.line_of_marker(marker)}, set(self.lines_of(up_to_call)))


class TestCuCreationContinuedArguments(CuCreationCase):
    SOURCE = """
        void work(int *a, int b, int c);
        void split(int *a, int n) {
          int m = n / 2;
          work(a, m,                          // @first
               n - m);
        }
        int main() { int a[4]; split(a, 4); return 0; }
        void work(int *a, int b, int c) { a[0] = b + c; }
        """

    def test_the_arguments_on_the_next_line_are_in_the_cu_of_the_call(self) -> None:
        instructions, calls = self.cu_of_call_on("first")
        first = self.program.line_of_marker("first")
        before_call = instructions[: instructions.index(calls[0])]
        # the subtraction on the continuation line is evaluated before the call, but is not the store of ``m``
        self.assertIn(first + 1, self.lines_of(before_call))
        self.assertNotIn(first - 1, self.lines_of(before_call))


class TestCuCreationJumps(CuCreationCase):
    SOURCE = """
        void work(int *a, int k);
        void loop(int *a, int n) {
          for (int k = 0; k < n; k++) {      // @header
            work(a, k);                      // @call
          }                                  // @brace
        }
        int main() { int a[4]; loop(a, 4); return 0; }
        void work(int *a, int k) { a[k] = k; }
        """

    def test_the_jump_back_at_the_closing_brace_is_listed_as_jump_and_the_call_is_not(self) -> None:
        jumps = self.jump_lines()
        self.assertIn(self.program.line_of_marker("brace"), jumps)
        self.assertNotIn(self.program.line_of_marker("call"), jumps)
