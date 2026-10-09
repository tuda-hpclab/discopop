<!--
 /*
 * This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */
 -->

# Important Notes
The execution of the unit tests requires the `build` folder to be located within the original `discopop` directory!

# Executing End-to-end Tests
The end-to-end tests run with pytest: `python -m pytest -v test/end_to_end` (the bare `python -m pytest` from the
repository root includes them). They are skipped when the profiler (`discopop_cc`, `discopop_cxx`) is not installed.

The detection tests are data-driven: each directory below `test/end_to_end/cases` holds a program in `src/` and
the expected suggestions in `expected.toml`; `test/end_to_end/test_cases.py` runs one test per directory and
documents the format. To add a test, add such a directory.

# Instrumentation Tests
The tests below `test/instrumentation` compile small programs with the DiscoPoP compiler wrapper
and check which callbacks the LLVM pass inserted into the resulting LLVM IR. They complement
`test/profiler`, which runs an instrumented program and compares the dependencies it reports
against a gold standard. Run them with
`python -m unittest -v -k "*test.instrumentation.*"`; see `test/instrumentation/README.md`.

# Work-in-progress Tests
The tests below `test/wip_end_to_end` are known to fail and are excluded from collection
(see `test/wip_end_to_end/__init__.py`), so neither `python -m unittest -v` nor `pytest`
picks them up. To work on one of them, run it explicitly, e.g.
`python -m unittest -v test.wip_end_to_end.do_all.backwards_array_access.test`.
Once it passes, move it over to `test/end_to_end`.
