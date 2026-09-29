# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import re
import subprocess


def demangle_tag(tag: str, parent_logger: logging.Logger, cxxfilt_bin: str) -> str:
    logger = parent_logger.getChild("demangle_tag")

    # check if the tag contains any alphabetic character to suppress unnecessary calls to cxxfilt
    if re.search("[a-zA-Z]", tag) is None:
        # no alphabetic character. No demangling required
        return tag

    result = subprocess.run([cxxfilt_bin, tag], stdout=subprocess.PIPE)
    demangled_tag = result.stdout.decode("UTF-8")
    demangled_tag = demangled_tag.replace("\n", "")
    return demangled_tag
