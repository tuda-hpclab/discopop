# Profiler dependency tests

Each directory `<category>/<case>/` (categories `RAW`, `WAR`, `WAW` and `NONE`) holds a small program
`test.cpp`, a `Makefile` that compiles it with `discopop_cxx` and runs it, and `expected.toml` with the
dependencies the profiler has to report (`required`) and, optionally, those it must not report
(`forbidden`). `test_dependencies.py` documents the format. `test_overview.md` describes what each case
covers.

## Execution
From the repository root, with the profiler installed (`pip install ./profiler`, without `-e`):

```
venv/bin/python -m pytest -v test/profiler
```

There is one test class per category (`TestRAW`, `TestWAR`, `TestWAW`, `TestNONE`) and one test per case,
e.g. `test_dependencies.py::TestRAW::test_dependencies[raw_52]`. Before the first test of a class, the selected
cases of its category are built and profiled in parallel, each in a temporary copy that pytest keeps for the last
runs (`/tmp/pytest-of-<user>/`); the source tree is not written to. A failing test lists the missing or forbidden
dependencies, or the output of a failed `make`.

Selecting tests:
- `-k raw_52` runs a single case (only that case is built), `-k "raw_1 or war_4"` several
- `-k TestRAW` runs a category

## Adding a case
Create `<category>/<case>/` with `test.cpp`, the `Makefile` of another case and an `expected.toml`. A new category
also needs its test class in `test_dependencies.py`.
