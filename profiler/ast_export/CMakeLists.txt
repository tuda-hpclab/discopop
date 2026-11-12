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
# the version of the LLVM that was found: Clang's package accepts nothing else (it needs the same major.minor)
find_package(Clang ${LLVM_PACKAGE_VERSION} CONFIG QUIET)
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
