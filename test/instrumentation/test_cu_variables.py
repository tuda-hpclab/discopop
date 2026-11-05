"""Tests for the variables the pass lists per CU (``Data.xml``): which are local and which are global.

``PopulateGlobalVariablesSet`` asks ``DetermineVariableNameStatic`` whether an access is to a global variable. That
function only ever sets its flag, so the flag has to be cleared before every query. It was set once per region: after
the first access to a global variable, every later variable of the region was a "program global", locals included.
"""

import os
import re
from typing import Dict, List, Tuple

from .utilities import InstrumentationTestCase


class TestCuVariables(InstrumentationTestCase):
    SOURCE = """
        int counter;
        int work(int n) {
          int before = n * 2;
          counter += n;                       // the first access to a global variable of the function
          int after = before + 1;
          return after;
        }
        int main() { return work(3); }
        """

    def variables(self) -> List[Tuple[str, str, str]]:
        """``(kind, name, defLine)`` of every variable of every CU of ``Data.xml``."""
        with open(os.path.join(self.program.directory, ".discopop", "profiler", "Data.xml")) as f:
            text = f.read()
        return [
            (kind, name, def_line)
            for kind, def_line, name in re.findall(r'<(local|global) type="[^"]*" defLine="([^"]*)"[^>]*>([^<]*)<', text)
        ]

    def kinds(self) -> Dict[str, set]:
        found: Dict[str, set] = {}
        for kind, name, _ in self.variables():
            found.setdefault(name, set()).add(kind)
        return found

    def test_the_global_variable_is_global(self) -> None:
        self.assertIn("global", self.kinds()["counter"])

    def test_the_locals_after_a_global_access_stay_local(self) -> None:
        kinds = self.kinds()
        for name in ("before", "after"):
            self.assertEqual({"local"}, kinds[name], name)

    def test_only_global_variables_have_the_def_line_of_a_global(self) -> None:
        marked = {name for _, name, def_line in self.variables() if def_line == "GlobalVar"}
        self.assertLessEqual(marked, {"counter"})
