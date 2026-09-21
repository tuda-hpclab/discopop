# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

#include_directories(
#    ../share/include
#    )

# Runtime library sources and build flags.
#
# Split in two because the benchmark variants below recompile one half and reuse the other. The
# callback half is every translation unit whose generated code depends on callback_body_enabled(),
# i.e. everything that includes callback_scope.hpp; the shared half compiles to the same objects
# in every variant. Keep a new source on the right side of that line: a callback file that ends up
# in the shared list would silently be built once and shared by all variants.
set(DiscoPoP_CALLBACK_SOURCES
        injected_functions/dp_alloca.cpp
        injected_functions/dp_call.cpp
        injected_functions/dp_decl.cpp
        injected_functions/dp_delete.cpp
        injected_functions/dp_func_entry.cpp
        injected_functions/dp_func_exit.cpp
        injected_functions/dp_incr_taken_branch_counter.cpp
        injected_functions/dp_loop_entry.cpp
        injected_functions/dp_loop_exit.cpp
        injected_functions/dp_loop_incr.cpp
        injected_functions/dp_new.cpp
        injected_functions/dp_read.cpp
        injected_functions/dp_report_bb.cpp
        injected_functions/dp_report_bb_pair.cpp
        injected_functions/dp_write.cpp

        lifecycle/runtime_shutdown.cpp
        )

set(DiscoPoP_SHARED_SOURCES
        output_paths.cpp
        runtimeFunctions.cpp
        runtimeFunctionsGlobals.cpp

        memory/MemoryManager.cpp
        memory/Signature.cpp

        calltree/CallTreeNode.cpp
        calltree/CallTree.cpp
        calltree/CallTreeGlobals.cpp
        calltree/DependencyMetadata.cpp
        calltree/MetaDataQueueElement.cpp
        calltree/utils.cpp

        injected_functions/dp_add_bb_deps.cpp
        injected_functions/dp_finalize.cpp
        injected_functions/dp_loop_output.cpp
        injected_functions/dp_taken_branch_counter_output.cpp

        hybrid_analysis/bb_deps.cpp

        lifecycle/runtime_startup.cpp

        static_callstate_transitions/CallState.cpp
        static_callstate_transitions/CallStateGraph.cpp
        static_callstate_transitions/utils.cpp
        )

set(DiscoPoP_SOURCES ${DiscoPoP_SHARED_SOURCES} ${DiscoPoP_CALLBACK_SOURCES})

set(CMAKE_CXX_FLAGS
        "-O2 -std=c++17 -pthread -fno-rtti -fPIE -fPIC")
# DISCOPOP_BOOST_INCLUDE_DIR is set by the top-level CMakeLists.
# Appending here because set(CMAKE_CXX_FLAGS) above replaces all flags and
# target_include_directories / include_directories are not reliable after it.
if(DISCOPOP_BOOST_INCLUDE_DIR)
    string(APPEND CMAKE_CXX_FLAGS " -I${DISCOPOP_BOOST_INCLUDE_DIR}")
endif()

# add_custom_target(DiscoPoP)

add_library(DiscoPoP_RT STATIC
        ${DiscoPoP_SOURCES})

target_link_libraries(DiscoPoP_RT PRIVATE Boost::headers)

# The runtime again, once with none of the callback bodies and once per callback with only that
# one (see callback_body_enabled() in callback_scope.hpp). Together they take the cost of
# instrumentation apart: what the added calls cost by themselves, and what each callback's body
# adds on top of them.
#
# Built here rather than next to the benchmarks that use them, because CMAKE_CXX_FLAGS above
# applies to this directory only and libraries that are compared have to be compiled identically.
# None of them is installed or linked by anything the profiler ships: they export the same symbols
# as DiscoPoP_RT, so an instrumented program linked against one of them would profile partially or
# not at all.
if(DP_BUILD_UNITTESTS STREQUAL "1")
        # the half that does not depend on which callbacks are switched on, compiled once and
        # reused by every variant -- which is what keeps sixteen extra runtime libraries cheap
        add_library(DiscoPoP_RT_BenchmarkShared OBJECT ${DiscoPoP_SHARED_SOURCES})
        target_link_libraries(DiscoPoP_RT_BenchmarkShared PRIVATE Boost::headers)

        # the CallbackId enumerators from callback_scope.hpp. The library name carries the
        # enumerator so that a driver can go from one to the other without a table.
        set(DiscoPoP_RT_BENCHMARK_CALLBACKS
                ALLOCA CALL DECL DELETE FUNC_ENTRY FUNC_EXIT INCR_TAKEN_BRANCH_COUNTER
                LOOP_ENTRY LOOP_EXIT LOOP_INCR NEW READ REPORT_BB REPORT_BB_PAIR WRITE)

        add_library(DiscoPoP_RT_EmptyCallbacks STATIC
                ${DiscoPoP_CALLBACK_SOURCES}
                $<TARGET_OBJECTS:DiscoPoP_RT_BenchmarkShared>)
        target_compile_definitions(DiscoPoP_RT_EmptyCallbacks PUBLIC DP_BENCHMARK_EMPTY_CALLBACKS)
        set(DiscoPoP_RT_BENCHMARK_TARGETS DiscoPoP_RT_BenchmarkShared DiscoPoP_RT_EmptyCallbacks)

        foreach(dp_callback IN LISTS DiscoPoP_RT_BENCHMARK_CALLBACKS)
                add_library(DiscoPoP_RT_Only_${dp_callback} STATIC
                        ${DiscoPoP_CALLBACK_SOURCES}
                        $<TARGET_OBJECTS:DiscoPoP_RT_BenchmarkShared>)
                target_compile_definitions(DiscoPoP_RT_Only_${dp_callback} PUBLIC
                        DP_BENCHMARK_ONLY_CALLBACK=${dp_callback})
                list(APPEND DiscoPoP_RT_BENCHMARK_TARGETS DiscoPoP_RT_Only_${dp_callback})
        endforeach()

        foreach(dp_variant IN LISTS DiscoPoP_RT_BENCHMARK_TARGETS)
                target_link_libraries(${dp_variant} PRIVATE Boost::headers)
        endforeach()

        # one target to ask for all of them, so a driver does not have to know the list
        add_custom_target(DiscoPoP_RT_BenchmarkVariants DEPENDS ${DiscoPoP_RT_BENCHMARK_TARGETS})
