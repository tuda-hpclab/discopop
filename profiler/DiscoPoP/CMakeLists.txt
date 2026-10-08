# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

include_directories(
        ../share/include
)

# The pass sources are compiled once into an OBJECT library, which is consumed both by the
# LLVMDiscoPoP plugin below and by the DiscoPoP_Pass_UT unit test binary (test/pass_unit_tests).
# A MODULE library cannot be linked against, so the tests would otherwise have to compile the
# same sources a second time -- and would silently drift apart from the compile definitions set
# further down in this file.
add_library(DiscoPoP_PassObjects OBJECT
        DiscoPoP.cpp
        ../share/lib/DPUtils.cpp

        Globals.cpp
        RegisterPass.cpp

        instrumentation/low_level/instrumentAlloca.cpp
        instrumentation/low_level/instrumentNewOrMalloc.cpp
        instrumentation/low_level/instrumentRealloc.cpp
        instrumentation/low_level/instrumentCalloc.cpp
        instrumentation/low_level/instrumentPosixMemalign.cpp
        instrumentation/low_level/instrumentDeleteOrFree.cpp
        instrumentation/low_level/instrumentLoad.cpp
        instrumentation/low_level/instrumentStore.cpp
        instrumentation/low_level/instrumentFuncEntry.cpp
        instrumentation/low_level/instrumentLoopEntry.cpp
        instrumentation/low_level/instrumentLoopExit.cpp
        instrumentation/low_level/insertDPFinalize.cpp

        instrumentation/high_level/instrumentFunction.cpp
        instrumentation/high_level/instrumentLoop.cpp
        instrumentation/high_level/instrumentModule.cpp

        instrumentation/taken_branches/createInstrumentation.cpp

        initialization/initializeCUIDCounter.cpp
        initialization/initializeBBDepCounter.cpp
        initialization/initializeInstructionIDCounter.cpp
        initialization/initializeCallpathStateIDCounter.cpp

        llvm_hooks/doInitialization.cpp
        llvm_hooks/doFinalization.cpp
        llvm_hooks/runOnBasicBlock.cpp
        llvm_hooks/runOnFunction.cpp
        llvm_hooks/runOnModule.cpp

        dp_reduction/get_load_instr.cpp
        dp_reduction/find_reduction_instr.cpp
        dp_reduction/determine_variable_name.cpp
        dp_reduction/determine_variable_type.cpp
        dp_reduction/CFA.cpp
        dp_reduction/get_var.cpp
        dp_reduction/get_reduction_instr.cpp
        dp_reduction/utils.cpp
        dp_reduction/insert_functions.cpp

        utils/simple.cpp
        utils/output.cpp
        utils/CFA.cpp
        utils/variables/names.cpp
        utils/variables/types.cpp
        utils/variables/defLine.cpp

        static_analysis/createCUs.cpp
        static_analysis/fillCUVariables.cpp
        static_analysis/populateGlobalVariablesSet.cpp
        static_analysis/instruction_id_assignment.cpp
        static_analysis/calltree_construction.cpp
        static_analysis/path_enumeration.cpp
        static_analysis/StaticCalltree.cpp
        static_analysis/StaticCallPathTree.cpp

        hybrid_analysis/InstructionCFG.cpp
        hybrid_analysis/InstructionDG.cpp
        )

# the plugin is built as a shared object, so the objects have to be position independent
set_target_properties(DiscoPoP_PassObjects PROPERTIES POSITION_INDEPENDENT_CODE ON)

# absolute paths, so that consumers outside of this directory (the unit tests) inherit them
target_include_directories(DiscoPoP_PassObjects PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../share/include
        )

target_link_libraries(DiscoPoP_PassObjects PUBLIC OpenMP::OpenMP_CXX)

# forward compiler flags
# PUBLIC on the object library, so the unit tests compile against the same configuration
if(DEFINED DP_HYBRID_PROFILING)
        target_compile_definitions(DiscoPoP_PassObjects PUBLIC DP_HYBRID_PROFILING=${DP_HYBRID_PROFILING})
        if(${DP_HYBRID_PROFILING} EQUAL 0)
                message(STATUS "WARNING: DiscoPoP configuration: DP_HYBRID_PROFILING disabled. Reduces profiling speed.")
        endif()
else()
        target_compile_definitions(DiscoPoP_PassObjects PUBLIC DP_HYBRID_PROFILING=1)
endif()

if(DEFINED DP_BRANCH_TRACKING)
        target_compile_definitions(DiscoPoP_PassObjects PUBLIC DP_BRANCH_TRACKING=${DP_BRANCH_TRACKING})
        if(NOT ${DP_BRANCH_TRACKING} EQUAL 0)
                message(STATUS "WARNING: DiscoPoP configuration: DP_BRANCH_TRACKING enabled. Reduces profiling speed.")
        endif()
else()
        target_compile_definitions(DiscoPoP_PassObjects PUBLIC DP_BRANCH_TRACKING=0)
endif()
# end of compiler flags

# PARTIAL_SOURCES_INTENDED: LLVM otherwise insists that the target in this directory lists every
# .cpp file next to it. Here the sources belong to DiscoPoP_PassObjects and reach the plugin as
# compiled objects.
add_llvm_library(LLVMDiscoPoP MODULE
        PARTIAL_SOURCES_INTENDED
        $<TARGET_OBJECTS:DiscoPoP_PassObjects>
        )

# NOTE: the objects arrive via $<TARGET_OBJECTS:...> above. Linking the object library here as
# well would add every object a second time and break the link with duplicate symbols.
target_link_libraries(LLVMDiscoPoP PRIVATE OpenMP::OpenMP_CXX)

install(TARGETS LLVMDiscoPoP LIBRARY DESTINATION discopop-profiler.libs)
