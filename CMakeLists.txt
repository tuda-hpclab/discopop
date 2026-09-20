# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

cmake_minimum_required(VERSION 3.28.0)
project(DiscoPoP)

set(CMAKE_CXX_STANDARD 17)

if (POLICY CMP0077)
	cmake_policy(SET CMP0077 NEW)
endif()

# Print DiscoPoP version to be installed
file(READ ${CMAKE_CURRENT_LIST_DIR}/library/discopop_library/global_data/version/VERSION DiscoPoP_VERSION)
string(REGEX REPLACE "\n$" "" DiscoPoP_VERSION "${DiscoPoP_VERSION}")
message(STATUS "DiscoPoP version: ${DiscoPoP_VERSION}")

if(NOT ${LLVM_DIST_PATH} STREQUAL "")
    # manually specify path to LLVM installation, used for builds from source
    if(NOT EXISTS ${LLVM_DIST_PATH})
        message(FATAL_ERROR "The specified LLVM_DIST_PATH=${LLVM_DIST_PATH} does not exist!")
    endif()
    set(LLVM_DIR ${LLVM_DIST_PATH}/lib/cmake/llvm)
    find_package(LLVM PATHS ${LLVM_DIR})
elseif(NOT ${USE_LLVM_VERSION} STREQUAL "")
    # search for specified llvm version
    find_package(LLVM ${USE_LLVM_VERSION} REQUIRED)
else()
    # search for any supported LLVM major version (19–22), any minor version
    foreach(_major 19 20 21 22)
        foreach(_minor RANGE 0 9)
            if(NOT LLVM_FOUND)
                find_package(LLVM "${_major}.${_minor}" CONFIG QUIET)
            endif()
        endforeach()
    endforeach()
    if(NOT LLVM_FOUND)
        message(FATAL_ERROR "\
No supported LLVM Version found. \
Versions 19–22 are supported. \
If a supported LLVM Version is installed, consider specifying the -DLLVM_DIST_PATH flag. \
For more information, please refer to https://discopop-project.github.io/discopop/setup/discopop. \
")
    endif()
endif()

find_package(Boost REQUIRED)

message(STATUS "Using LLVM version ${LLVM_PACKAGE_VERSION}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")
list(APPEND CMAKE_MODULE_PATH ${LLVM_CMAKE_DIR})

set(LLVM_RUNTIME_OUTPUT_INTDIR ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_CFG_INTDIR}/bin)
set(LLVM_LIBRARY_OUTPUT_INTDIR ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_CFG_INTDIR}/libi)

list(APPEND CMAKE_MODULE_PATH "${LLVM_CMAKE_DIR}")
include(HandleLLVMOptions)
include(AddLLVM)

add_definitions(${LLVM_DEFINITIONS})
include_directories(${LLVM_INCLUDE_DIRS})

# Decided before profiler/ is configured: the runtime library builds an extra variant of itself
# for the callback benchmarks when the unit tests are requested, see profiler/rtlib/CMakeLists.txt.
if( NOT DEFINED DP_BUILD_UNITTESTS)
    set(DP_BUILD_UNITTESTS 0)
endif()

add_subdirectory(profiler)

add_subdirectory(scripts)

# build unittests and performance benchmarks, if requested
if(${DP_BUILD_UNITTESTS} STREQUAL "1")
    add_subdirectory(test/unit_tests)
    add_subdirectory(test/pass_unit_tests)
    add_subdirectory(benchmark)
endif()

##### DEPRECATED #####
# save build configuration to build/build_config.txt
file(REMOVE "${DiscoPoP_BINARY_DIR}/build_config.txt")
file(TOUCH "${DiscoPoP_BINARY_DIR}/build_config.txt")
file(APPEND "${DiscoPoP_BINARY_DIR}/build_config.txt" "DP_BUILD=${DiscoPoP_BINARY_DIR}\n")
file(APPEND "${DiscoPoP_BINARY_DIR}/build_config.txt" "DP_SOURCE=${DiscoPoP_SOURCE_DIR}\n")
file(APPEND "${DiscoPoP_BINARY_DIR}/build_config.txt" "LLVM_BIN_DIR=${LLVM_TOOLS_BINARY_DIR}\n")
file(APPEND "${DiscoPoP_BINARY_DIR}/build_config.txt" "PYTHON_EXECUTABLE=${Python3_EXECUTABLE}\n")
##### END OF DEPRECATED #####

