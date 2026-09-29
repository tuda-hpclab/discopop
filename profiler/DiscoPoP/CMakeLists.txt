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

add_llvm_library(LLVMDiscoPoP MODULE
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

target_link_libraries(LLVMDiscoPoP PRIVATE OpenMP::OpenMP_CXX)

# forward compiler flags
if(DEFINED DP_HYBRID_PROFILING)
        target_compile_definitions(LLVMDiscoPoP PUBLIC DP_HYBRID_PROFILING=${DP_HYBRID_PROFILING})
        if(${DP_HYBRID_PROFILING} EQUAL 0)
                message(STATUS "WARNING: DiscoPoP configuration: DP_HYBRID_PROFILING disabled. Reduces profiling speed.")
        endif()
else()
        target_compile_definitions(LLVMDiscoPoP PUBLIC DP_HYBRID_PROFILING=1)
endif()

if(DEFINED DP_BRANCH_TRACKING)
        target_compile_definitions(LLVMDiscoPoP PUBLIC DP_BRANCH_TRACKING=${DP_BRANCH_TRACKING})
        if(NOT ${DP_BRANCH_TRACKING} EQUAL 0)
                message(STATUS "WARNING: DiscoPoP configuration: DP_BRANCH_TRACKING enabled. Reduces profiling speed.")
        endif()
else()
        target_compile_definitions(LLVMDiscoPoP PUBLIC DP_BRANCH_TRACKING=0)
endif()
# end of compiler flags

install(TARGETS LLVMDiscoPoP LIBRARY DESTINATION discopop-profiler.libs)
