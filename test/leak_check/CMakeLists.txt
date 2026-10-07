# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Build for the profiler leak check (scripts/dev/check_profiler_leaks.sh): the profiler exactly as
# `pip install ./profiler` builds it (LLVM pass, runtime library, wrapper scripts), plus the runtime
# library's GoogleTest unit tests, all with one compiler. Configure it with -DDP_SANITIZERS=address.
#
# The root CMakeLists.txt is not used, since configuring it creates a venv in the source tree and rewrites
# library/discopop_library/ConfigProvider/assets/build_config.py. Pass the clang the profiler's wrapper
# scripts use as CMAKE_C_COMPILER / CMAKE_CXX_COMPILER, so the runtime library and the instrumented
# programs use the same sanitizer runtime.

cmake_minimum_required(VERSION 3.28.0)
project(DiscoPoPLeakCheck)

set(CMAKE_CXX_STANDARD 17)

# the leak check only needs the unit test binary, not GoogleTest's install rules
set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../profiler profiler)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../unit_tests unit_tests)
