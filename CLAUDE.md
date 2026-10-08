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

# Development Guidelines
This document contains critical information about working with this codebase. Follow these guidelines precisely.

# Code Structure
- The code for the static analysis step of the profiler is located in the folder `DiscoPoP`
- The code for the runtime library of the profiler is located in the folders `rtlib` and `share`
- The code for the pattern analysis is located in the folder `discopop_explorer`
- Utilities for the pattern analysis as well as further tools are located in the folder `discopop_library`
- The projects wiki page is defined in the folder`docs`
- The code for the graphical user interface is located in the folder `GUI`

# Code Style
- verify the type correctness of python code
- verify correctness of code using the unittests
- verify correctness of modifications to the profiler using the unittests

# Tools
## Setup
### Setup venv
- in case the `venv` is not set up, execute `python3 -m venv venv` to create a new virtual environment
- always use the `venv` located in the project root directory; if it is not already activated, activate it via `source venv/bin/activate` before running any Python commands

## Type checking
### Python
- install prerequisites via `venv/bin/pip install -r requirements-dev.txt` (pins the mypy version CI uses; a different version can report different errors)
- to execute type checking of python files use the following command as the basis: `venv/bin/python -m mypy --config-file=mypy.ini -p`
- to type check everything CI checks (`files` in `mypy.ini`: `discopop_explorer`, `discopop_library`, `discopop_gui`, `mcp_server`, `test/leak_check`, `test/instrumentation` and the benchmark drivers in `benchmark/pass_overhead` and `benchmark/injected_functions`), run `venv/bin/python -m mypy --config-file=mypy.ini` without further arguments

## Formatting
### Python
- install prerequisites via `venv/bin/pip install -r requirements-dev.txt` (pins the black version CI uses)
- CI checks the formatting of these paths only: `explorer library hotspot_detection/discopop_hotspot_analyzer hotspot_detection/discopop_hotspot_cc hotspot_detection/discopop_hotspot_cxx GUI mcp_server test/leak_check benchmark/pass_overhead benchmark/injected_functions test/instrumentation`
- to execute the formatting check, use `venv/bin/python -m black -l 120 --check <paths>` with the paths above
- to execute automatic formatting, use `venv/bin/python -m black -l 120 <paths>`, restricted to the paths you changed; never run black on `.`, as it would reformat many unrelated, unchecked files

## Testing
### Install python packages
- to install python packages, execute `venv/bin/pip install . ./profiler ./library` from the root directory of the project
- **Important:** The profiler module must be installed without the `-e` (editable) flag. Use `pip install ./profiler`, not `pip install -e ./profiler`. Editable mode breaks the relative paths required by `CXX_wrapper.sh` to locate compiled artifacts like `LLVMDiscoPoP.so`.
### Python end-to-end tests
- to execute the python end-to-end tests, use 'venv/bin/python -m unittest -v -k "*.end_to_end.*"'

### MCP server end-to-end tests
- `test/end_to_end/mcp_server` drives the MCP server as a client does: it starts `python -m mcp_server.server` from the repository root (so the server code of the checkout is tested) as a stdio subprocess and calls it with the MCP SDK client
- run only them via `venv/bin/python -m unittest -v -k "*.end_to_end.mcp_server.*"` or `venv/bin/python -m pytest test/end_to_end/mcp_server`; they are also part of the end-to-end command above, but not of the bare `pytest` run
- `test_stdio_server.py` (protocol, tool listing, setup tools, error paths) and `test_daemon_proxy.py` (stdio proxy forwarding to a `--daemon`) need no profiler; `test_workflows.py` (pipeline, auto-tuning, patches, failure paths, cancellation) runs the real pipeline on `src/code.cpp` and is skipped when `discopop_cc`/`discopop_cxx` are not installed
- every server gets a free `--daemon-port`, so a developer's daemon on the default port never takes over the calls; known server bugs are marked `unittest.expectedFailure` with a comment naming the cause

### Python unit tests (all)
- to run all Python unit tests at once, from the repository root: `venv/bin/python -m pytest`
- this collects `explorer/discopop_explorer`, `library/discopop_library`, `mcp_server`, `hotspot_detection` and `test/project_manager`, as configured in `[tool.pytest.ini_options]` of the root `pyproject.toml`; the CI pipeline runs exactly this
- the configuration sets `--import-mode=importlib` and puts the source trees on `pythonpath`: with the default import mode, collecting several package roots in one run aborts with an import file mismatch against the copies installed in site-packages

