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
set(DiscoPoP_SOURCES
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
        injected_functions/dp_alloca.cpp
        injected_functions/dp_call.cpp
        injected_functions/dp_decl.cpp
        injected_functions/dp_delete.cpp
        injected_functions/dp_finalize.cpp
        injected_functions/dp_func_entry.cpp
        injected_functions/dp_func_exit.cpp
        injected_functions/dp_incr_taken_branch_counter.cpp
        injected_functions/dp_loop_entry.cpp
        injected_functions/dp_loop_exit.cpp
        injected_functions/dp_loop_incr.cpp
        injected_functions/dp_loop_output.cpp
        injected_functions/dp_new.cpp
        injected_functions/dp_read.cpp
        injected_functions/dp_report_bb.cpp
        injected_functions/dp_report_bb_pair.cpp
        injected_functions/dp_taken_branch_counter_output.cpp
        injected_functions/dp_write.cpp

        static_callstate_transitions/CallState.cpp
        static_callstate_transitions/CallStateGraph.cpp
        static_callstate_transitions/utils.cpp
        )

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

install(TARGETS DiscoPoP_RT ARCHIVE DESTINATION discopop-profiler.libs)

# compile simple-alias-detection
#exec_program(${CMAKE_CURRENT_SOURCE_DIR}/simple-alias-detection/compile.sh
#    ARGS ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}
#)
