---
layout: default
title: Project manager
parent: Tools
nav_order: 2
---

# Project manager
## Executable
`discopop_project_manager` (`discopop` is an alias for it). `discopop_gui` opens the same tool with its [graphical interface](GUI.md), equivalent to `--gui`.

Up to DiscoPoP 5.0, the bare `discopop` command opened the graphical interface and silently ignored every other argument it was given. It is now the command line tool, and the window has moved to `discopop_gui`. Without any argument, the tool prints its help and does nothing.

## Purpose
Initialize a project for use with the DiscoPoP framework and manage its *execution configurations*: named descriptions of how the project is built, how it is run, and how the correctness of a run is checked. The project manager builds and runs the project in the modes described below, records the measurements and creates reports. Configurations are also used by the [empirical autotuner](Autotuner.md), [patch repair](Patch_repair.md), the [GUI](GUI.md) and the [MCP server](MCP_server.md), which compile, execute and validate candidate parallelizations through them.

For a step-by-step example, see [Project manager on the command line](../examples/project_manager_cli.md).

## Required input
- A project that can be copied to a sibling directory and built there
- A `.discopop/project/configs` directory with a `compile.sh`, a `seq_settings.json` and at least one configuration with an `execute.sh` (see below)

## Initialization
```bash
cd <your project>
discopop_project_manager --init
```

`--init` creates the `.discopop` directory and exactly two files:

- `.discopop/project/configs/compile.sh`: a placeholder that prints a hint and exits with `1`, so a run fails until you edit it. It is already executable.
- `.discopop/project/configs/seq_settings.json`: `{"CC": "clang", "CXX": "clang++", "CFLAGS": "", "CXXFLAGS": ""}`

It creates no configuration. You create one by adding a directory with an `execute.sh` below `configs`:

```bash
cat > .discopop/project/configs/compile.sh <<'EOF'
#!/bin/bash
$CXX $CXXFLAGS example.cpp -o prog
EOF
mkdir .discopop/project/configs/tiny
printf '#!/bin/bash\n./prog\n' > .discopop/project/configs/tiny/execute.sh
chmod +x .discopop/project/configs/compile.sh .discopop/project/configs/tiny/execute.sh
```

Alternatively, use the [GUI](GUI.md) (its configuration assistant creates all files) or the [MCP server](MCP_server.md). `tiny` is the configuration name `-x` uses by default.

## Configuration directory
All configurations live below `.discopop/project/configs/`:

```text
.discopop/project/configs/
├── compile.sh                  # shared build
├── compile_validate.sh         # optional: shared build used for validation only
├── seq_settings.json           # compilers and flags of the sequential build
├── dp_settings.json            # derived from seq_settings.json
├── hd_settings.json            # derived from seq_settings.json
├── par_settings.json           # derived from seq_settings.json
└── <configuration_name>/
    ├── execute.sh              # required: the timed run
    ├── validate.sh             # optional: untimed correctness check
    ├── execution_time.json     # optional: read the runtime from the program's output
    ├── compile.sh              # optional: build override for this configuration
    └── compile_validate.sh     # optional: validation build override for this configuration
```

`dp_settings.json`, `hd_settings.json` and `par_settings.json` are derived from `seq_settings.json` and **overwritten on every command line run** (except `--init`, `-r`, `-rx` and `--gui`). Edit `seq_settings.json` instead:

| Settings file | Derived from `seq_settings.json` by |
|---|---|
| `dp_settings.json` | `CC=discopop_cc`, `CXX=discopop_cxx` |
| `hd_settings.json` | `CC=discopop_hotspot_cc`, `CXX=discopop_hotspot_cxx`, `-fopenmp` appended to `CFLAGS` and `CXXFLAGS` |
| `par_settings.json` | `-fopenmp` appended to `CFLAGS` and `CXXFLAGS` |

Every script is executed with the project root as its working directory, so relative paths may be used as if already in the project root. Each script must exit `0` on success. The following environment variables are available:

