---
layout: default
title: Scripts and wrappers
parent: Tools
nav_order: 9
---

# Scripts and wrappers
Several scripts, utilities and compiler wrappers are located in the `discopop/build/scripts` directory.
The following sections will give a brief overview over the individual scripts and their purpose.

## Compiler wrappers
To simplify the application of DiscoPoP's static analysis and code instrumentation, we provide wrapper scripts around the `clang`(CC_wrapper.sh) and `clang++`(CXX_wrapper.sh) compilers as well as a wrapper around `cmake`(CMAKE_wrapper.sh).
These scripts can be used instead of the original versions to build the instrumented version of the sequential program.
For examples how to use these wrappers, please refer to the [examples](../examples/examples.md).

## Hotspot Detection compiler wrappers
The `discopop-hotspot-detection` package provides analogous compiler wrappers for runtime hotspot profiling:

- **`discopop_hotspot_cc`** — wraps `clang` to instrument C source files
- **`discopop_hotspot_cxx`** — wraps `clang++` to instrument C++ source files

These wrappers inject the `LLVMHotspotDetection` pass during compilation and link the `HotspotDetection_RT` runtime library, which measures the time spent in each code region across multiple runs.

For CMake-based projects, pass the wrappers as the compiler directly:
```
cmake -DCMAKE_C_COMPILER_WORKS=1 \
      -DCMAKE_CXX_COMPILER_WORKS=1 \
      -DCMAKE_C_COMPILER=discopop_hotspot_cc \
      -DCMAKE_CXX_COMPILER=discopop_hotspot_cxx \
      ..
```

After running the instrumented binary (multiple times with varying inputs), analyze the collected data with:
```
cd .discopop
discopop_hotspot_analyzer
```

For more details, refer to the [Hotspot-Detection README](../../hotspot_detection/README.md).

## Utilities
### dp-fmap script
This script creates a [filemapping](../data/Filemapping.md) file. However, it is not necessary anymore since the filemapping is created during the static analysis. Using the script to create a filemapping manually is still possible, although not recommended.

## Developer utilities
Developer utilities are located inside the `dev` folder.
### check-license.sh
Checks if all files in the project start with the appropriate license header.
### create-release.sh
Original utility to create or prepare an new DiscoPoP release. It is not recommended to use this script to prepare a release. Follow the steps in [how to contribute](../How_to_contribute.md) instead.
### check-commit-msg.py
This script is part of the pre-commit checks described in [how to contribute](../How_to_contribute.md).
It validates commit messages before commiting and ensures a well-structured and uniform formatting of git commit messages.