# save build_config.py to discopop_library/ConfigProvider/assets for easy accessibility and global use
file(REMOVE "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py")
file(TOUCH "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_VERSION=\"${DiscoPoP_VERSION}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_BUILD=\"${DiscoPoP_BINARY_DIR}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_SOURCE=\"${DiscoPoP_SOURCE_DIR}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "LLVM_BIN_DIR=\"${LLVM_TOOLS_BINARY_DIR}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "PYTHON_EXECUTABLE=\"${Python3_EXECUTABLE}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_HYBRID_PROFILING=\"${DP_HYBRID_PROFILING}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_PTHREAD_COMPATIBILITY_MODE=\"${DP_PTHREAD_COMPATIBILITY_MODE}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_RTLIB_VERBOSE=\"${DP_RTLIB_VERBOSE}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_NUM_WORKERS=\"${DP_NUM_WORKERS}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_INTERNAL_TIMER=\"${DP_INTERNAL_TIMER}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_CALLTREE_PROFILING=\"${DP_CALLTREE_PROFILING}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_CALLTREE_PROFILING_METADATA_CUTOFF=\"${DP_CALLTREE_PROFILING_METADATA_CUTOFF}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY=\"${DP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_MEMORY_REGION_DEALIASING=\"${DP_MEMORY_REGION_DEALIASING}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_BRANCH_TRACKING=\"${DP_BRANCH_TRACKING}\"\n")
file(APPEND "${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py" "DP_BUILD_UNITTESTS=\"${DP_BUILD_UNITTESTS}\"\n")


if(NOT ${IS_DEB_INSTALL} STREQUAL "")
    message(STATUS "performing installation from .deb package")
else()
    # print DiscoPoP configuration
    file(READ ${DiscoPoP_SOURCE_DIR}/library/discopop_library/ConfigProvider/assets/build_config.py DiscoPoP_CONFIGURATION)
    string(REGEX REPLACE "\n$" "" DiscoPoP_CONFIGURATION "${DiscoPoP_CONFIGURATION}")
    string(REGEX REPLACE "\n" "\n    " DiscoPoP_CONFIGURATION "${DiscoPoP_CONFIGURATION}")
    message(STATUS "DiscoPoP configuration:\n    ${DiscoPoP_CONFIGURATION}")

    # install DiscoPoP python modules
    find_package(Python3 REQUIRED COMPONENTS Interpreter)

    # setup DiscoPoP venv
    if(NOT ${USE_VENV} STREQUAL "")
        message(STATUS "Setting up existing python venv: ${USE_VENV}")
        set(Python3_VENV_EXECUTABLE ${USE_VENV}/bin/python3)
    else()
        message(STATUS "Setting up default DiscoPoP python venv: ${DiscoPoP_SOURCE_DIR}/venv")
        execute_process(
            COMMAND ${Python3_EXECUTABLE} -m venv ${DiscoPoP_SOURCE_DIR}/venv
        )
        set(Python3_VENV_EXECUTABLE ${DiscoPoP_SOURCE_DIR}/venv/bin/python3)
    endif()

    # check if python tkinter module is available
    execute_process(
        COMMAND ${Python3_VENV_EXECUTABLE} -c "import tkinter"
        RESULT_VARIABLE TKINTER_AVAILABLE_EXIT_CODE
    )
    if(${TKINTER_AVAILABLE_EXIT_CODE})
        message(WARNING "Python module 'tkinter' not found. Please install the 'python3-tk' package via a package manager.")
    endif()




endif()



### SETUP PYTHON MODULES ####

set(DP_LOCAL_BIN_DIR "$ENV{HOME}/.local/bin")

add_custom_target(
    python_modules
    COMMENT "Installing DiscoPoP python modules"
    DEPENDS install_python_modules reset_symlinks setup_symlinks
)


add_custom_target(
    install_python_modules
    COMMENT "Installing python modules and dependencies"
    COMMAND ${Python3_VENV_EXECUTABLE} -m pip install -e ${DiscoPoP_SOURCE_DIR}
)

add_custom_target(
    reset_symlinks
    DEPENDS install_python_modules
    COMMENT "Resetting existing DiscoPoP symlinks to python executables"
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_auto_tuner
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_config_provider
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_explorer
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_optimizer
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_patch_applicator
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_patch_generator
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_sanity_checker
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_project_manager
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_configuration_manager
    COMMAND rm -f ${DP_LOCAL_BIN_DIR}/discopop_dependency_comparator
)

add_custom_target(
    setup_symlinks
    DEPENDS reset_symlinks
    COMMENT "Creating symlinks for DiscoPoP python executables"
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_auto_tuner ${DP_LOCAL_BIN_DIR}/discopop_auto_tuner
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_config_provider ${DP_LOCAL_BIN_DIR}/discopop_config_provider
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_explorer ${DP_LOCAL_BIN_DIR}/discopop_explorer
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_optimizer ${DP_LOCAL_BIN_DIR}/discopop_optimizer
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_patch_applicator ${DP_LOCAL_BIN_DIR}/discopop_patch_applicator
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_patch_generator ${DP_LOCAL_BIN_DIR}/discopop_patch_generator
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_sanity_checker ${DP_LOCAL_BIN_DIR}/discopop_sanity_checker
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_preprocessor ${DP_LOCAL_BIN_DIR}/discopop_preprocessor
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_project_manager ${DP_LOCAL_BIN_DIR}/discopop_project_manager
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_configuration_manager ${DP_LOCAL_BIN_DIR}/discopop_configuration_manager
    COMMAND ln -sf ${DiscoPoP_SOURCE_DIR}/venv/bin/discopop_dependency_comparator ${DP_LOCAL_BIN_DIR}/discopop_dependency_comparator
)
