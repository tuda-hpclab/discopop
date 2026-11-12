---
layout: default
title: Compiler wrappers
parent: Tools
nav_order: 3
---

# Compiler wrappers
## Executables
`discopop_cc` (C) and `discopop_cxx` (C++). Both are installed with the `discopop-profiler` package into the `bin` directory of your virtual environment.

## Purpose
The wrappers build the instrumented version of your sequential program. They call `clang` / `clang++` with the DiscoPoP LLVM pass, which instruments the code and performs the static analysis, and link the DiscoPoP runtime library. When you run the resulting program, the runtime writes the profiling data. You use the wrappers instead of your normal compiler, with your normal arguments.

## What the wrappers do
`discopop_cc` and `discopop_cxx` are small launchers for the scripts `CC_wrapper.sh` and `CXX_wrapper.sh`, which are installed next to the pass (`LLVMDiscoPoP.so`) and the runtime (`libDiscoPoP_RT.a`) in the directory `discopop-profiler.libs` of the virtual environment's `site-packages`. A call `discopop_cxx <arguments>`

1. selects the compiler: the first of `clang-22`, `clang-21`, `clang-20` and `clang-19` found on the `PATH` (with the matching `clang++-<N>` for C++), otherwise a plain `clang` / `clang++`; on macOS also the Homebrew `llvm@<N>` installations. The wrapper stops with an error if no clang 19 to 22 is found;
2. runs the compiler with your `<arguments>` and the additional flags `-g -O0 -fno-discard-value-names -fPIC`, loads the pass (`-fpass-plugin`), and links `libDiscoPoP_RT.a` and `pthread`. Optimization is therefore always off;
3. runs the compiler a second time with `-fsyntax-only -Xclang -ast-dump=json` and appends the AST of your project's sources (filtered to the files below the project root) to `.discopop/profiler/ast_dump.json`. The Explorer uses it for the pattern detection.

The `.discopop` directory is the one given by [`DOT_DISCOPOP`](../setup/environment_variables.md), by default `.discopop` in the current directory. Functions of library code are only skipped if `DP_PROJECT_ROOT_DIR` is set; see [Environment variables and runtime settings](../setup/environment_variables.md) for these and the other variables that influence the wrappers and the runtime.

{: .note }
The profiler must be installed without `-e` (`pip install ./profiler`): the wrappers locate the pass and the runtime relative to their own location, and refuse to run from the source tree.

## Usage
### A single file
```bash
cd <project directory>
discopop_cxx example.cpp -o a.out
./a.out
```

The compilation creates `.discopop/FileMapping.txt` and the static analysis results in `.discopop/profiler`. Running `./a.out` completes the profiling data in the same directory. Run the program from the project directory, or set `DOT_DISCOPOP` so that it finds the `.discopop` directory. Afterwards, continue with the [Explorer](Explorer.md).

### Makefile projects
Pass the wrappers as compilers:

```bash
make CC=discopop_cc CXX=discopop_cxx
```

Use the wrappers for compiling and linking. Build your project from a clean state and with the same wrappers for all files, so that the profiling data covers every source file.

<!-- UNVERIFIED: the Makefile and CMake invocations were not run on a real project; only the single file example was. -->
### CMake projects
```bash
mkdir build && cd build
cmake -DCMAKE_C_COMPILER=discopop_cc -DCMAKE_CXX_COMPILER=discopop_cxx ..
make
```

### Through the project manager
The `dp` mode of the [project manager](Project_manager.md) sets `CC=discopop_cc` and `CXX=discopop_cxx` for your build script, so a script that uses `$CC` and `$CXX` is instrumented without further changes.

## Further scripts in the package
The directory `discopop-profiler.libs` contains further scripts that are not installed as commands. You can call them by their full path:

| Script | Purpose |
|---|---|
| `LINKER_wrapper.sh` | Links objects with the DiscoPoP runtime (`-lDiscoPoP_RT`), without instrumenting |
| `MPI_CC_wrapper.sh`, `MPI_CXX_wrapper.sh`, `MPI_LINKER_wrapper.sh` | Variants for MPI programs; need the MPI compiler wrappers on the `PATH` (compile with `MPI_CC_wrapper.sh` / `MPI_CXX_wrapper.sh`, link with `MPI_LINKER_wrapper.sh`) |
| `CMAKE_wrapper.sh` | Calls `cmake` with `CC_wrapper.sh` / `CXX_wrapper.sh` as compilers |
| `filter_ast_dump.py` | Used by the wrappers to reduce the AST: keeps the declarations of the files in `FileMapping.txt` (below the project directory without one) and drops the type nodes |
| `dump_ast.sh` | Sourced by `CC_wrapper.sh` and `CXX_wrapper.sh`: writes the AST of a translation unit, with the AST export plugin if there is one, otherwise by filtering clang's complete dump |
| `DiscoPoPASTExport-<clang version>.so` | The AST export plugin (only built if the Clang development files are installed, see below) |
| `dp-fmap` | Creates a [file mapping](../data/Filemapping.md) by hand. This is not necessary anymore since the instrumentation creates `FileMapping.txt`. |

### AST export plugin
The explorer reads `ast_dump.json`, but only the nodes of the files in `FileMapping.txt`. Clang's complete JSON dump contains every declaration of the included headers as well, which is tens of GB for a single translation unit of a template heavy project. If the Clang development files (`libclang-<version>-dev` on Debian and Ubuntu) were installed when the profiler was built, the build also creates the clang plugin `DiscoPoPASTExport-<clang version>.so`. The wrappers then let clang write only the declarations of the mapped files (a few seconds instead of minutes, and a few hundred MB instead of tens of GB per translation unit). Without the plugin, or if it fails, the wrappers filter the complete dump while it is written: the result is the same, but slower and needing more disk throughput.

- `DP_AST_NO_PLUGIN=1` uses the filtered dump even if the plugin exists.
- The declarations of the excluded directories (`DP_PROJECT_EXCLUDE_DIRS`, see [Environment variables](../setup/environment_variables.md)) are left out by both, also before a `FileMapping.txt` exists. A dependency fetched below the project directory (`build/_deps`) should be excluded: otherwise it is project code, instrumented and kept in the AST.
- `filter_ast_dump.py` reports on stderr which files it keeps, how it is doing (every 10 s on long runs) and, when done, how much it read, wrote and dropped, so each translation unit adds two lines to the build log; `DP_AST_QUIET=1` silences them.
- `-DDP_AST_EXPORT=OFF` (or `REQUIRED`) at build time never builds the plugin (or fails if it cannot be built).
- The plugin only runs with the clang of the version it was built for (the version is part of its file name).
- Namespaces are not part of the exported AST, their declarations are, and neither are type aliases and the documentation comments of declarations; the explorer does not use them.

<!-- UNVERIFIED: the MPI wrappers and LINKER_wrapper.sh were not run. -->

## Output
- `.discopop/FileMapping.txt`, `.discopop/profiler/*`: see [Profiling and instrumentation output](../data/Profiling_and_instrumentation_output.md) and [File mapping](../data/Filemapping.md).
