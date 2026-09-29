# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


# setup DiscoPoP venv
if(NOT ${USE_VENV} STREQUAL "")
    message(STATUS "Setting up existing python venv: ${USE_VENV}")
    set(Python3_VENV_EXECUTABLE ${USE_VENV}/bin/python3)
    set(Python3_VENV_BIN_PATH ${USE_VENV}/bin)
else()
    message(STATUS "Setting up default DiscoPoP python venv: ${DiscoPoP_SOURCE_DIR}/venv")
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -m venv ${DiscoPoP_SOURCE_DIR}/venv
    )
    set(Python3_VENV_EXECUTABLE ${DiscoPoP_SOURCE_DIR}/venv/bin/python3)
    set(Python3_VENV_BIN_PATH ${DiscoPoP_SOURCE_DIR}/venv/bin)
endif()

if(NOT ${IS_DEB_INSTALL} STREQUAL "")
    # create symlinks to files
    message(STATUS "performing installation from .deb package")
else()
    # create symlinks to files
    set(DP_LOCAL_BIN_DIR "$ENV{HOME}/.local/bin")
    if(EXISTS ${Python3_VENV_BIN_PATH})
        # These wrapper scripts are only produced by `cmake --install` of this
        # (top-level, unit-test-only) build tree, which nothing in the documented
        # build/CI flow ever runs. Only (re-)point discopop_cc/cxx/cmake at them
        # if they actually exist here — otherwise leave whatever `pip install
        # ./profiler` already placed in the venv (the supported install path)
        # alone, instead of replacing a working script with a dangling symlink.
        if(EXISTS ${CMAKE_CURRENT_BINARY_DIR}/CC_wrapper.sh)
            execute_process(COMMAND rm -f ${Python3_VENV_BIN_PATH}/discopop_cc)
            message(STATUS "Creating symlink ${Python3_VENV_BIN_PATH}/discopop_cc to ${CMAKE_CURRENT_BINARY_DIR}/CC_wrapper.sh")
            execute_process(COMMAND ln -sf ${CMAKE_CURRENT_BINARY_DIR}/CC_wrapper.sh ${Python3_VENV_BIN_PATH}/discopop_cc)
        endif()

        if(EXISTS ${CMAKE_CURRENT_BINARY_DIR}/CXX_wrapper.sh)
            execute_process(COMMAND rm -f ${Python3_VENV_BIN_PATH}/discopop_cxx)
            message(STATUS "Creating symlink ${Python3_VENV_BIN_PATH}/discopop_cxx to ${CMAKE_CURRENT_BINARY_DIR}/CXX_wrapper.sh")
            execute_process(COMMAND ln -sf ${CMAKE_CURRENT_BINARY_DIR}/CXX_wrapper.sh ${Python3_VENV_BIN_PATH}/discopop_cxx)
        endif()

        if(EXISTS ${CMAKE_CURRENT_BINARY_DIR}/CMAKE_wrapper.sh)
            execute_process(COMMAND rm -f ${Python3_VENV_BIN_PATH}/discopop_cmake)
            message(STATUS "Creating symlink ${Python3_VENV_BIN_PATH}/discopop_cmake to ${CMAKE_CURRENT_BINARY_DIR}/CMAKE_wrapper.sh")
            execute_process(COMMAND ln -sf ${CMAKE_CURRENT_BINARY_DIR}/CMAKE_wrapper.sh ${Python3_VENV_BIN_PATH}/discopop_cmake)
        endif()
    else()
        message(WARNING "Creation of symlinks discopop_cc to ${CMAKE_CURRENT_BINARY_DIR}/CC_wrapper.sh not possible. Please create it manually.")
        message(WARNING "Creation of symlinks discopop_cxx to ${CMAKE_CURRENT_BINARY_DIR}/CXX_wrapper.sh not possible. Please create it manually.")
        message(WARNING "Creation of symlinks discopop_cmake to ${CMAKE_CURRENT_BINARY_DIR}/CMAKE_wrapper.sh not possible. Please create it manually.")
    endif()
endif()
