# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

add_llvm_library(LLVMHotspotDetection MODULE
        HotspotDetection.cpp
)

install(TARGETS LLVMHotspotDetection LIBRARY DESTINATION discopop-hotspot-detection.libs)
