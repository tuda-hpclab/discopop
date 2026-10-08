# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


#CMAKE_CURRENT_SOURCE_DIR = "$1"
#CMAKE_CURRENT_BINARY_DIR = "$2"

mkdir $2/simple-alias-detection
cd $2/simple-alias-detection
cmake $1/simple-alias-detection
make
