---
layout: default
title: How to contribute
nav_order: 8
---

# How to contribute

1. TOC
{:toc}

## Reporting a bug or requesting a feature

Create an issue with the appropriate template (bug report or feature request) on [GitHub](https://github.com/tuda-hpclab/discopop/issues).

## Proposing a change

- Contributors outside the project create a fork. Project members create a branch with a descriptive name (the *Create a branch* link in the *Development* section of an issue is a good start).
- The base branch is **`new_explorer`**, the current development branch. `master` only receives releases.
- Open a pull request into `new_explorer`. Link the issue it solves, e.g. with a [closing keyword](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue#linking-a-pull-request-to-an-issue-using-a-keyword).
- Every file needs the license tag (see [License tags](#license-tags)); the CI checks it.

## Setting up a development environment

Install the prerequisites from [Installation](setup/discopop.md#prerequisites), then:

```bash
git clone https://github.com/tuda-hpclab/discopop.git
cd discopop
python3 -m venv venv
venv/bin/python -m pip install -r requirements-dev.txt
venv/bin/python -m pip install . ./profiler ./explorer ./library ./GUI ./hotspot_detection ./mcp_server
```

`make` does the same with editable installs for the Python packages. `requirements-dev.txt` pins the versions of mypy, black, ruff, pytest and the other tools that the CI uses; other versions can report different findings.

{: .important }
Install `./profiler` and `./hotspot_detection` without `-e` and all packages in one command, see [Installation](setup/discopop.md#manual-installation). After changing the profiler (`profiler/`), reinstall it (`venv/bin/python -m pip install ./profiler`): the profiler and instrumentation tests drive the *installed* `discopop_cxx`.

### Pre-commit hooks

```bash
venv/bin/python -m pip install pre-commit
venv/bin/pre-commit install
```

(`pre-commit` is not part of `requirements-dev.txt`.) This installs the hooks of `.pre-commit-config.yaml` (pre-commit and commit-msg): whitespace and end-of-file fixes, YAML and merge-conflict checks, large file check, mypy, black, ruff, the license tag check and the commit message check.

## Python

- The supported Python versions are 3.11 and newer.
- **Formatting:** black with line length 120. The CI checks these paths only: `explorer library hotspot_detection/discopop_hotspot_analyzer hotspot_detection/discopop_hotspot_cc hotspot_detection/discopop_hotspot_cxx GUI mcp_server test/leak_check benchmark/pass_overhead benchmark/injected_functions benchmark/compare test/instrumentation`.

  ```bash
  venv/bin/python -m black -l 120 --check <paths>
  venv/bin/python -m black -l 120 <paths you changed>
  ```

  Never run black on `.`: it would reformat many unrelated files.
- **Linting:** `venv/bin/python -m ruff check` checks the whole repository (pycodestyle, pyflakes, and the naming rules N804 and N806; configured in `pyproject.toml`). Black does not wrap comments, docstrings and long strings, so wrap those by hand. Review the result of `ruff check --fix`: do not remove code that only commented-out code uses, and do not rename public names to satisfy a naming rule.
- **Type checking:** `venv/bin/python -m mypy --config-file=mypy.ini` checks everything the CI checks (the `files` list of `mypy.ini`). Add type annotations to new code.

## C++ (profiler)

- The profiler (`profiler/DiscoPoP`, `profiler/rtlib`, `profiler/share`) follows the Google C++ Style Guide with 120 columns, configured in `profiler/.clang-format`, `profiler/CPPLINT.cfg` and `profiler/.clang-tidy`. `scripts/dev/check_cpp_style.sh [build dir]` runs clang-format, cpplint and clang-tidy and fails on any finding.
- Names that are looked up by string must keep their spelling: the injected callbacks `__dp_*` and the methods that LLVM's pass manager detects (`run`, `isRequired`, `name`).
- Every header has to compile on its own and no header may contain a `using namespace` directive (`scripts/dev/check_headers.py`).
- The pass supports LLVM 19&ndash;22. Code that differs between the versions belongs into `profiler/DiscoPoP/llvm_compat.hpp`, not into `#if LLVM_VERSION_MAJOR` at the call site.
- Everything is built as C++20. The code compiles without warnings with gcc and clang (the deprecation warnings of the LLVM API are the exception).
- Compile time options of the runtime (`-DDP_...`) switch code in and out; a new option belongs into the list of `scripts/dev/check_rtlib_options.sh`. See [Build options](setup/build_options.md).

## Tests

All suites run with pytest. Write new tests in pytest style.

| Command | Runs |
|---|---|
| `venv/bin/python -m pytest -m "not e2e and not profiler"` | the unit tests (explorer, library, mcp_server, hotspot_detection, project manager, leak check, benchmark compare) |
| `venv/bin/python -m pytest` | everything configured in `testpaths` of `pyproject.toml`, including the end-to-end and profiler tests |
| `venv/bin/python -m pytest -n auto --dist loadgroup test/end_to_end` | the end-to-end tests in parallel |
| `venv/bin/python -m pytest -n auto --dist loadgroup test/instrumentation test/profiler` | the tests of the LLVM pass and of the reported dependencies |
| `venv/bin/python -m pytest explorer/discopop_explorer -k <name>` | one package or test selection |

- The tests of `explorer`, `library`, `mcp_server` and `hotspot_detection` are colocated with the source as `test_*.py`. The explorer's `conftest.py` provides fixtures for building small graphs without the profiler pipeline.
- Tests with the marker `e2e` (`test/end_to_end`) and `profiler` (`test/instrumentation`, `test/profiler`) need the installed profiler and are skipped without it.
- Tests `test/wip_end_to_end` are work in progress and only run with `DP_RUN_WIP_TESTS=1`.
- **C++ unit tests:** `DiscoPoP_UT` (runtime library, `test/unit_tests`) and `DiscoPoP_Pass_UT` (pass, `test/pass_unit_tests`) are built through the root `CMakeLists.txt`, see [Build options](setup/build_options.md#developer-builds).

### Adding an end-to-end test case

Every directory below `test/end_to_end/cases` that contains an `expected.toml` is one test. The directory holds the program in `src/` (a Makefile that builds `prog` with `$CC`/`$CXX`) and the expected patterns; the schema is documented in the docstring of `test/end_to_end/test_cases.py`. Known failures get `xfail = "<reason>"`. The pipeline runs in a temporary copy of `src/`.

Tests that check more than the detected patterns live in `test/end_to_end/<topic>/test_<topic>.py` and derive from `pipeline.PipelineTestCase`. Profiler dependency cases are directories with `test.cpp`, a `Makefile` and `expected.toml` below `test/profiler/{RAW,WAR,WAW,NONE}` (see `test/profiler/README.md`).

## Continuous integration

`.github/workflows/ci.yml` runs on pushes to `master` and `new_explorer`, on every pull request and manually. A commit is tested once: a feature branch is tested through its pull request. The full matrix (Ubuntu 24.04 with LLVM 19 and 20, Debian 13 with LLVM 21 and 22) only runs when merging into `master`; other pull requests and manual runs test Debian 13 with LLVM 21. The jobs cover the static checks (license tags, black, ruff), mypy, the unit tests, the instrumentation, profiler and end-to-end tests, the C++ unit tests, sanitizers, a leak check, coverage, and benchmarks with a comparison against the previous version. A job only runs if the changes of the pull request can affect it: a change of the Python packages besides the profiler (or of the documentation) skips the profiler's C++ unit tests, runtime checks and benchmarks; a manual run always runs everything.

To run the pipeline locally (requires [act](https://github.com/nektos/act) and Docker):

```bash
scripts/dev/run_ci_locally.sh
scripts/dev/run_ci_locally.sh --matrix id:ubuntu-24-04-llvm-20
```

## Commit messages

Commit messages have the form `type(scope): subject`, for example `fix(profiler): ...` or `docs(explorer): ...`. Allowed types: `feat`, `fix`, `test`, `chore`, `update`, `refactor`, `doc`, `docs`, `perf`, `wip`, `ci`, `build`, `style`. The scope and an optional `[info]` are optional. Merge and revert commits are accepted. `scripts/dev/check-commit-msg.py` checks the format as a commit-msg hook.

## License tags

Every source file carries the DiscoPoP license header in its first 20 lines (`scripts/dev/check-license.sh`, run by pre-commit and by the CI). Copy the header of a neighboring file. Binary files, `__init__.py`, `docs/`, `test/` and a few other locations are exempt (see the script).

## Releases

Each package has its own `VERSION` file (`profiler/`, `explorer/`, `library/`, `GUI/`, `hotspot_detection/`, `mcp_server/`, and the root `VERSION` for `discopop`), which its `pyproject.toml` reads. Update it before tagging. A tag publishes to PyPI:

| Tag | Publishes |
|---|---|
| `profiler_v<version>` | `discopop-profiler` |
| `explorer_v<version>` | `discopop-explorer` |
| `library_v<version>` | `discopop-library` |
| `gui_v<version>` | `discopop-gui` |
| `hotspot_detection_v<version>` | `discopop-hotspot-detection` |
| `mcp_server_v<version>` | `discopop-mcp-server` |
| `v<version>` (e.g. `v5.0.3`), tagged on `master` | the root package `discopop` and a draft GitHub release |
| `v<version>a<n>`, `v<version>b<n>`, `v<version>dev<n>` | the root package `discopop` as pre-release |

Use `1.2.3a4` as the version of an alpha release and `b` instead of `a` for a beta release. Version numbers: bug fixes and documentation only raise the last digit; compatible new features raise the middle digit and reset the last; changes of interfaces or data formats that are not compatible raise the first digit and reset the others.

## Developer utilities

The scripts in `scripts/dev` support development; run them from the root of the repository.

| Script | Purpose |
|---|---|
| `run_ci_locally.sh` | runs the CI workflow locally with act |
| `check-commit-msg.py` | validates a commit message (commit-msg hook) |
| `check-license.sh` | checks that files carry the license tag (pre-commit) |
| `check_cpp_style.sh [build dir]` | clang-format (dry run), cpplint and clang-tidy on the profiler |
| `clang-format.sh` | runs clang-format in place on all C/C++ files (run it from `scripts/dev`) |
| `check_headers.py [build dir]` | compiles every profiler header on its own |
| `check_rtlib_options.sh [dir] [name]` | builds the runtime library once per set of compile time options (compile check only) |
| `run_profiler_sanitizers.sh <sanitizers>` | builds and runs `DiscoPoP_UT` with `address,undefined` or `thread` |
| `check_profiler_leaks.sh` | compiles the programs of `test/leak_check/programs` with the pass, links an ASan/LSan runtime and evaluates leaks of the runtime |
| `run_rtlib_coverage.sh` | builds `DiscoPoP_UT` with clang coverage and reports the coverage of `profiler/rtlib` (`--min-line-coverage`, `--markdown-out`, `--html-out`) |

The benchmarks have their own drivers: `benchmark/pass_overhead/run_pass_benchmark.py` (compile time, run time and size with and without the pass), `benchmark/injected_functions/run_callback_benchmark.py` (cost of each injected callback) and `benchmark/compare` (comparison of two versions, used by the CI); see the READMEs in these directories.

## Output folder structure

All tools make use of the following structure, where nothing is stored outside of `.discopop` in order to keep the build directory of the user clean:

```text
project root/
  .discopop/
    FileMapping.txt
    <tool>/
      output files of the tool
      private/
        intermediate files of the tool
```

Files that several tools read, such as `FileMapping.txt`, live directly in `.discopop`. Output for other tools is stored in the folder of the creating tool; intermediate files go into `private` and are not used by other tools. Prefer structured formats such as JSON over plain text files for data that other tools read. Analysis tools are meant to be executed from within `.discopop`. See [Data](data/data.md) for the real contents.
