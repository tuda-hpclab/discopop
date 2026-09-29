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
from typing import List
from discopop_library.PreProcessor.PreProcessorArguments import PreProcessorArguments
from discopop_library.PreProcessor.demangle.utilities import demangle_tag


def demangle_static_dependencies(
    arguments: PreProcessorArguments, parent_logger: logging.Logger, cxxfilt_bin: str
) -> None:
    logger = parent_logger.getChild("static_dependencies.txt")
    logger.info("Starting..")

    # check prerequisites
    static_dependencies_path = os.path.join(os.getcwd(), "profiler", "static_dependencies.txt")
    if not os.path.exists(static_dependencies_path):
        raise FileNotFoundError(static_dependencies_path)

    processed_static_dependencies_path = os.path.join(os.getcwd(), "profiler", "static_dependencies.txt.processed")

    line_count = 0
    with open(static_dependencies_path, "r") as f:
        for line in f.readlines():
            line_count += 1

    if os.path.exists(processed_static_dependencies_path):
        os.remove(processed_static_dependencies_path)

    with open(processed_static_dependencies_path, "w+") as of:
        with open(static_dependencies_path, "r") as f:
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
                    if tag in ["RAW", "WAR", "WAW", "NOM", "INIT", "END", "BGN"]:
                        call_required = False

                    if call_required:
                        sub_tags = unpack(tag)
                        demangled_sub_tags = []

                        for sub_tag in sub_tags:

                            if sub_tag.startswith("GEPRESULT_"):
                                demangled_sub_tags.append(
                                    "GEPRESULT_" + demangle_tag(sub_tag.replace("GEPRESULT_", ""), logger, cxxfilt_bin)
                                )
                            else:
                                demangled_sub_tags.append(demangle_tag(sub_tag, logger, cxxfilt_bin))

                        demangled_tags.append(pack(demangled_sub_tags))

                    else:
                        demangled_tags.append(tag)

                line = " ".join(demangled_tags)

                if len(orig_line) != len(line):
                    logger.debug("line " + str(idx) + " : " + orig_line)
                    logger.debug("line " + str(idx) + " : " + line)
                    logger.debug("")

                of.write(line + "\n")

    # overwrite static_dependencies.txt
    os.remove(static_dependencies_path)
    os.rename(processed_static_dependencies_path, static_dependencies_path)

    logger.info("Done.")


def unpack(tag: str) -> List[str]:
    # example: 1:2390|_ZL4tmp1(_ZL4tmp1)  --> returns ("1:2390", "_ZL4tmp1", "_ZL4tmp1")
    if "|" in tag:
        first = tag[: tag.index("|")]
        tag = tag[tag.index("|") + 1 :]
        if "(" in tag:
            second = tag[: tag.index("(")]
            third = tag[tag.index("(") + 1 : -1]
            return [first, second, third]
        else:
            second = tag
            return [first, second]
    else:
        return [tag]


def pack(sub_tags: List[str]) -> str:
    # example: ("1:2390", "_ZL4tmp1", "_ZL4tmp1") returns: "1:2390|_ZL4tmp1(_ZL4tmp1)"
    if len(sub_tags) == 1:
        return sub_tags[0]
    if len(sub_tags) == 2:
        return sub_tags[0] + "|" + sub_tags[1]
    if len(sub_tags) == 3:
        return sub_tags[0] + "|" + sub_tags[1] + "(" + sub_tags[2] + ")"
    raise ValueError("Invalid length: " + str(len(sub_tags)))
