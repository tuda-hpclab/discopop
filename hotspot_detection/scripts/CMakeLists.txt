# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

install(PROGRAMS
    ${CMAKE_CURRENT_SOURCE_DIR}/CC_wrapper.sh
    ${CMAKE_CURRENT_SOURCE_DIR}/CXX_wrapper.sh
    ${CMAKE_CURRENT_SOURCE_DIR}/CMAKE_wrapper.sh
    ${CMAKE_CURRENT_SOURCE_DIR}/LINKER_wrapper.sh
    ${CMAKE_CURRENT_SOURCE_DIR}/runHotspotDetection
    DESTINATION discopop-hotspot-detection.libs
)
