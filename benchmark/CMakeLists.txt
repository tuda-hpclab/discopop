# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


include(FetchContent)

set(CMAKE_EXPORT_COMPILE_COMMANDS OFF)

set(BENCHMARK_ENABLE_TESTING
        OFF
        CACHE INTERNAL "")
FetchContent_Declare(
        googlebenchmark
        GIT_REPOSITORY https://github.com/google/benchmark.git
        GIT_TAG v1.6.1)

FetchContent_MakeAvailable(googlebenchmark)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

get_target_property(googlebenchmark_includes benchmark
        INTERFACE_INCLUDE_DIRECTORIES)
set_target_properties(benchmark PROPERTIES INTERFACE_SYSTEM_INCLUDE_DIRECTORIES
        "${googlebenchmark_includes}")

add_executable(DiscoPoP_BM)
target_sources(
  DiscoPoP_BM
  PRIVATE 
  benchmarks.cpp
  memory_region_tree/benchmark_memory_region_tree.cpp
  perfect_shadow/benchmark_perfect_shadow.cpp
  scope/benchmark_scope.cpp)

target_include_directories(DiscoPoP_BM PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(DiscoPoP_BM PRIVATE DiscoPoP_RT)
target_link_libraries(DiscoPoP_BM PRIVATE benchmark::benchmark)
set_target_properties(DiscoPoP_BM PROPERTIES CXX_STANDARD 20)
set_target_properties(DiscoPoP_UT PROPERTIES ENABLE_EXPORTS 1)

# The per-callback benchmarks, built twice from the same source: once against the runtime as it
# is shipped, once against the build whose callbacks return before their body (see
# DP_BENCHMARK_EMPTY_CALLBACKS in profiler/rtlib/callback_scope.hpp). Same flags and the same
# benchmark names on both sides, so that run_callback_benchmark.py can subtract them per
# callback and report what the call costs and what the body adds.
foreach(dp_callback_benchmark IN ITEMS DiscoPoP_BM_Callbacks DiscoPoP_BM_Callbacks_Empty)
  add_executable(${dp_callback_benchmark}
    injected_functions/benchmark_injected_functions.cpp)
  target_include_directories(${dp_callback_benchmark} PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
  target_link_libraries(${dp_callback_benchmark} PRIVATE benchmark::benchmark)
  target_link_libraries(${dp_callback_benchmark} PRIVATE Boost::headers)
  set_target_properties(${dp_callback_benchmark} PROPERTIES CXX_STANDARD 20)
endforeach()

target_link_libraries(DiscoPoP_BM_Callbacks PRIVATE DiscoPoP_RT)
target_link_libraries(DiscoPoP_BM_Callbacks_Empty PRIVATE DiscoPoP_RT_EmptyCallbacks)

