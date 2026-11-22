# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Optional: the Clang plugin that writes the AST of the instrumented files only (see ast_export.cpp). It needs the
# development files of Clang (libclang-<version>-dev, ...), which the rest of the profiler does not. Without them, the
# wrappers fall back to filtering clang's complete AST dump.
set(DP_AST_EXPORT "ON" CACHE STRING "Build the AST export plugin if the Clang development files are found (ON, OFF, REQUIRED)")

if(DP_AST_EXPORT STREQUAL "OFF")
    message(STATUS "AST export plugin: disabled (DP_AST_EXPORT=OFF)")
    return()
endif()

# the version is tied to the plugin's name below, so a plugin is only ever loaded by the clang it was built for
# Clang's CMake package lies next to LLVM's (<prefix>/lib/cmake/llvm and <prefix>/lib/cmake/clang); CMake does not look
# into a hinted directory itself, only into prefixes
if(NOT Clang_DIR AND EXISTS "${LLVM_DIR}/../clang/ClangConfig.cmake")
    get_filename_component(_dp_clang_dir "${LLVM_DIR}/../clang" ABSOLUTE)
    # FORCE: an earlier failed search leaves Clang_DIR-NOTFOUND in the cache, which a plain set() does not replace
    set(Clang_DIR "${_dp_clang_dir}" CACHE PATH "Directory of ClangConfig.cmake" FORCE)
endif()
# Clang's package can be installed without the libraries and headers it imports: apt.llvm.org ships ClangConfig.cmake
# with the package clang-<version>, the libraries with libclang-<version>-dev. Its ClangTargets.cmake then stops the
# configuration with a fatal error (QUIET or not), so the package is first loaded by a CMake run of its own, which may
# fail. Only if it succeeds, the package is loaded here.
set(_dp_clang_probe_dir "${CMAKE_CURRENT_BINARY_DIR}/clang_package_probe")
file(WRITE "${_dp_clang_probe_dir}/CMakeLists.txt"
    "cmake_minimum_required(VERSION ${CMAKE_MINIMUM_REQUIRED_VERSION})\n"
    "project(DiscoPoP_ClangPackageProbe NONE)\n"
    "find_package(Clang \"${LLVM_PACKAGE_VERSION}\" CONFIG REQUIRED)\n")
set(_dp_clang_probe_args "-DLLVM_DIR=${LLVM_DIR}")
if(Clang_DIR)
    list(APPEND _dp_clang_probe_args "-DClang_DIR=${Clang_DIR}")
endif()
if(CMAKE_PREFIX_PATH)
    list(JOIN CMAKE_PREFIX_PATH "\\;" _dp_prefix_path)
    list(APPEND _dp_clang_probe_args "-DCMAKE_PREFIX_PATH=${_dp_prefix_path}")
endif()
execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${_dp_clang_probe_dir}" -B "${_dp_clang_probe_dir}/build" -G "${CMAKE_GENERATOR}"
            "-DCMAKE_MAKE_PROGRAM=${CMAKE_MAKE_PROGRAM}" ${_dp_clang_probe_args}
    RESULT_VARIABLE _dp_clang_probe_result
    OUTPUT_QUIET
    ERROR_VARIABLE _dp_clang_probe_error)
if(_dp_clang_probe_result EQUAL 0)
    # the version of the LLVM that was found: Clang's package accepts nothing else (it needs the same major.minor)
    find_package(Clang ${LLVM_PACKAGE_VERSION} CONFIG QUIET)
elseif(_dp_clang_probe_error MATCHES "references the file[ \t\r\n]+\"([^\"]+)\"")
    message(STATUS "AST export plugin: Clang's CMake package is installed, but not the files it references (e.g. "
                   "${CMAKE_MATCH_1}; Debian/Ubuntu: libclang-${LLVM_MAJOR_VERSION}-dev)")
endif()
if(Clang_FOUND)
    find_path(DP_CLANG_JSON_HEADER_DIR clang/AST/JSONNodeDumper.h PATHS ${CLANG_INCLUDE_DIRS} ${LLVM_INCLUDE_DIRS} NO_DEFAULT_PATH)
endif()
if(NOT Clang_FOUND OR NOT DP_CLANG_JSON_HEADER_DIR)
    if(DP_AST_EXPORT STREQUAL "REQUIRED")
        message(FATAL_ERROR "DP_AST_EXPORT=REQUIRED, but the Clang ${LLVM_MAJOR_VERSION} development files were not found")
    endif()
    message(STATUS "AST export plugin: not built, the Clang ${LLVM_MAJOR_VERSION} development files were not found "
                   "(the wrappers filter clang's AST dump instead)")
    return()
endif()

add_library(DiscoPoP_ASTExport MODULE ast_export.cpp)
set_target_properties(DiscoPoP_ASTExport PROPERTIES
    PREFIX ""
    OUTPUT_NAME "DiscoPoPASTExport-${LLVM_MAJOR_VERSION}"
    SUFFIX ".so"
    POSITION_INDEPENDENT_CODE ON)
target_include_directories(DiscoPoP_ASTExport SYSTEM PRIVATE ${CLANG_INCLUDE_DIRS} ${DP_CLANG_JSON_HEADER_DIR})
target_link_libraries(DiscoPoP_ASTExport PRIVATE DiscoPoP_LLVM DiscoPoP_Warnings)
# the plugin is loaded into clang, which provides the symbols of Clang and LLVM
target_link_options(DiscoPoP_ASTExport PRIVATE $<$<PLATFORM_ID:Darwin>:-undefined dynamic_lookup>)

install(TARGETS DiscoPoP_ASTExport LIBRARY DESTINATION discopop-profiler.libs)
message(STATUS "AST export plugin: DiscoPoPASTExport-${LLVM_MAJOR_VERSION}.so")
