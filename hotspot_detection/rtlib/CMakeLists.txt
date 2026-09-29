# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Runtime library sources and build flags.
set(HotspotDetection_SOURCES
        rtlib.c
)

add_library(HotspotDetection_RT STATIC
        ${HotspotDetection_SOURCES})
install(TARGETS HotspotDetection_RT ARCHIVE DESTINATION discopop-hotspot-detection.libs)