### Python unit tests (discopop_library)
- `discopop_library` (`library/discopop_library`) has pytest-based unit tests colocated with the source as `test_*.py` files
- to run them, from the repository root: `venv/bin/python -m pytest library/discopop_library`

### Python unit tests (mcp_server, hotspot_detection)
- `mcp_server` and `hotspot_detection` have pytest-based unit tests colocated with the source as `test_*.py` files
- to run them, from the repository root: `venv/bin/python -m pytest mcp_server` and `venv/bin/python -m pytest hotspot_detection`

### Further unittest suites
- `test/instrumentation` asserts on the callbacks the LLVM pass inserts; it drives `discopop_cxx`, so the venv has to be *activated* (`. venv/bin/activate`), not just addressed via `venv/bin/python`: `python3 -m unittest -v -k "*test.instrumentation.*"`
- the CI matrix job `build_install_and_test` runs the instrumentation tests on every matrix entry
- `test/wip_end_to_end` is work in progress and opt-in: it only runs with `DP_RUN_WIP_TESTS=1`; CI does not run it

### Python unit tests (discopop_explorer)
- the `discopop_explorer` package (`explorer/discopop_explorer`) has pytest-based unit tests colocated with the source as `test_*.py` files (e.g. `explorer/discopop_explorer/utilities/ASTUtils/test_ASTQueries.py`, `explorer/discopop_explorer/test_utils.py`, `explorer/discopop_explorer/pattern_detectors/test_do_all_detector.py`)
- install prerequisites via `venv/bin/pip install -r requirements-dev.txt pytest-cov`
- to run all of them, from the repository root: `venv/bin/python -m pytest explorer/discopop_explorer`
- to run a single file: `venv/bin/python -m pytest explorer/discopop_explorer/test_utils.py -v`
- to run tests matching a name substring: `venv/bin/python -m pytest explorer/discopop_explorer -k "detect_do_all"`
- `explorer/discopop_explorer/conftest.py` provides shared fixtures for building small in-memory graphs without running the full profiler pipeline; extend these rather than re-deriving graph setup per test file:
  - `make_node`/`build_pet_graph`: build a `PEGraphX` directly from hand-picked `CUNode`/`FunctionNode`/`LoopNode` instances and edges, bypassing `PEGraphX.from_parsed_input`'s XML/dependency parsing
  - `build_task_graph`/`make_tg_node`: build a `TaskGraph` (bypassing its profiler-file-dependent `__init__`) plus `TGNode`s, for testing `TaskGraph`/`Context`-based code (e.g. `new_do_all_detector.py`)
  - `isolated_pattern_id_cwd`: isolates the `next_free_pattern_id.txt` file that `PatternInfo` subclasses (e.g. `DoAllInfo`, `ReductionInfo`) allocate ids from into a temp directory, so tests don't touch/lock files in the repo root
- **Note:** these unit tests do not cover code paths that are only exercised by the end-to-end tests (`test/end_to_end`), since those invoke `discopop_explorer` as a subprocess rather than in-process

### Coverage report (discopop_explorer)
- to generate a coverage report, run from the repository root:
  `venv/bin/python -m pytest explorer/discopop_explorer --cov=discopop_explorer --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-config=<(echo -e "[run]\nomit =\n    */test_*.py\n")`
- this excludes the test files themselves from the coverage count and produces:
  - a terminal summary with missing line ranges per file
  - an HTML report at `htmlcov/index.html`
  - a Cobertura-style `coverage.xml`
- the coverage numbers reflect unit-test coverage only (see note above)

### C++
#### Profiler
- there are two GoogleTest binaries, both only reachable via the root `CMakeLists.txt`, not via `pip install ./profiler`: `DiscoPoP_UT` (runtime library, `test/unit_tests`) and `DiscoPoP_Pass_UT` (LLVM pass, `test/pass_unit_tests`)
- to execute them, configure and build from the repository root with `cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1`, then `cmake --build build_tests --target DiscoPoP_UT DiscoPoP_Pass_UT -j "$(nproc)"`, then run `build_tests/test/unit_tests/DiscoPoP_UT` and `build_tests/test/pass_unit_tests/DiscoPoP_Pass_UT`; the CI matrix job `build_install_and_test` runs both on every matrix entry
- the end-to-end profiler dependency-detection tests (`test/profiler/{RAW,WAR,WAW}`) are separate and run via `venv/bin/python -m unittest -v -k "*test.profiler.*"` from the repository root

