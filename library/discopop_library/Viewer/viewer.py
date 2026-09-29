# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path

from discopop_library.Viewer.ViewerArguments import ViewerArguments
from discopop_library.Viewer.suggestions_view import print_suggestions_overview
from discopop_library.global_data.version.utils import get_version
import shutil
import logging

logger = logging.getLogger("Viewer")


def run(arguments: ViewerArguments) -> None:
    logger.info("DiscoPoP Viewer: ")
    for arg in arguments.__dict__:
        logger.info("-> " + str(arg) + ": " + str(arguments.__dict__[arg]))

    if arguments.print_suggestions_overview:
        print_suggestions_overview(arguments)
