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

There is one test per category and one subtest per case. Passing subtests are not listed
(`verbosity_subtests = 0` in the root `pyproject.toml`), failing ones are, with the missing or forbidden
dependencies. The cases of a category are built and profiled in parallel, each in a temporary copy that
pytest keeps for the last runs (`/tmp/pytest-of-<user>/`); the source tree is not written to.

Options:
- `DP_TEST_PROFILER_CASES=<pattern>[,<pattern>...]` runs only the cases whose directory name matches one of
  the glob patterns, e.g. `DP_TEST_PROFILER_CASES=raw_52,war_4*`
- `-k RAW` runs a single category
- `-o verbosity_subtests=1` lists the passing subtests as well

## Adding a case
Create `<category>/<case>/` with `test.cpp`, the `Makefile` of another case and an `expected.toml`.
