---
layout: default
title: Project manager on the command line
parent: Examples
nav_order: 2
---

# Project manager on the command line
This walk-through runs the whole workflow with `discopop_project_manager` on the example program: set up a project, measure it, detect patterns, autotune and apply suggestions. All options are described in [Project manager](../tools/Project_manager.md) and [Autotuner](../tools/Autotuner.md). The same workflow is available in the [GUI](walk_through_gui.md).

Prerequisites: DiscoPoP is [installed](../setup/discopop.md) and the virtual environment is active. Work on a copy of the example:

```bash
cp -r example my_project && cd my_project
```

## 1. Initialize the project
```bash
discopop_project_manager --init
```

`--init` creates the folder `.discopop/project/configs` with two files:

| File | Content |
|---|---|
| `compile.sh` | placeholder that exits with an error until you edit it |
| `seq_settings.json` | `{"CC": "clang", "CXX": "clang++", "CFLAGS": "", "CXXFLAGS": ""}` |

You write two scripts yourself. Both are executed from the project root. `compile.sh` must use `$CC`/`$CXX` and `$CFLAGS`/`$CXXFLAGS`; `execute.sh` runs the program that `compile.sh` built. A *configuration* is a folder below `configs/` that contains an `execute.sh`; its name is the name of the configuration (`tiny` is the default of `-x`).

```bash
cat > .discopop/project/configs/compile.sh <<'X'
#!/bin/bash
$CXX $CXXFLAGS example.cpp -o prog
X
mkdir .discopop/project/configs/tiny
printf '#!/bin/bash\n./prog\n' > .discopop/project/configs/tiny/execute.sh
chmod +x .discopop/project/configs/compile.sh .discopop/project/configs/tiny/execute.sh
```

The files `dp_settings.json`, `hd_settings.json` and `par_settings.json` are derived from `seq_settings.json` (and overwritten) each time you execute a configuration: the compilers become `discopop_cc`/`discopop_cxx` for the profiling mode `dp` and the hotspot detection wrappers for `hd`, and `-fopenmp` is added for `hd` and `par`. Edit `seq_settings.json`, not the derived files.

## 2. Execute configurations
```bash
discopop_project_manager -x tiny
```

The project is copied next to itself, compiled and executed once per mode, and the copy is deleted afterwards. The modes are `seq` (sequential), `dp` (instrumented, profiling), `hd` (hotspot detection) and `par` (parallel). The result is a table:

```text
+---------------+-----------------------+---------------+
| Configuration | Overview              | (C) Autotuner |
+---------------+-----------------------+---------------+
| tiny          | (PASS) dp - settings  | PASS          |
|               | (PASS) dp - compile   |               |
|               | ...                   |               |
|               | (PASS) par - execute  |               |
+---------------+-----------------------+---------------+
```

The measurements are stored in `.discopop/project/execution_results.json`. `-l` lists the configurations without executing anything; `-xf` executes all configurations.

Select modes and thread counts with `<config>[:<mode>][:<threads>]`, separated by commas. Repeat the timed runs with `-xr` and label them with `-lp`:

```bash
discopop_project_manager -x tiny:seq:1,tiny:par:2 -xr 5 -lp first
```

Only the `seq` and `par` runs are repeated (default: 3 repetitions); the `dp` and `hd` runs and all compilations run once. Each result is stored as an entry of a list per configuration, script and settings file.

## 3. Keep the profiling data
Pattern detection needs the data of a `dp` run. A run without `-i` happens in a *build*, a copy of the project that is kept and reused by later runs as long as nothing changed (`--list-builds` shows them, `--delete-builds` removes them). The data lands in the `.discopop` directory of the build. To get it into the project, where the explorer reads it, run in the project directory:

```bash
# run in the project directory; data lands in ./.discopop/profiler
discopop_project_manager -x tiny:dp:4,tiny:hd:4 -i
# or run in a build (<project folder>_discopop_builds/<config>_<mode>, next to the project)
discopop_project_manager -x tiny:dp:2
discopop_project_manager --list-builds
```

`-i` also leaves the built program (`prog`) in the project root. The hotspot data of the `hd` run lands in `.discopop/hotspot_detection`.

## 4. Detect patterns
The project manager does not run the explorer; run it in `.discopop` (the GUI does it for you). The parentheses run the command in a subshell, so you stay in the project directory for the next steps:

```bash
(cd .discopop && discopop_explorer --enable-patterns "reduction,doall")
```

It finds suggestions 0 (the initialization loop) and 1 (the summation loop, `reduction(+:sum)`); see the [command line walk-through](walk_through.md).

## 5. Report
```bash
discopop_project_manager --report
```

prints a table with one row per configuration, script and settings file (columns `Config`, `Script`, `Setting`, `Label`, `Applied Suggestions`, `Threads`, `Code`, `Time`, `Speedup`, `Efficiency`; the speedup is relative to the `seq` run of the same script) and writes `.discopop/project/reports/<timestamp>/` with `report.csv`, `speedups.pdf`, `efficiency.pdf`, `execution_time.pdf`, `execution_time_full.pdf` and `full_report.pdf`.

## 6. Autotune
The [autotuner](../tools/Autotuner.md) applies suggestions to project copies, measures them and records the best combination. It needs the explorer output and a project without applied suggestions. Run it inside `.discopop`; `-t` sets the number of threads:

```bash
(cd .discopop && discopop_auto_tuner -c tiny -t 2)
```

```text
@@AT_PROGRESS {"config": "tiny", "event": "baseline", "runtime": 0.0036, "thread_count": 2, "valid": true}
@@AT_PROGRESS {"config": "tiny", "event": "measurement", "index": 2, "speedup": 0.5955, "suggestions": [0], ...}
@@AT_PROGRESS {"config": "tiny", "event": "measurement", "index": 3, "speedup": 0.6128, "suggestions": [1], ...}
##############################
Applied suggestions: [1]
Speedup:  0.617
Parallel efficiency:  0.308
##############################
```

The default algorithm (`-A 0`) measures every suggestion alone. The result is stored in `.discopop/auto_tuner/results.json`:

```json
{"tiny": {"applied_suggestions": ["1"], "speedup": 0.617, "efficiency": 0.308, "time": 0.005821}}
```

{: .note }
The example runs for a few milliseconds, so thread start-up costs more than the parallel loop gains and the speedup is below 1. Use a realistic workload to see a gain. The output also prints a "Best configuration located at" path; that project copy is deleted unless you pass `--skip-cleanup`, so the file `results.json` is the result to use.

## 7. Apply suggestions
`-a` applies suggestions in the project copy that the executed configuration runs in. Your sources stay untouched.

```bash
# the suggestions chosen by the autotuner (results.json)
discopop_project_manager -x tiny:par:2 -a auto
# explicit suggestion ids; the patched build is kept to inspect it (see --list-builds)
discopop_project_manager -x tiny:par:2 -a 1
```

The kept build (`../my_project_discopop_builds/tiny_par_s<hash>`, see `--list-builds`) contains the added `#pragma omp parallel for ...`. The entry in `execution_results.json` lists `applied_suggestions`, `requested_suggestions` and `failed_suggestions`. To change the original sources, use the [patch applicator](../tools/Patch_applicator.md).

## 8. Reset
```bash
discopop_project_manager -rx   # delete execution_results.json and the reports
discopop_project_manager -r    # additionally delete everything in .discopop except project/ (configurations are kept)
```

`-r` includes `-rx`.
