# type: ignore
"""A caught exception unwinds the stack without running the __dp_func_exit of the functions it leaves. The function
level of the runtime then stays above the level of the function that caught it, and the loops of the unwound functions
stay on the loop stack. The loop entry of a function whose level is above the one of the loop on top starts a new loop
(the entry of a recursive instance), so after a caught exception every iteration of a loop would be a loop of its own.
The landing pad of the catching function therefore closes the loops and levels of the functions it left."""

import os
import pathlib
import re

from test.end_to_end.pipeline import PipelineTestCase

SRC = pathlib.Path(__file__).parent / "src" / "code.cpp"


def loop_lines():
    """{name: line of the loop marked "// LOOP:<name>" in code.cpp}"""
    lines = dict()
    for number, text in enumerate(SRC.read_text().splitlines(), start=1):
        marker = re.search(r"// LOOP:(\w+)", text)
        if marker:
            lines[marker.group(1)] = number
    return lines


class TestLoopAccountingExceptions(PipelineTestCase):
    SRC_DIR = SRC.parent

    def loop_record(self, name):
        """(total iterations, executions, average, maximum) of the loop"""
        with open(os.path.join(self.profiler_dir, "dynamic_dependencies.txt")) as f:
            text = f.read()
        line = loop_lines()[name]
        records = {
            int(found_line): tuple(int(v) for v in values)
            for _, found_line, *values in re.findall(r"(\d+):(\d+) BGN loop (\d+) (\d+) (\d+) (\d+)", text)
        }
        return records[line]

    def test_a_loop_with_caught_exceptions_is_counted_like_one_without(self):
        # three executions of six iterations
        self.assertEqual(self.loop_record("withexc"), (18, 3, 6, 6))

    def test_the_loop_calling_the_function_with_caught_exceptions_is_counted(self):
        self.assertEqual(self.loop_record("caller"), (3, 1, 3, 3))
