---
layout: default
title: Hotspot detection
parent: Tools
nav_order: 4
---

# Hotspot detection
## Executables
`discopop_hotspot_cc`, `discopop_hotspot_cxx` and `discopop_hotspot_analyzer`. They are installed with the `discopop-hotspot-detection` package (part of `pip install discopop`).

## Purpose
Hotspot detection finds the code regions (loops and functions) that deserve your attention. It measures the time spent in every region and classifies each region by two criteria:

- **A**: the region contributes a lot to the runtime of the program (high average runtime).
- **B**: the runtime of the region grows strongly when you change the program's input (high ratio between the runs).

| Class | Criteria | Name in the README of the package |
|---|---|---|
| `YES` | A and B | HOT |
| `MAYBE` | A or B, not both | WARM |
| `NO` | neither | COLD |

Other tools use the classes to concentrate on the relevant code (see [Use of the results](#use-of-the-results)). The method is described in: Mohammadi et al., *Filtering and Ranking of Code Regions for Parallelization via Hotspot Detection and OpenMP Overhead Analysis*, SC-W 2023, [doi:10.1145/3624062.3624206](https://doi.org/10.1145/3624062.3624206).

## Usage
### 1. Build with the hotspot wrappers
Use the wrappers in place of your compiler. They call `clang` / `clang++`, run the hotspot detection pass and link its runtime. Like the [compiler wrappers](Instrumentation.md), they are launchers for scripts in the `site-packages` of your virtual environment.

```bash
cd <project directory>
discopop_hotspot_cxx example.cpp -o a.out     # C++
discopop_hotspot_cc  example.c   -o a.out     # C
```

For Makefile and CMake projects, pass them as compilers, for example `make CC=discopop_hotspot_cc CXX=discopop_hotspot_cxx`. The README of the package gives for CMake:

```bash
cmake -DCMAKE_C_COMPILER_WORKS=1 -DCMAKE_CXX_COMPILER_WORKS=1 \
      -DCMAKE_C_COMPILER=discopop_hotspot_cc -DCMAKE_CXX_COMPILER=discopop_hotspot_cxx ..
```

<!-- UNVERIFIED: the CMake invocation was not run. The Makefile one is run by test/end_to_end/hotspot_parallel_build. -->

Parallel builds (`make -j`, `cmake --build -j`) are supported: the compiler processes take turns while they number the code regions (a lock in `.discopop/hotspot_detection/locking_files/`), so every region gets an id of its own. If the lock cannot be taken (a file system without file locks, such as NFS without `lockd`, or a `.discopop` owned by another user), the compilation continues without it and warns that the ids of a parallel build may collide; build serially in that case.

The build creates `.discopop/FileMapping.txt` and `.discopop/hotspot_detection/private/` (with `cs_id.txt`, the table of the instrumented code regions).

### 2. Run the program several times
Run the instrumented program with different inputs, ideally with different problem sizes, since criterion B compares the runs:

```bash
./a.out <input 1>
./a.out <input 2>
```

Every run adds a file `hotspot_result_<N>.txt` to `.discopop/hotspot_detection/private/`. With a single run, every ratio is constant and the classification only reflects the average runtime.

### 3. Analyze
Run the analyzer inside the `.discopop` directory:

```bash
cd .discopop
discopop_hotspot_analyzer
```

| Option | Default | Description |
|---|---|---|
| `--input-dir DIR` | `private` | Directory inside `hotspot_detection/` that holds `cs_id.txt` and the `hotspot_result_<N>.txt` files |
| `--no-merge-runs` | off | Analyze the directory as it is. By default, the runs are first renumbered into one id space that does not depend on the build (written to `hotspot_detection/merged`); this allows combining runs of several builds or configurations. Without merging, the result is only correct for a project that was compiled exactly once. |

### With the project manager and the GUI
The `hd` mode of the [project manager](Project_manager.md) builds your project with the hotspot wrappers (`hd_settings.json`) and runs `execute.sh`:

```bash
discopop_project_manager -x tiny:hd -i
cd .discopop && discopop_hotspot_analyzer
```

The analyzer is not part of the project manager. The *Hotspot Detection* tab of the [GUI](GUI.md) builds, runs several times, collects the runs of several configurations and calls the analyzer for you. The [MCP server](MCP_server.md) does the same through `gather_data` with `hotspot_config_names` and returns the regions with `get_hotspots`.

## Output
`.discopop/hotspot_detection/Hotspots.json` holds one entry per code region. Real output for the example program of the repository (two runs, shortened):

```json
{"code_regions": [{
    "csid": 2,
    "typ": "LOOP",
    "fid": 1,
    "lineNum": 20,
    "name": "",
    "runtimes": [0.000256, 0.000254],
    "level": 0,
    "hot": true,
    "hotness": "MAYBE",
    "delta": 2e-06,
    "avr": 0.000255,
    "sum": 0.00051,
    "minVal": 0.000254,
    "maxVal": 0.000256,
    "ratio": 0.5019607843137255,
    "topAvr": true,
    "topRatio": false
}]}
```

| Field | Meaning |
|---|---|
| `csid` | Id of the code region (unique within one build) |
| `typ` | `LOOP` or `FUNCTION` |
| `fid`, `lineNum`, `name` | File id (see [File mapping](../data/Filemapping.md)), line and, for functions, name |
| `runtimes` | Time in seconds of the region in each run |
| `avr`, `sum`, `minVal`, `maxVal` | Average, sum, minimum and maximum of `runtimes` |
| `ratio` | `1 / (minVal / maxVal + 1)`: 0.5 if all runs take equally long, towards 1 when the runtime varies strongly |
| `topAvr`, `topRatio` | The region is at or above the middle value of all regions by average runtime (A) / by ratio (B) |
| `hotness` | `YES` (both), `MAYBE` (one), `NO` (none) |

The directory also contains `Hotspots.txt`, the `merged/` directory and, written by the GUI, `measurement_runs.json`.

## Use of the results

| Consumer | Use |
|---|---|
| [Explorer](Explorer.md) | `--hotspot-types` (default `yes,maybe`): only regions of these classes are analyzed. Without `Hotspots.json`, the whole program is analyzed. |
| [Empirical autotuner](Autotuner.md) | `-A 6` requires hotspot results and ranks the regions by class and runtime. `-ht/--hotspot-types` selects the classes (default `yes,no,maybe`). For the other algorithms, hotspots are optional; without them, every suggestion counts as `yes`. |
| [Patch repair](Patch_repair.md) | `--hotspot-types` (default `yes,maybe`) skips suggestions in cold code |
| [GUI](GUI.md), [MCP server](MCP_server.md) | Show the regions and their classes |
| VS Code extension | Shows the hotspots in the editor, see [VS Code extension](../setup/vscx.md) |

Further information: [README of the package](https://github.com/tuda-hpclab/discopop/blob/master/hotspot_detection/README.md).
