# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

cmake_minimum_required(VERSION 3.28.0)

# Select clang as compiler before project() so CMake uses it for all targets.
# Only set if not already overridden on the command line or via environment.
if(NOT DEFINED CMAKE_C_COMPILER)
    find_program(CMAKE_C_COMPILER NAMES clang-22 clang-21 clang-20 clang-19 clang)
endif()
if(NOT DEFINED CMAKE_CXX_COMPILER)
    find_program(CMAKE_CXX_COMPILER NAMES clang++-22 clang++-21 clang++-20 clang++-19 clang++)
endif()

project(HotspotDetection)

set(CMAKE_CXX_STANDARD 17)

if (POLICY CMP0077)
	cmake_policy(SET CMP0077 NEW)
endif()

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
    foreach(_major 22 21 20 19)
        foreach(_minor RANGE 0 9)
            if(NOT LLVM_FOUND)
                find_package(LLVM "${_major}.${_minor}" CONFIG QUIET)
            endif()
        endforeach()
    endforeach()
    if(NOT LLVM_FOUND)
        message(FATAL_ERROR "No supported LLVM Version found. Versions 19–22 are supported. If a supported LLVM Version is installed, consider specifying the -DLLVM_DIST_PATH flag.")
    endif()
endif()

# Derive the clang executable name from the detected LLVM major version
string(REGEX MATCH "^([0-9]+)" LLVM_MAJOR_VERSION "${LLVM_PACKAGE_VERSION}")
find_program(CLANG_EXECUTABLE NAMES clang-${LLVM_MAJOR_VERSION} clang)
if(NOT CLANG_EXECUTABLE)
    message(FATAL_ERROR "clang-${LLVM_MAJOR_VERSION} is required but was not found. Please install clang-${LLVM_MAJOR_VERSION}.")
endif()
message(STATUS "Found clang: ${CLANG_EXECUTABLE}")

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

add_subdirectory(HotspotDetection)

add_subdirectory(rtlib)

add_subdirectory(scripts)
