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

project(DiscoPopProfiler)

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
	foreach(_major 22 21 20 19 )
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
For more information, please refer to https://tuda-hpclab.github.io/discopop/setup/discopop. \
")
	endif()
endif()

# Derive the clang executable name from the detected LLVM major version
string(REGEX MATCH "^([0-9]+)" LLVM_MAJOR_VERSION "${LLVM_PACKAGE_VERSION}")
find_program(CLANG_EXECUTABLE NAMES clang-${LLVM_MAJOR_VERSION} clang)
if(NOT CLANG_EXECUTABLE)
	message(FATAL_ERROR "clang-${LLVM_MAJOR_VERSION} is required but was not found. Please install clang-${LLVM_MAJOR_VERSION} before building the DiscoPoP profiler.")
endif()
message(STATUS "Found clang: ${CLANG_EXECUTABLE}")

# ── Boost ────────────────────────────────────────────────────────────────────
# Try the system-installed Boost first. If not found, download it via
# FetchContent so the build works without a pre-installed Boost.
find_package(Boost QUIET)

if(Boost_FOUND)
    # Resolve a plain include path for subdirectories that override
    # CMAKE_CXX_FLAGS and therefore can't rely on target-property propagation.
    if(Boost_INCLUDE_DIRS)
        set(DISCOPOP_BOOST_INCLUDE_DIR "${Boost_INCLUDE_DIRS}")
    elseif(APPLE)
        execute_process(
            COMMAND brew --prefix boost
            OUTPUT_VARIABLE _brew_boost_prefix
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET
        )
        if(_brew_boost_prefix)
            set(DISCOPOP_BOOST_INCLUDE_DIR "${_brew_boost_prefix}/include")
        endif()
    endif()
else()
    message(STATUS "Boost not found — downloading via FetchContent")
    include(FetchContent)
    FetchContent_Declare(
        Boost
        URL https://github.com/boostorg/boost/releases/download/boost-1.87.0/boost-1.87.0-cmake.tar.xz
        DOWNLOAD_EXTRACT_TIMESTAMP ON
    )
    set(BOOST_INCLUDE_LIBRARIES container_hash functional)
    set(BOOST_ENABLE_CMAKE ON)
    FetchContent_MakeAvailable(Boost)
    FetchContent_GetProperties(Boost SOURCE_DIR _boost_src_dir)
    # Headers live at the source root (e.g. <boost_src>/boost/...)
    set(DISCOPOP_BOOST_INCLUDE_DIR "${_boost_src_dir}")
endif()

if(DISCOPOP_BOOST_INCLUDE_DIR)
    include_directories("${DISCOPOP_BOOST_INCLUDE_DIR}")
    message(STATUS "Boost include dir: ${DISCOPOP_BOOST_INCLUDE_DIR}")
endif()
# ─────────────────────────────────────────────────────────────────────────────

if(APPLE)
    # Homebrew's libomp is keg-only; probe its prefix so FindOpenMP can locate it.
    execute_process(
        COMMAND brew --prefix libomp
        OUTPUT_VARIABLE HOMEBREW_LIBOMP_PREFIX
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    if(HOMEBREW_LIBOMP_PREFIX)
        set(OpenMP_C_FLAGS   "-fopenmp -I${HOMEBREW_LIBOMP_PREFIX}/include")
        set(OpenMP_CXX_FLAGS "-fopenmp -I${HOMEBREW_LIBOMP_PREFIX}/include")
        set(OpenMP_C_LIB_NAMES   "omp")
        set(OpenMP_CXX_LIB_NAMES "omp")
        set(OpenMP_omp_LIBRARY   "${HOMEBREW_LIBOMP_PREFIX}/lib/libomp.dylib")
    endif()
endif()

find_package(OpenMP REQUIRED)

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

# ── Sanitizers ───────────────────────────────────────────────────────────────
# DP_SANITIZERS takes a value for -fsanitize=, e.g. "address,undefined" or
# "thread". The flags are added PUBLIC to the runtime library DiscoPoP_RT, so
# everything linking it (e.g. the unit tests DiscoPoP_UT) is instrumented and
# linked against the sanitizer runtime as well.
# The LLVM pass plugin LLVMDiscoPoP is NOT sanitized: it is dlopen'ed by an
# uninstrumented clang/opt, and the ASan/TSan runtimes must be part of the
# initial executable (they abort with "runtime does not come first" or miss
# allocations made by the host otherwise). Sanitizing the pass would need a
# sanitizer-built LLVM.
set(DP_SANITIZERS "" CACHE STRING "Sanitizers for the profiler runtime library and its unit tests, e.g. address,undefined or thread")
set(DP_SANITIZER_FLAGS "")
if(NOT "${DP_SANITIZERS}" STREQUAL "")
    if(DP_SANITIZERS MATCHES "thread" AND DP_SANITIZERS MATCHES "address|leak|memory")
        message(FATAL_ERROR "DP_SANITIZERS=${DP_SANITIZERS}: thread cannot be combined with address, leak or memory")
    endif()
    list(APPEND DP_SANITIZER_FLAGS "-fsanitize=${DP_SANITIZERS}" "-fno-omit-frame-pointer" "-g")
    if(DP_SANITIZERS MATCHES "undefined")
        # make UBSan findings fail the run instead of only printing them
        list(APPEND DP_SANITIZER_FLAGS "-fno-sanitize-recover=undefined")
    endif()
    message(STATUS "DiscoPoP configuration: DP_SANITIZERS=${DP_SANITIZERS} (runtime library and unit tests; the LLVM pass is not sanitized)")
endif()
# ─────────────────────────────────────────────────────────────────────────────


add_subdirectory(DiscoPoP)

add_subdirectory(rtlib)

add_subdirectory(scripts)