#### Sanitizers (profiler)
- the CMake option `DP_SANITIZERS` (value for `-fsanitize=`, e.g. `address,undefined` or `thread`) instruments the runtime library `DiscoPoP_RT` and everything linking it, i.e. `DiscoPoP_UT`; the LLVM pass plugin is not sanitized (it runs inside an uninstrumented clang)
- to build and run `DiscoPoP_UT` with ASan+UBSan(+LSan) resp. TSan, from the repository root: `scripts/dev/run_profiler_sanitizers.sh address,undefined` resp. `scripts/dev/run_profiler_sanitizers.sh thread` (build dirs `build_asan` / `build_tsan`, gitignored; ~30 s each); the CI job `sanitizers` runs exactly this
- the script sets the `*SAN_OPTIONS` (halt on error, suppression files); any finding fails the run
- TSan needs ASLR disabled on kernels with high mmap entropy (`FATAL: ThreadSanitizer: unexpected memory mapping`); the script runs it via `setarch "$(uname -m)" -R`, which in Docker needs `--security-opt seccomp=unconfined`
- accepted leaks / races go into `test/unit_tests/sanitizers/{lsan,tsan}.supp`, one comment per entry explaining why; prefer fixing the code or the test

#### Coverage (runtime library)
- `scripts/dev/run_rtlib_coverage.sh` builds `DiscoPoP_UT` with clang source based coverage (build dir `build_coverage`), runs it and reports line / function / branch coverage of `profiler/rtlib` (llvm-cov and llvm-profdata of clang's major version are required, e.g. the `llvm-19` package)
- `--min-line-coverage <n>` fails below n percent lines, `--markdown-out <file>` / `--html-out <dir>` write reports; test failures do not stop the report
- the CI job `rtlib_coverage` runs it with a floor of 90% lines; it is not part of `checks_successful` yet

### Execute example
You can execute a full example by following the steps below. The example should not raise any errors. Warnings may arise during different parts of the process and can be tolerated.
- setup venv
- install python packages
- clean example via `rm -rf example/a.out example/.discopop`
- execute static analysis and instrumentation via `cd example && ../venv/bin/discopop_cxx example.cpp -o a.out`
- execute profiling via `cd example && ./a.out`
- execute pattern analysis via `cd example/.discopop && ../../venv/bin/discopop_explorer`
- check for existing parallelization suggestions by checking for created patch files in example/.discopop/patch_generator

### Measured execution time
- by default, a configuration's runtime is the wall clock time of its `execute.sh`; a program printing its own timing can have that value measured instead (see `docs/tools/Project_manager.md`, section "Measured runtime")
- the setting is stored per configuration in `.discopop/project/configs/<config>/execution_time.json` and edited in the GUI under Editor -> execute.sh; `--execution-time-regex` (on both `discopop_project_manager` and `discopop_auto_tuner`) overrides it for one run
- the extraction lives in `library/discopop_library/ProjectManager/configurations/execution_time.py`; only `execute.sh` call sites pass a pattern, so `compile.sh` / `validate.sh` keep their wall clock times
- `execution_results.json` entries carry `wall_clock_time` and `time_source` next to `time`; `time` always holds the measurement of interest, so reports, plots, the auto-tuner and the benchmark harnesses need no change

### Excecute CI Pipeline locally
To execute the CI pipeline locally, use the following command from the root folder: `scripts/dev/run_ci_locally.sh`.
- a single matrix entry can be selected with act's `--matrix` filter on its `id`, e.g. `scripts/dev/run_ci_locally.sh --matrix id:ubuntu-24-04-llvm-20`

### Supported versions and CI matrix
- LLVM/clang 19-22 (accepted by `profiler/CMakeLists.txt` and `profiler/hatch_build.py`), Python >= 3.10 (`requires-python` of every package)
- the matrix created by the `create_matrix` job in `.github/workflows/ci.yml` covers each of these once instead of the full cross product: ubuntu 24.04 / LLVM 19 / Python 3.10 (deadsnakes PPA), ubuntu 24.04 / LLVM 20 / Python 3.12, debian 13 / LLVM 21 (apt.llvm.org) / Python 3.13, debian 13 / LLVM 22 / Python 3.13
- when changing the supported range, update the matrix, `requires-python`, the black `target-version` in the root `pyproject.toml` and `docs/setup/discopop.md` together

## Benchmarks
### Runtime library micro-benchmarks
- Google Benchmark micro-benchmarks for the runtime library data structures live in `benchmark/`
- they are built through the root `CMakeLists.txt`: `cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1`, then `cmake --build build_tests --target DiscoPoP_BM -j "$(nproc)"`, then run `build_tests/benchmark/DiscoPoP_BM`

### Runtime library benchmark variants
- `profiler/rtlib/CMakeLists.txt` builds the runtime 18 times when `DP_BUILD_UNITTESTS=1`: the shipped `DiscoPoP_RT`, plus `DiscoPoP_RT_EmptyCallbacks` (no callback body at all) and one `DiscoPoP_RT_Only_<CALLBACK>` per callback (only that body)
- the switch is `callback_body_enabled(CallbackId)` in `profiler/rtlib/callback_scope.hpp`, driven by `DP_BENCHMARK_EMPTY_CALLBACKS` and `DP_BENCHMARK_ONLY_CALLBACK=<enumerator>`; it is a compile-time constant, so a body that is off is gone from the generated code rather than skipped over
- build them all with `cmake --build build_tests --target DiscoPoP_RT_BenchmarkVariants`; they are not installed and must never be linked into a profiled program
- the shared half of the runtime is compiled once into `DiscoPoP_RT_BenchmarkShared` and reused; `DiscoPoP_CALLBACK_SOURCES` in that CMakeLists lists the files whose code depends on the switch (everything including `callback_scope.hpp`) — a new callback file belongs there, not in `DiscoPoP_SHARED_SOURCES`

### Injected callback benchmark
- `benchmark/injected_functions` measures what each callback the LLVM pass injects costs, split into the call the pass adds and the body the runtime executes inside it
- to run it: `venv/bin/python benchmark/injected_functions/run_callback_benchmark.py`; it configures, builds `DiscoPoP_BM_Callbacks` and `DiscoPoP_BM_Callbacks_Empty`, runs both and subtracts them per callback
- `--no-build`, `--filter <regex>`, `--repetitions <n>` and `--min-time <s>` shorten the run while iterating; `--json-out` / `--markdown-out` write machine readable results
- it fails when a binary does not build or run, when the runtime does not come up, or when the two runs no longer agree on the set of benchmarks; the times are reported, never enforced
- the binaries need `DOT_DISCOPOP` to point at a directory containing a `profiler/` subdirectory when run by hand -- the runtime opens its result files before `main`; the driver supplies one
- see `benchmark/injected_functions/README.md` for what is and is not covered, and for how to add a callback
- the CI job `callback_benchmark` runs it together with the `--callback-breakdown` of the pass overhead benchmark, only on pushes to master/new_explorer and on manual runs (`workflow_dispatch`); it is not part of `checks_successful`

### Pass overhead benchmark
- `benchmark/pass_overhead` compiles the test programs in `benchmark/pass_overhead/programs` twice -- once plain, once with the LLVM pass from `profiler/DiscoPoP` plus the linked runtime library -- and reports compile time, run time and binary size side by side
- it needs the profiler installed without `-e`: `venv/bin/pip install -r requirements-dev.txt ./profiler`
- to run it: `venv/bin/python benchmark/pass_overhead/run_pass_benchmark.py`
- `--filter <substring>` and `--repetitions <n>` shorten the run while iterating; `--json-out` / `--markdown-out` write machine readable results
- it fails when a program does not build or run, or when the instrumented binary stops reproducing the baseline output; timings only fail the run if `--max-compile-factor` / `--max-run-factor` are given
- the CI job `pass_overhead_benchmark` runs it (without timing limits) and is part of `checks_successful`: a program that no longer builds, runs or reproduces its output fails the pipeline
- adding a program means dropping a `.cpp` file with a `// BENCHMARK: <description>` comment into `benchmark/pass_overhead/programs`; see `benchmark/pass_overhead/README.md`
- `--callback-breakdown` additionally builds every program against each runtime variant above, which attributes the whole-program overhead to the individual callbacks; it needs the variants built and links *every* instrumented configuration from `--variants-dir` so they all come from one build
- the breakdown rows do not add up to the total: a body running on its own never saturates the access queue, so the main thread never waits for the workers the way it does in a real profiling run. Read it as a ranking, not as a decomposition
