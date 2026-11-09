---
layout: default
title: Command line walk-through
parent: Examples
nav_order: 1
---

# Command line walk-through
This example shows the complete process from a sequential program to a parallel one, using the individual DiscoPoP tools on the command line. The program is `example/example.cpp` of the repository.

## Prerequisites
- DiscoPoP is [installed](../setup/discopop.md) and the virtual environment is active (`source venv/bin/activate`).
- Work on a copy of the example. Run the commands from your copy:

```bash
cp -r example /tmp/dp_example && cd /tmp/dp_example
```

## Step 1: Instrument and build
`discopop_cxx` (for C: `discopop_cc`) replaces the compiler. It runs the static analysis, instruments the code and links the runtime library.

```bash
discopop_cxx example.cpp -o example
```

If your project uses CMake, set the compilers instead (use `-DCMAKE_C_COMPILER=discopop_cc` for C code as well). The folder `example/` contains a `CMakeLists.txt` that builds `cmake_example`:

```bash
mkdir build && cd build
cmake -DCMAKE_CXX_COMPILER=discopop_cxx ..
make
```

Both variants create the folder `.discopop` in the directory the compiler was started from (for CMake: `build/.discopop`). It stores all data of the following steps; see [Data](../data/data.md).

The outputs below come from the direct variant. With the CMake variant, the patches currently lack the clause `firstprivate(N)`; both versions of the patches are valid.

{: .note }
The build prints a warning that `DP_PROJECT_ROOT_DIR` is not set. Without it, library functions may be instrumented as well, which increases the profiling time. It also warns that `DOT_DISCOPOP` is not set: harmless here, as the program is compiled in one directory and started from it, but a build compiling in several directories needs the same absolute `DOT_DISCOPOP` for every compiler call. See [Environment variables](../setup/environment_variables.md).

## Step 2: Run the instrumented program
Run the program as usual. The profiler writes the dependencies it observes to `.discopop/profiler`.

```bash
./example
```

```text
Outputting instrumentation results... done
```

For the CMake variant run `./cmake_example` inside `build/`.

{: .note }
Profiling slows the program down considerably. Use a small input that still represents typical executions.

## Step 3: Identify parallel patterns
Run the [explorer](../tools/Explorer.md) inside `.discopop`. By default it searches for reductions and do-all loops.

```bash
cd .discopop
discopop_explorer
```

It prints its progress and ends with the identified suggestions:

```text
✓ Detecting patterns (0.0s)
Generating parallelization patches...
✓ Generating parallelization patches (0.4s)
───────────────────────────
  Suggestion IDs by files
───────────────────────────
==> /tmp/dp_example/example.cpp
|---> 0
|---> 1
```

The explorer writes:

| Path | Content |
|---|---|
| `.discopop/explorer/patterns.json` | the identified patterns, one entry per suggestion |
| `.discopop/explorer/pattern_decisions.json`, `detection_result_dump.json`, `side_effects.json.gz` | further results of the analysis |
| `.discopop/patch_generator/<id>/` | one patch file per source file for each suggestion |
| `.discopop/patch_applicator/applied_suggestions.json` | the list of applied suggestions (empty) |

Suggestion 0 is the initialization loop (`pattern_id` 0 in the `do_all` list of `patterns.json`, pragma `#pragma omp parallel for`, with `N` as `firstprivate`). Suggestion 1 is the summation loop, a reduction (`reduction(+:sum)`).

{: .note }
The explorer prints hints for the VS Code extension at the end. You can ignore them if you use the GUI or the command line; see [VS Code extension walk-through](walk_through_vscode.md).

## Step 4: Look at the patches
The explorer has already created the patches. Run `discopop_patch_generator` only to generate them again, e.g. after you changed what the explorer found. See [Patch generator](../tools/Patch_generator.md).

```bash
cat patch_generator/0/1.patch patch_generator/1/1.patch
```

```diff
@@ -17,6 +17,7 @@
   long sum = 0;
   int Arr[N];

+  #pragma omp parallel for firstprivate(N)
   for (int i = 0; i < N; i++) {
     Arr[i] = i % 13;
   }
@@ -21,6 +21,7 @@
     Arr[i] = i % 13;
   }

+  #pragma omp parallel for firstprivate(N) reduction(+:sum)
   for (int i = 0; i < N; i++) {
     sum += Arr[i];
   }
```

The file name `1.patch` is the id of the source file (see `FileMapping.txt`), not the suggestion id. The folder name is the suggestion id.

## Step 5: Apply and manage patches
The [patch applicator](../tools/Patch_applicator.md) applies, lists and rolls back suggestions in the sources of your project.

```bash
discopop_patch_applicator -a 0 1    # apply suggestions 0 and 1
grep -n pragma ../example.cpp
```

```text
20:  #pragma omp parallel for firstprivate(N)
25:  #pragma omp parallel for firstprivate(N) reduction(+:sum)
```

| Command | Effect |
|---|---|
| `discopop_patch_applicator -l` | list the applied suggestions (`Applied suggestions:  ['0', '1']`) |
| `discopop_patch_applicator -r 1` | roll back suggestion 1; only 0 stays applied |
| `discopop_patch_applicator -C` | reset the code to the original; the list of applied suggestions is saved |
| `discopop_patch_applicator -L` | load the saved list again and re-apply it (after `-C`: only suggestion 0) |

Compile the patched `example.cpp` with OpenMP enabled (`-fopenmp`) to run the parallel version. Reset with `-C` when you are done.

## Step 6: Next steps
- [Autotuner](../tools/Autotuner.md): measures which suggestions actually speed the program up.
- [Project manager](../tools/Project_manager.md): organizes build and run scripts, measurements and reports; see [Project manager on the command line](project_manager_cli.md).
- [GUI walk-through](walk_through_gui.md): the same workflow in a graphical user interface.
