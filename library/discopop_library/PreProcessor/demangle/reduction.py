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
from discopop_library.PreProcessor.PreProcessorArguments import PreProcessorArguments
from discopop_library.PreProcessor.demangle.utilities import demangle_tag


def demangle_reduction(arguments: PreProcessorArguments, parent_logger: logging.Logger, cxxfilt_bin: str) -> None:
    logger = parent_logger.getChild("reduction.txt")
    logger.info("Starting..")

    # check prerequisites
    reduction_path = os.path.join(os.getcwd(), "profiler", "reduction.txt")
    if not os.path.exists(reduction_path):
        raise FileNotFoundError(reduction_path)

    processed_reduction_path = os.path.join(os.getcwd(), "profiler", "reduction.txt.processed")

    line_count = 0
    with open(reduction_path, "r") as f:
        for line in f.readlines():
            line_count += 1

    if os.path.exists(processed_reduction_path):
        os.remove(processed_reduction_path)

    with open(processed_reduction_path, "w+") as of:
        with open(reduction_path, "r") as f:
            for idx, line in enumerate(f.readlines()):
                if idx % 100 == 0:
                    logger.info("Progress: " + str(round((idx / line_count) * 100, 2)) + "%")
                line = line.replace("\n", "")
                orig_line = line

                tags = line.split(" ")
                demangled_tags = []
                for tag in tags:
                    # reduce calls to llvm-cxxfilt
                    call_required = True
                    if tag in ["FileID", "Line", "Number", "Operation", "Name", "Reduction", "Variable"]:
                        call_required = False

                    if call_required:
                        if tag.startswith("GEPRESULT_"):
                            demangled_tags.append(
                                "GEPRESULT_" + demangle_tag(tag.replace("GEPRESULT_", ""), logger, cxxfilt_bin)
                            )
                        else:
                            demangled_tags.append(demangle_tag(tag, logger, cxxfilt_bin))
                    else:
                        demangled_tags.append(tag)

                line = " ".join(demangled_tags)

                if len(orig_line) != len(line):
                    logger.debug("line " + str(idx) + " : " + orig_line)
                    logger.debug("line " + str(idx) + " : " + line)
                    logger.debug("")

                of.write(line + "\n")

    # overwrite reduction.txt
    os.remove(reduction_path)
    os.rename(processed_reduction_path, reduction_path)

    logger.info("Done.")
