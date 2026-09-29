# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


def get_unique_pattern_id() -> int:
    with open("next_free_pattern_id.txt", "r") as f:
        pattern_id = int(f.read())
    with open("next_free_pattern_id.txt", "w") as f:
        f.write(str(pattern_id + 1))
    return pattern_id
