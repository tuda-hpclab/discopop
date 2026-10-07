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
- to type check everything CI checks (`files` in `mypy.ini`: `discopop_explorer`, `discopop_library`, `discopop_gui` and `mcp_server`), run `venv/bin/python -m mypy --config-file=mypy.ini` without further arguments

## Formatting
### Python
- install prerequisites via `venv/bin/pip install -r requirements-dev.txt` (pins the black version CI uses)
- CI checks the formatting of these paths only: `explorer library hotspot_detection/discopop_hotspot_analyzer hotspot_detection/discopop_hotspot_cc hotspot_detection/discopop_hotspot_cxx GUI mcp_server`
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
- the profiler's C++ unit tests (GoogleTest, in `test/unit_tests`) are only reachable via the root `CMakeLists.txt`, not via `pip install ./profiler`
- to execute them, configure and build from the repository root with `cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1`, then `cmake --build build_tests --target DiscoPoP_UT -j "$(nproc)"`, then run `build_tests/test/unit_tests/DiscoPoP_UT`
- the end-to-end profiler dependency-detection tests (`test/profiler/{RAW,WAR,WAW}`) are separate and run via `venv/bin/python -m unittest -v -k "*test.profiler.*"` from the repository root

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
