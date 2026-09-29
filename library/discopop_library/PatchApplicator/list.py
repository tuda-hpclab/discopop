# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
from typing import List, cast

from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments


def list_applied_suggestions(arguments: PatchApplicatorArguments, applied_suggestions_file: str) -> List[str]:
    with open(applied_suggestions_file, "r") as f:
        applied_suggestions = json.loads(f.read())
        return cast(List[str], applied_suggestions["applied"])
