# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

message(STATUS "Found LLVM/Clang version " ${LLVM_VERSION})
if (NOT ${LLVM_VERSION} VERSION_EQUAL 11)
    message(WARNING "Make sure to use Clang 11")
endif ()

project(simple_alias_extraction)

find_package(Clang)

set(SOURCES
        main.cpp
        BinCallBack.hpp)

add_executable(getStatements ${SOURCES})

target_compile_options(getStatements PUBLIC
        -fno-rtti
        )

target_include_directories(getStatements PUBLIC
        ${CLANG_INCLUDE_DIRS}
        ${PROJECT_SOURCE_DIR}/include
        )

target_link_libraries(getStatements
        clangTooling
        )