endif()

# forward compiler flags
if(DEFINED DP_PTHREAD_COMPATIBILITY_MODE)
        if(NOT ${DP_PTHREAD_COMPATIBILITY_MODE} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_PTHREAD_COMPATIBILITY_MODE=${DP_PTHREAD_COMPATIBILITY_MODE})
                message(STATUS "WARNING: DiscoPoP configuration: DP_PTHREAD_COMPATIBILITY_MODE enabled. Reduces profiling speed.")
        endif()
endif()

if(DEFINED DP_RTLIB_VERBOSE)
        if(NOT ${DP_RTLIB_VERBOSE} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_RTLIB_VERBOSE=${DP_RTLIB_VERBOSE})
        endif()
endif()

if(DEFINED DP_NUM_WORKERS)
        target_compile_definitions(DiscoPoP_RT PUBLIC DP_NUM_WORKERS=${DP_NUM_WORKERS})
endif()

if(DEFINED DP_INTERNAL_TIMER)
        if(NOT ${DP_INTERNAL_TIMER} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_INTERNAL_TIMER=${DP_INTERNAL_TIMER})
                message(STATUS "WARNING: DiscoPoP configuration: DP_INTERNAL_TIMER enabled. Debug setting. Reduces profiling speed.")
        endif()
endif()

if(DEFINED DP_STACK_ACCESS_DETECTION)
        if(NOT ${DP_STACK_ACCESS_DETECTION} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_STACK_ACCESS_DETECTION=${DP_STACK_ACCESS_DETECTION})
                message(STATUS "WARNING: DiscoPoP configuration: DP_STACK_ACCESS_DETECTION enabled. Reduces profiling speed.")
        endif()
endif()

if(DEFINED DP_CALLTREE_PROFILING)
        if(NOT ${DP_CALLTREE_PROFILING} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_CALLTREE_PROFILING=${DP_CALLTREE_PROFILING})
                message(STATUS "WARNING: DiscoPoP configuration: DP_CALLTREE_PROFILING enabled. Reduces profiling speed.")
        endif()
endif()

if(DEFINED DP_CALLTREE_PROFILING_METADATA_CUTOFF)
        target_compile_definitions(DiscoPoP_RT PUBLIC DP_CALLTREE_PROFILING_METADATA_CUTOFF=${DP_CALLTREE_PROFILING_METADATA_CUTOFF})
        message(STATUS "WARNING: DiscoPoP configuration: DP_CALLTREE_PROFILING_METADATA_CUTOFF enabled. Incomplete dependency metadata possible.")
else()
        target_compile_definitions(DiscoPoP_RT PUBLIC DP_CALLTREE_PROFILING_METADATA_CUTOFF=50)
        message(STATUS "WARNING: DiscoPoP configuration: DP_CALLTREE_PROFILING_METADATA_CUTOFF set to default value: 50.")
endif()

if(DEFINED DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY)
        target_compile_definitions(DiscoPoP_RT PUBLIC DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY=${DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY})
        message(STATUS "WARNING: DiscoPoP configuration: DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY set to ${DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY} * 0.1% .")
else()
        target_compile_definitions(DiscoPoP_RT PUBLIC DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY=1)
        message(STATUS "WARNING: DiscoPoP configuration: DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY set to default value: 0.1%")
endif()



if(DEFINED DP_MEMORY_REGION_DEALIASING)
        if(NOT ${DP_MEMORY_REGION_DEALIASING} EQUAL 0)
                target_compile_definitions(DiscoPoP_RT PUBLIC DP_MEMORY_REGION_DEALIASING=${DP_MEMORY_REGION_DEALIASING})
                message(STATUS "WARNING: DiscoPoP configuration: DP_MEMORY_REGION_DEALIASING enabled. Reduces profiling speed.")
        endif()
endif()


# end of compiler flags

# The benchmark variants have to see exactly the configuration above, or their measurements would
# describe a runtime nobody builds. Copied off the target rather than repeated, so that an option
# added to the list above cannot be forgotten here.
if(DiscoPoP_RT_BENCHMARK_TARGETS)
        get_target_property(DiscoPoP_RT_FORWARDED_DEFINITIONS DiscoPoP_RT INTERFACE_COMPILE_DEFINITIONS)
        if(DiscoPoP_RT_FORWARDED_DEFINITIONS)
                foreach(dp_variant IN LISTS DiscoPoP_RT_BENCHMARK_TARGETS)
                        target_compile_definitions(${dp_variant} PUBLIC ${DiscoPoP_RT_FORWARDED_DEFINITIONS})
                endforeach()
        endif()
endif()

install(TARGETS DiscoPoP_RT ARCHIVE DESTINATION discopop-profiler.libs)