| Variable | Meaning |
|---|---|
| `$CC`, `$CXX` | compiler executables, taken from the settings file of the active mode |
| `$CFLAGS`, `$CXXFLAGS` | compiler flags, likewise from the settings file |
| `$DP_PROJECT_ROOT_DIR` | absolute path of the (possibly copied) project root; use it to refer to the project, e.g. `cmake -S "$DP_PROJECT_ROOT_DIR" -B build` |
| `$DP_PROJECT_ORIGINAL_DIR` | absolute path of the original project, never a copy (equal to `$DP_PROJECT_ROOT_DIR` for runs in place); use it to reach what is not copied, e.g. `cmake -S "$DP_PROJECT_ORIGINAL_DIR" -B build` or large input data. Code compiled from there lies outside of `$DP_PROJECT_ROOT_DIR`: it is not instrumented (unless listed as an included directory) and contains no applied suggestions |
| `$DOT_DISCOPOP` | absolute path of the `.discopop` directory inside that root |
| `$DP_PROJECT_EXCLUDE_DIRS` | the [excluded directories](#project-directories) as absolute paths inside that root, separated by `:`, after the entries a settings file may set; only set if there are any |
| `$DP_PROJECT_INCLUDE_DIRS` | the [included directories](#project-directories) outside the project, absolute, separated by `:`, after the entries a settings file may set; only set if there are any |
| `$OMP_NUM_THREADS` | thread count of the current run |

Build scripts must use `$CC` / `$CXX` and `$CFLAGS` / `$CXXFLAGS` rather than hard-coded compiler names. The same script is reused for sequential builds, DiscoPoP instrumentation, hotspot detection and parallel builds; only the settings file changes between them. A bare `clang` / `clang++` in the settings is replaced by the highest installed `clang-<N>` / `clang++-<N>` if no unversioned compiler is on the `PATH`.

### Project directories
The profiler and the hotspot detection instrument the functions defined in the project, i.e. below the project root (`DP_PROJECT_ROOT_DIR`). Two lists change what counts as project code:

- **Excluded directories** below the project root are no project code, e.g. the dependencies a CMake build fetches into `build/_deps`, or third-party libraries the project brings along. Leaving them out shortens the instrumented build and, considerably, the profiling run: on Kripke (RAJA, CHAI and Umpire below `tpl/`), instrumenting only `src/` cut the profiling run from 14 s to under one second, with a quarter of the dependencies to analyze. A directory excludes everything below it.
- **Included directories** outside the project root are project code as well, e.g. sources shared between projects. They are not copied for the runs of a configuration: every copy compiles the same files. Parallelization suggestions for them are therefore never applied automatically, see [Suggestions that patch files outside of the project](#suggestions-that-patch-files-outside-of-the-project).

Both are stored in `.discopop/project/` (kept by `--reset`): `excluded_directories.json` with paths relative to the project root, `included_directories.json` with absolute paths:

```json
{"excluded_directories": ["build/_deps", "third_party"]}
```

Edit them in the GUI (*Project Setup* stage: a folder tree with check boxes for the excluded directories, a list for the included ones), with the MCP server (`set_compile_script`), or in the files; `--project-exclude-dirs` / `--project-include-dirs` replace a list for one invocation. The project manager passes them to every build as `DP_PROJECT_EXCLUDE_DIRS` (absolute paths in the copy of the project the run works in) and `DP_PROJECT_INCLUDE_DIRS`, see [Environment variables](../setup/environment_variables.md). Paths are compared as given and with symbolic links resolved.

Every instrumented build records the lists it was built with in `.discopop/instrumented_project_directories.json`; if they change afterwards, the GUI marks the profiling and hotspot data stale.

`DP_PROJECT_ROOT_DIR`, `DP_PROJECT_ORIGINAL_DIR` and `DOT_DISCOPOP` are set by the project manager for every run and cannot be set in a settings file: a value found there is ignored with a warning, and the command line removes it from the settings files. A `project_environment.json` of an earlier development version (a single "instrumentation scope") is no longer read; the command line says so.

### Call path pruning
The profiler enumerates a call path state for every path of the static call tree, which for large codes is most of the static data and of the cost of profiling. With the results of the [hotspot detection](Hotspot_detection.md) (`.discopop/hotspot_detection/Hotspots.json`), the LLVM pass can fold the states of functions that are neither hot nor lead to a hot function into the state of their caller, keeping the call paths of the hot code (`DP_CALLPATH_*`, see [Environment variables](../setup/environment_variables.md)). It is **off by default** and a project setting: `.discopop/project/callpath_pruning.json` (`enabled`, `hot_depth`, `unclassified`, `hotness`, kept by `--reset`), edited in the *Build* stage of the GUI (section *Call path pruning*, below *Shared build*, with the classes that count as hot, `YES` and `MAYBE` by default; collapsed and disabled unless the mode `dp` is selected, as no other mode prunes). The project manager then sets the variables for the `dp` compilation of every build; a `DP_CALLPATH_*` value in the environment or a settings file is ignored (with a warning).

Pruning only applies with *current* hotspot results: `Hotspots.json` classifies at least one region as hot, was made with the current project directories and the sources did not change since the instrumented `hd` build it belongs to. If current results exist and pruning is off, the console output of the `dp` compilation says that it could be activated (`WARNING: Call path pruning is not activated ...`), and so do the section in the *Build* stage and its chip in the `dp` mode. If it is on without current results, the compilation warns that nothing is pruned. After a pruned compilation, a `NOTE:` names the number of modules and call path states the pass reports.

The setting and the content of `Hotspots.json` are part of the fingerprint of `dp` builds (switching pruning or repeating the hotspot detection makes the build stale), and the profiling data records how it was pruned: if it differs from what a build would do now, the *Profiling* stage is marked stale and the MCP server treats the results as outdated.

### OpenMP flags
A program compiled with `-fopenmp` is profiled with its OpenMP pragmas active, which is rarely what the analysis needs (see [Instrumentation](Instrumentation.md#openmp-flags)). By default the project manager keeps the flags and the console output of the `dp` / `hd` compilation says so (`WARNING: The instrumented compilation kept the OpenMP flags ...`) together with how to remove them: the check box *Remove OpenMP flags* of the section *OpenMP flags* in the *Project Setup* stage of the GUI, or `--strip-openmp` on the command line (`--no-strip-openmp` keeps them for one invocation even if the setting removes them). The setting is stored in `.discopop/project/openmp_handling.json` (`strip`, off by default, kept by `--reset`) and passed to every instrumented compilation as `DP_STRIP_OPENMP=1`; a value of this variable in the environment or a settings file is ignored (with a warning). After a compilation that removed flags, a `NOTE:` says so.

The setting is part of the fingerprint of `dp` and `hd` builds (switching it makes the build stale, and the change cannot be accepted: compile again), and the profiling data records which way it was compiled: if that differs from the setting, the *Profiling* stage is marked stale and the MCP server treats the results as outdated.

### Checks of instrumented builds and runs
An instrumented build only produces consistent data if every compiler call uses the same `.discopop` directory. The project manager sets the absolute `DOT_DISCOPOP` for every run; without it (a build that resets the environment), the compiler wrappers use the nearest `.discopop` directory of the current directory and above, which is the one of the project or its copy, and the instrumented program remembers it. Only a `.discopop` below the project other than `$DOT_DISCOPOP` (a build that compiles outside of the project or whose compiler call finds no other directory) would spread the data over several of them, with file and instruction numbers that do not fit together. Therefore, in the `dp` and `hd` modes:

- a build fails if DiscoPoP data was written into a `.discopop` directory below the project other than `$DOT_DISCOPOP` (the build lost the variable on the way to a compiler, e.g. because it resets the environment or runs a compiler other than `$CC` / `$CXX`)
- a build warns if `FileMapping.txt` names no file in the project or an included directory (nothing will be profiled)
- a profiling run (`execute.sh`) fails if it did not write `profiler/dynamic_dependencies.txt` (`dp`) or a `hotspot_detection/private/hotspot_result_*.txt` (`hd`)

The messages are appended to the stderr output of the script.

### Execution modes
A run selects one of four modes, each backed by its own settings file:

| Mode | Purpose | Scripts executed |
|---|---|---|
| `seq` | sequential baseline | build → `execute.sh` → *validation* |
| `par` | parallelized code | build → `execute.sh` → *validation* |
| `dp` | DiscoPoP instrumentation | build → `execute.sh` |
| `hd` | hotspot detection instrumentation | build → `execute.sh` |

Only `execute.sh` is timed, and its duration is what the autotuner compares. The validation step is skipped entirely for `dp` and `hd`, which are profiling runs: re-running an instrumented binary would regenerate its profiling data.

### Measured runtime
By default the runtime of a run is the wall clock time of `execute.sh`. That also covers setup and teardown, reading input files and writing results — work that is often not what a parallelization is meant to speed up, and that dilutes every speedup computed from it.

When the program prints the duration of the region that actually matters, that value can be measured instead. The search is configured per configuration in `execution_time.json`, next to the `execute.sh` it applies to:

```json
{
  "enabled": true,
  "regex": "Total time:\\s*([0-9.]+)"
}
```

`regex` is a regular expression whose **first capture group** holds the value; the example above reads `1.234` out of `Total time: 1.234 seconds`. Leaving the file out, or setting `enabled` to `false`, measures the wall clock time as before — the stored pattern is kept either way, so switching the search off does not discard it. The default pattern looks for `<DP_EXEC_TIME>1.234</DP_EXEC_TIME>`, a tag a program can print regardless of how the rest of its output is formatted.

Both output streams are searched (`stdout` first, then `stderr`), and of several matches the **last** one is used, so a program printing a time per phase may end with the total. Only `execute.sh` is searched: `compile.sh` and `validate.sh` produce no measurement.

`--execution-time-regex` overrides the stored setting of every configuration for a single run:

| Given as | Effect |
|---|---|
| *(omitted)* | each configuration's `execution_time.json` applies |
| `--execution-time-regex` | search for the `<DP_EXEC_TIME>` tag |
| `--execution-time-regex 'Total time:\s*([0-9.]+)'` | search for that pattern |
| `--execution-time-regex ''` | measure the wall clock time, even where a configuration enables the search |

`discopop_auto_tuner` accepts the same option, so the search that ranks candidate patch sets measures the same time the report does.

If the pattern finds nothing, the wall clock time is measured instead and a warning is logged. Such a run is recorded with `"time_source": "wall_clock_fallback"`, so a fallback is never mistaken for a program that reported its own time. Every entry in `execution_results.json` carries the measured wall clock time as `wall_clock_time` alongside the reported `time`, whichever of the two `time` holds.

### Repeated measurements
A single run is one sample of a noisy quantity: another benchmark on the machine, a background rebuild, the page cache in whatever state the previous run left it — all of it lands in that one number, and two measurements of the *same* code can then differ by more than the effect being looked for.

`--execution-repetitions N` (`-xr N`) runs each measured execution `N` times and reports the **median** of the measured times. The median rather than the mean, because a single stalled run drags an average up but cannot move the middle value.

**The default is 3**, not 1: a runtime nobody asked to be trustworthy is still read as one, and three is the smallest count at which a median can ignore an outlier — two runs have no middle value. Pass `-xr 1` for the single measurement releases before this option made.

Of the repetitions, one is singled out as the *representative* — the run whose time is the median, or the lower of the two middle values when `N` is even. Its wall clock time, console output, return code and time source are what get recorded, so the stored entry describes one run that actually happened: the recorded `wall_clock_time` really is the wall clock time of the run whose `time` is reported, and the recorded `stdout` really is the output that time was read from.

Every individual measurement is kept alongside it, so a spread can be computed without re-running anything:

```json
{
    "time": 4.1,
    "wall_clock_time": 4.1,
    "repetitions": 5,
    "repetition_times": [4.1, 4.05, 6.8, 4.08, 4.12],
    "repetition_wall_clock_times": [4.1, 4.05, 6.8, 4.08, 4.12],
    "repetition_time_sources": ["console", "console", "console", "console", "console"],
    "time_aggregate": "median"
}
```

`time` still holds the measurement of interest, exactly as without repetitions, so the reports, the plots and everything else reading `execution_results.json` need to know nothing about the option.

`time_aggregate` says whether `time` is an aggregate at all, so a consumer never has to infer it from the number of repetitions:

| Value | `time` holds |
|---|---|
| `median` | the median of `repetition_times` |
| `failed_run` | the failing repetition's own time — the loop stopped there, so nothing was averaged |
| `not_measured` | nothing; the run was never started (see below), and `repetition_times` is empty |

What is and is not repeated:

| Run | Repeated | Why |
|---|---|---|
| `execute.sh` in `seq` / `par` | yes | these measure a runtime |
| `execute.sh` in `dp` / `hd` | no | instrumented profiling runs whose output feeds the Explorer; repeating them multiplies the profiling cost without improving a measurement |
| `compile.sh`, `compile_validate.sh`, `validate.sh` | no | they produce no measurement |

A repetition that exits non-zero or runs into its timeout ends the loop: a broken configuration will fail again, and that failing run is what gets recorded — a median taken among the repetitions that did succeed would describe the configuration as working. Such an entry is marked `"time_aggregate": "failed_run"`, since its `time` is one run's and not an average of any.

Combined with `--execution-time-regex`, a repetition whose output does not contain the pattern is measured by the wall clock instead — a systematically larger number, since it covers the setup, teardown and file I/O the pattern exists to exclude. Such a repetition is **left out of the median**, and a warning names how many were dropped: a program that only intermittently prints its timing is exactly the flaky case repetitions are meant to help with, and letting the fallbacks in would make the reported number worse the more often it happens. If *no* repetition reported a time, the wall clock times are all there is and their median is reported, as it would have been anyway. `repetition_time_sources` records how each repetition's time came about, so a reader can tell which of them the median was taken over.

The timeouts apply **per repetition**, not to the sequence, so `-tox` does not have to be raised alongside `-xr`. The total time a run takes does grow with `N`.

`discopop_auto_tuner` accepts the same option for its own candidate measurements, and the two are deliberately separate — including in their defaults, which are 3 here and **1** there. The search performs one program execution per *candidate*, so the same count would multiply the runtime of a whole search rather than of one reported number, and `--noise-threshold` already keeps noise out of its decisions. Repeating the final measurements alone gives a stable reported runtime at no cost to the search.

### Output validation
`validate.sh` is optional. Without it, a run counts as correct exactly when `execute.sh` exits `0`. With it, the run counts as correct only when **both** exit `0`. It is run separately from `execute.sh` so that validation work — dumping output, diffing against a reference — never enters the runtime measurement.

`validate.sh` may need a differently compiled binary than `execute.sh`: built with extra checks, against a reference implementation, or with an output-dumping flag. Provide those build instructions in `compile_validate.sh`. The full validation step is then:

```text
build (compile.sh)          →  execute.sh          →  build (compile_validate.sh)  →  validate.sh
        timeout-compilation        timeout-execution         timeout-compilation           timeout-validation
```

The validation build deliberately runs *after* the timed `execute.sh`, so it can never replace the binary whose runtime is being measured. If it fails, `validate.sh` is skipped and the run counts as incorrect. A `compile_validate.sh` is ignored for configurations that define no `validate.sh`, since there would be nothing to run against that build.

### Compile script resolution
Two build scripts are resolved independently: the one used for `execute.sh` and the one used for `validate.sh`. Both fall back from specific to shared, and the validation build additionally falls back to the execute build:

**Build for `execute.sh`**
1. `<configuration_name>/compile.sh`
2. `compile.sh`

**Build for `validate.sh`**
1. `<configuration_name>/compile_validate.sh`
2. `compile_validate.sh`
3. the build resolved for `execute.sh`

Note that the *role* of a script outranks how specific it is: a shared `compile_validate.sh` is used for validation even by a configuration that has its own `compile.sh` override. Reaching step 3 means a single build serves both scripts, which is the behaviour of a project that defines no validation build at all.

| Present files | Build for `execute.sh` | Build for `validate.sh` |
|---|---|---|
| `compile.sh` | `compile.sh` | `compile.sh` |
| `compile.sh`, `foo/compile.sh` | `foo/compile.sh` | `foo/compile.sh` |
| `compile.sh`, `compile_validate.sh` | `compile.sh` | `compile_validate.sh` |
| `compile.sh`, `foo/compile.sh`, `compile_validate.sh` | `foo/compile.sh` | `compile_validate.sh` |
| `compile.sh`, `compile_validate.sh`, `foo/compile_validate.sh` | `compile.sh` | `foo/compile_validate.sh` |

### Editing configurations
- **Graphically:** `discopop_gui` (or `discopop_project_manager --gui`). The configuration assistant creates a first configuration; afterwards the editor's sub-tabs manage `execute.sh`, `validate.sh` and the two override scripts, while the *Project Setup* stage (in the Tk GUI the *Compilation Editor*) manages the shared `compile.sh`, `compile_validate.sh` and the settings files. See [Graphical user interface](GUI.md).
- **By hand:** create the files listed above and mark the scripts executable.
- **Through an LLM agent:** the [DiscoPoP MCP server](MCP_server.md) exposes `set_compile_script` (with `purpose` selecting `compile.sh` or `compile_validate.sh`) and `create_execution_configuration` (which writes `execute.sh` and optionally `validate.sh` plus the override scripts).

## Executing configurations
`-x` takes a comma separated list of `<configuration>[:<mode>][:<threads>]`:

```bash
discopop_project_manager -x tiny                        # all four modes of tiny
discopop_project_manager -x tiny:seq:1,tiny:par:4       # two runs
discopop_project_manager -x tiny:par:4 -xr 5 -lp first  # five repetitions, label "first"
discopop_project_manager -xf                            # every configuration, all modes
```

- Modes are `seq`, `dp`, `hd` and `par`. Without a mode, all four run.
- The thread count is the value of `OMP_NUM_THREADS`. The default is half of the CPU count; `seq` always uses 1.
- Without `-x`, the configuration `tiny` is executed. An unknown configuration name produces an empty table and no error.
- `-l` lists the configurations and does nothing else.
- `-a <ids>` applies the comma separated suggestion ids before the execution. `-a auto` uses the suggestions selected by the autotuner (`auto_tuner/results.json`; the union if several configurations exist), `-a prm` those of the parallel region merger. Suggestions are applied in the project copy only; your sources stay untouched.

### Suggestions that patch files outside of the project
A project copy isolates only the files below the project directory. A suggestion whose patch targets a file outside of it (a shared source directory) would modify the original, which other projects may use. The project manager therefore skips such suggestions in the `auto` and `prm` selections (and logs which and why) and refuses them in `--apply-suggestions` (the run is skipped like any failed application) unless `--allow-patching-outside-project` is given. If it is given, the files are patched in place and **restored after each run** by rolling the suggestions back, also when the run fails or is stopped, and also with `--skip-cleanup`; because the rollback is per suggestion, the files of such a suggestion inside the copy are restored as well. Do not run several project manager instances that patch the same shared files at the same time.

### Builds
Unless `-i/--inplace` is given, a configuration is run in a *build*: a copy of the project (with the requested suggestions applied) that is compiled once and then **kept**, so that further runs execute in it instead of compiling again. This matters for large codes: running another input or thread count, or profiling again, does not repeat a long build.

- A build exists per configuration, mode and set of applied suggestions (its id is `<configuration>_<mode>[_s<hash of the suggestions>]`, its manifest is in `.discopop/project/builds/`). Its tree lies next to the project in `<project directory>_discopop_builds/<configuration>_<mode>`: **one tree per configuration and mode holds the build of one set of suggestions at a time**, so applying another set replaces the build of the previous one (its runs stay) instead of filling the disk with a copy per set. Builds compiled before this, with a tree `..._s<hash>` of their own, stay usable and deletable; so do builds whose suggestions may patch files outside of the project (`--allow-patching-outside-project`), which get a tree of their own. The tree includes the `.discopop` directory of the project at the time of the build, and the profiling data of `dp` and `hd` runs is written there.
- **Compiling again in the same tree.** A build does not copy the project again: the tree of its configuration and mode is updated in place. The suggestions are applied to copies of the files they patch first (a failed application leaves the tree as it was), and the patched files take the place of the project's. Files of the project whose content changed are written (with the current time, so that they look newer than what was compiled from them), files the project no longer has are deleted, and everything else the last compilation produced is removed, as is the tree's `.discopop`, which is copied anew. The compile script then runs as in a fresh copy (the console says `Updating the build tree ...` and how many files were written). What the tree holds is recorded in `.discopop/project/builds/trees/<build id>.json`; a tree without such a record or whose update was interrupted is copied anew.
- **Incremental builds (`compile_incremental.sh`).** Optionally, a configuration can say how its build is *continued* rather than redone: `compile_incremental.sh`, next to `compile.sh` (`<configuration>/compile_incremental.sh`, otherwise the shared `configs/compile_incremental.sh`, which only applies to configurations using the shared `compile.sh`). It is used for the modes `seq` and `par` only (instrumented builds are always compiled in full) and only when the tree was last compiled successfully in the same environment (the same compile scripts, settings, project directories, configuration files and compilers); otherwise, after a validation build in the tree, after a failed compilation and with `--rebuild`, `compile.sh` runs. When it is used, the changed files of the project are written into the tree and the outputs of the last compilation are **kept**, so the build system compiles only what changed: applying another set of suggestions recompiles the files they patch, not the whole program. The console says `Compiling incrementally (compile_incremental.sh)`, the manifest and every result of `compile` and `execute` record `build_kind` (`full` or `incremental`).
  - Both scripts get `DP_BUILD_KIND` (`full` or `incremental`) and otherwise the same environment.
  - `compile_incremental.sh` must only rebuild: no `rm -rf` of the build directory, no `make clean`, normally no configure step. It must build what `execute.sh` runs through the dependency tracking of the build system.
  - If it fails, or if it writes no file at all although files of the project changed (the program would be stale), the project manager says so, removes the outputs and runs `compile.sh` instead. A build that rebuilds *something* but not everything (e.g. missing header dependencies of a hand-written Makefile) cannot be detected this way: track dependencies (`-MMD -MP`) or do not use an incremental script.
  - Examples, for a `compile.sh` that configures into `build/`:

    | Build system | `compile.sh` | `compile_incremental.sh` |
    |---|---|---|
    | CMake | `cmake -S . -B build -DCMAKE_CXX_COMPILER="$CXX" && cmake --build build -j` | `cmake --build build -j` |
    | CMake superbuild (`ExternalProject`, e.g. Kripke) | `cmake -S . -B build ... && cmake --build build -j` | `cmake --build build/kripke-build -j` (the inner project: the outer build does not see changed sources of an external project without `BUILD_ALWAYS`) |
    | make | `make clean && make CC="$CC" -j` | `make CC="$CC" -j` |
    | autotools | `./configure CC="$CC" && make -j` | `make -j` |
    | meson | `meson setup build && ninja -C build` | `ninja -C build` |

- **What a copy leaves out.** A build directory configured in the project does not work in a copy at another path: CMake stores the absolute source and build directories in `CMakeCache.txt`, so `cmake ..` in the copy stops with an error, and `make` in a copied CMake build directory silently compiles and links the sources of the *project* into the build directory of the *project*, never the patched sources of the copy. Every copy of the project (the builds and the [autotuner](Autotuner.md)'s candidates) therefore leaves out:
  - a directory with a `CMakeCache.txt` of an out-of-source build (its `CMAKE_HOME_DIRECTORY` is another existing directory), a meson build directory (`meson-private`) and an autotools build directory outside the sources (`config.status` and `config.log` without a `configure` next to them), each as a whole;
  - of an in-source CMake build (or one whose `CMAKE_HOME_DIRECTORY` does not exist any more, e.g. a tree copied by hand) only `CMakeCache.txt` and `CMakeFiles` (the sources and generated `Makefile`s next to them are copied); a compile script that runs a bare `make` there without `cmake` first now fails visibly instead of building the original;
  - the paths listed in `.discopop/project/copy_exclude.json` (`{"copy_exclude": ["data", "old_build"]}`, relative to the project directory, files or directories; `.discopop` cannot be listed): the build directories of build systems without such a marker, or large input data that `execute.sh` reads through `$DP_PROJECT_ORIGINAL_DIR`.

  What was left out is named in the console when a build is copied (`Not copied: ...`). These paths are no input of a build, so their files do not make a build stale, also when such a directory is deleted later (the build keeps what it left out); a build compiled before this rule existed and without a file list is the exception; the list itself is part of the fingerprint, so changing it compiles again. Compile scripts that configure their build directory first (`cmake -S . -B build`, `meson setup`, `./configure`) are not affected.
- A build is *current* as long as the files of the project (path, size and modification time of every file outside `.discopop` and `.git` that the copy does not leave out), the compile script, the settings file of the mode, the included and excluded project directories, for `dp` builds the call path pruning (setting and hotspot results, see [Call path pruning](#call-path-pruning)), the generated patches (for builds with suggestions) and the installed profiler are unchanged. A run compiles only if there is no current build (`--rebuild` compiles in any case). The thread count is no part of it. A build whose suggestions patch files outside of the project is never reused.
- **What changed, and ignoring it.** A stale build is reported with the parts of its fingerprint that changed and, for the files of the project, how many were modified, added or removed and in which top-level directories (e.g. `Changed since the build: sources. 742 files changed (742 modified): dp_build/ (742).`). If the change of `callpath_pruning` follows from something else (hotspot results that are outdated because their `hd` build is stale), that is said as well. Every build keeps the list of files its fingerprint was made of in `.discopop/project/builds/fingerprints/<build id>.json`; for a build older than that list, the files newer than the build are reported instead.
  - If the project directory is the root of a git work tree, files that git ignores never count (a project in a subdirectory of a repository counts all its files). A build directory of the project's own build system that is *not* in `.gitignore` (e.g. `dp_build/` of a compile script that builds in place, which a test compilation in the project directory refreshes) would make every build stale: list it in `.discopop/project/fingerprint_ignore.json` (`{"patterns": ["dp_build/"]}`, kept by `--reset`). A pattern is relative to the project directory: `dir/` or a path without wildcards ignores everything below it, otherwise it is a shell wildcard pattern on the path (`docs/*.md`), and one without `/` also matches the file name in every directory (`*.log`). The files are still compiled; only the fingerprint ignores them. The patterns apply to the existing builds as well (their file lists are compared with the patterns of now), so adding one makes a build current again without compiling; a build compiled before builds kept their file list needs to be accepted or compiled once for that.
  - In the GUI's *Build* stage, *Show changes...* (next to *Check selected builds*) lists the changed files of the selected build and offers to ignore paths (it proposes top-level directories that git tracks nothing in, or, without git, that hold a `CMakeCache.txt`, `build.ninja`, `meson-info` or `CACHEDIR.TAG`) or to **accept the build as current**: after a confirmation, the build's fingerprint becomes that of the project now and runs reuse it, with the code (and, for `dp`, the call path pruning) it was compiled with. The acceptance is noted in the build's file list and named in the console whenever the build is reused. A change of the call path pruning cannot be accepted (the tree stays pruned as compiled, and its data would claim another pruning); if it only follows from a stale `hd` build, accept or rebuild that one first. The card *Ignored in build fingerprints* edits the patterns. Neither the command line nor the MCP server accepts changes: that is a decision of the user.
- `--reuse-build` never compiles and fails if there is no current build; `--build-only` compiles and does not execute. Both and `--rebuild` are available in the GUI as well: its *Build* stage (first of the pipeline) compiles the selected configuration in the mode seq, dp or hd into a kept build and lists the builds; *Profiling* then runs in it and lists the runs; the *Pattern Detection* stage names the run its data comes from and lets you choose another one.
- **Sharing a build.** Configurations that differ only in what `execute.sh` does (input, arguments, thread count) can share one build: `--share-build MEMBER:OWNER` lets `MEMBER` build from `OWNER` (stored in `configs/<member>/build_from.json`; `--unshare-build MEMBER` undoes it). The compile script, the settings and the files of the owner make the build, which is compiled once (with one thread, whichever member runs first); the `execute.sh` / `validate.sh` of each member run in the owner's build tree, and their results stay recorded under the member (the run lists name the configuration that ran). Sharing is refused if the member has files of its own that change the build (e.g. a `compile.sh` override) or the owner has a separate validation compile script (`compile_validate.sh`; its build would change the shared tree after every validation), and builds are not chained (an owner builds for itself). Renaming an owner re-points its members; deleting it lets them build for themselves. Runs in a shared build are serialized (one holds the build lock at a time). `--list` shows who builds from whom, `--list-builds` who else uses a build. The GUI's *Build* stage has a *Shared build* section for this. The *Hotspots* stage and the MCP server follow the declaration as well (`create_execution_configuration` has a `build_from` parameter); the Hotspots stage no longer shares a build between configurations merely because they use the same compile script.
- `--list-builds` shows the builds, their size and whether they are current; `--delete-builds [ids]` deletes the given builds (all without ids). **Builds are never deleted automatically** and may need much disk space, in particular when many sets of suggestions are applied.
- Every `dp` or `hd` run of a build writes its results into a *run directory* of its own, `<project directory>_discopop_builds/<build id>.runs/<run id>`, that is prepared from the static data of the build and used as `DOT_DISCOPOP` of `execute.sh`. Runs of one build with other inputs therefore never overwrite each other, and they survive building again. The measurements in `execution_results.json` carry the `build_id` and `run_id`.
- `--list-runs` shows the runs. `--activate-run [id]` puts a run (without an id: the latest successful `dp` run) into the `.discopop` directory of the project, where the explorer reads it: the data of the same kind that was there is replaced, the paths of the build tree become paths of the project, and `.discopop/active_run.json` names the run. A run of a build with applied suggestions cannot be activated (its line numbers differ from your sources). `--delete-runs [ids]` deletes runs (all without ids). **Runs are never deleted automatically.**
- `--skip-cleanup` only keeps the copy of a build that failed (the tree of a successful build is always kept).
- The [MCP server](MCP_server.md)'s `gather_data` uses the builds `<configuration>_hd` and `<configuration>_dp` as well, so a long compilation is not repeated by a second call, and it warns when builds and runs pile up (number and storage). The GUI's *Hotspots* stage runs in the `hd` build as well (configurations with the same compile script share one; it is listed in the *Build* stage, and a second measurement does not compile again). `run_configuration` and the autotuner compile in the project or in copies of their own.

With `-i`, the configuration is compiled and executed in the project root, no build is kept or reused, and the profiling data of `dp` and `hd` runs is written to `.discopop/profiler` and `.discopop/hotspot_detection` of the project, which is where the [Explorer](Explorer.md) reads it:

```bash
discopop_project_manager -x tiny:dp:4,tiny:hd:4 -i
```

## Output
- `.discopop/project/execution_results.json`: the results of every script run, structured as `{configuration: {script: {settings file: [entry, ...]}}}`, for example `["tiny"]["execute.sh"]["seq_settings.json"]`. The key is the name of the settings file, not the mode. An entry holds, among others, `code`, `time`, `wall_clock_time`, `time_source`, `thread_count`, `label`, `applied_suggestions`, `requested_suggestions`, `failed_suggestions`, `repetitions`, `repetition_times` and `time_aggregate`. A new run replaces an entry with the same suggestions, thread count and label.
- `.discopop/project/reports/<timestamp>/`, created by `--report`: `report.csv`, `speedups.pdf`, `efficiency.pdf`, `execution_time.pdf`, `execution_time_full.pdf` and `full_report.pdf`. The console shows the table as well. Speedup is relative to the `seq` run of the same script. The Amdahl pages of `full_report.pdf` estimate the best possible speedup of the applied suggestions from the hotspot runtimes and the suggestion extents of the explorer (`explorer/suggestion_extents.json`, see [Explorer output](../data/Explorer_output.md)); `--report` extracts missing extents of an older detection result from its dump, the GUI asks first.
- Profiling data of `dp` and `hd` runs below `.discopop/profiler` and `.discopop/hotspot_detection` of the project (with `-i`) or of the build tree.

The project manager does not run the Explorer. After a `dp` run, run `discopop_explorer` inside `.discopop` (see [Explorer](Explorer.md)); the GUI and the MCP server do this step for you.

## Options

| Option | Default | Description |
|---|---|---|
| `-p`, `--project PATH` | current directory | Root of the project. It must be possible to copy it and build the copy. |
| `--init` | | Initialize `.discopop` (see above). |
| `--gui` | | Open the [graphical interface](GUI.md); needs a display. |
| `--gui-toolkit {tk,qt}` | `qt` | The toolkit of the `--gui` window: the Qt (PySide6) version or the old Tk version. |
| `-x`, `--execute LIST` | `tiny` | Comma separated `<configuration>[:<mode>][:<threads>]`. |
| `-xf`, `--execute-full` | | Execute all configurations. |
| `-a`, `--apply-suggestions IDS` | | Suggestion ids to apply before the execution, or `auto` / `prm`. Suggestions that patch files outside of the project are refused unless `--allow-patching-outside-project` is given; `auto` / `prm` never include them. |
| `--allow-patching-outside-project` | off | Allow `--apply-suggestions` to apply suggestions that patch files outside of the project (shared sources). |
| `-l`, `--list` | | List the configurations; nothing else is done. |
| `-i`, `--inplace` | off | Execute in the project root instead of a copy. |
| `--skip-cleanup` | off | Keep the copy of a failed build. |
| `--rebuild` | off | Compile even if a current build exists. |
| `--reuse-build` | off | Never compile; run in the existing current build (not with `-i`). |
| `--build-only` | off | Compile only, do not execute. |
| `--share-build MEMBER:OWNER` | | Let the configuration `MEMBER` use the build of `OWNER`; nothing else is done. |
| `--unshare-build MEMBER` | | Let `MEMBER` build for itself again; nothing else is done. |
| `--list-builds` | | List the builds; nothing else is done. |
| `--delete-builds [IDS]` | | Delete the builds with the given ids, all without ids; nothing else is done. |
| `--list-runs` | | List the profiling runs of the builds; nothing else is done. |
| `--activate-run [ID]` | | Put the run (default: the latest successful `dp` run) into the project's `.discopop`; nothing else is done. |
| `--delete-runs [IDS]` | | Delete the runs with the given ids, all without ids; nothing else is done. |
| `--report` | | Generate the report from the stored results. |
| `--show-report` | | Only has an effect together with `--report`, where it opens the PDF with `xdg-open`. Alone it does not show a report. |
| `-r`, `--reset` | | Delete everything in `.discopop` except `project/`; implies `-rx`. |
| `-rx`, `--reset-execution-results` | | Delete `execution_results.json` and the reports. |
| `-lp`, `--label-prefix` | empty | Prefix of the label stored with the measurements. |
| `-tox`, `--timeout-execution` | 3600 | Timeout of each execution in seconds; 0 disables it. |
| `-toc`, `--timeout-compilation` | 3600 | Timeout of each compilation in seconds; 0 disables it. |
| `-tov`, `--timeout-validation` | 3600 | Timeout of each validation in seconds; 0 disables it. |
| `-xr`, `--execution-repetitions N` | 3 | Repetitions of `execute.sh` in `seq` and `par`; the median is reported. |
| `-etr`, `--execution-time-regex [RE]` | per configuration | Read the time from the output. Without a value: the `<DP_EXEC_TIME>` tag; `''` disables the search. |
| `--project-exclude-dirs DIRS` | `excluded_directories.json` | [Excluded directories](#project-directories) for this invocation, relative to the project root, separated by `:`; `''` excludes none. |
| `--project-include-dirs DIRS` | `included_directories.json` | [Included directories](#project-directories) outside the project for this invocation, absolute, separated by `:`; `''` includes none. |
| `--strip-openmp`, `--no-strip-openmp` | `openmp_handling.json` | Remove (keep) the [OpenMP flags](#openmp-flags) from the instrumented compilations for this invocation. |
| `-v`, `--verbose` | off | Verbose output. |
| `--log LEVEL` | `WARNING` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `--write-log` | off | Write a log file. |
