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


def demangle_dependency_metadata(
    arguments: PreProcessorArguments, parent_logger: logging.Logger, cxxfilt_bin: str
) -> None:
    logger = parent_logger.getChild("dependency_metadata.txt")
    logger.info("Starting..")

    # check prerequisites
    dependency_metadata_path = os.path.join(os.getcwd(), "profiler", "dependency_metadata.txt")
    if not os.path.exists(dependency_metadata_path):
        raise FileNotFoundError(dependency_metadata_path)

    processed_dependency_metadata_path = os.path.join(os.getcwd(), "profiler", "dependency_metadata.txt.processed")

    line_count = 0
    with open(dependency_metadata_path, "r") as f:
        for line in f.readlines():
            line_count += 1

    if os.path.exists(processed_dependency_metadata_path):
        os.remove(processed_dependency_metadata_path)

    with open(processed_dependency_metadata_path, "w+") as of:
        with open(dependency_metadata_path, "r") as f:
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
                    if (
                        tag in ["RAW", "WAR", "WAW"]
                        or tag.startswith("IEC[")
                        or tag.startswith("IEI[")
                        or tag.startswith("IAC[")
                        or tag.startswith("IAI[")
                        or tag.startswith("SINK_ANC[")
                        or tag.startswith("SOURCE_ANC[")
                    ):
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

    # overwrite dependency_metadata.txt
    os.remove(dependency_metadata_path)
    os.rename(processed_dependency_metadata_path, dependency_metadata_path)

    logger.info("Done.")
