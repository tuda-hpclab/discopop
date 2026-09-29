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


def demangle_data_xml(arguments: PreProcessorArguments, parent_logger: logging.Logger, cxxfilt_bin: str) -> None:
    logger = parent_logger.getChild("Data.xml")
    logger.info("Starting..")

    # check prerequisites
    data_xml_path = os.path.join(os.getcwd(), "profiler", "Data.xml")
    if not os.path.exists(data_xml_path):
        raise FileNotFoundError(data_xml_path)

    processed_data_xml_path = os.path.join(os.getcwd(), "profiler", "Data.xml.processed")

    line_count = 0
    with open(data_xml_path, "r") as f:
        for line in f.readlines():
            line_count += 1

    if os.path.exists(processed_data_xml_path):
        os.remove(processed_data_xml_path)

    with open(processed_data_xml_path, "w+") as of:
        with open(data_xml_path, "r") as f:
            for idx, line in enumerate(f.readlines()):
                if idx % 1000 == 0:
                    logger.info("Progress: " + str(round((idx / line_count) * 100, 2)) + "%")
                line = line.replace("\n", "")
                orig_line = line
                # match name:  "name\=\"\S+\""
                name_matches = re.findall(r"name\=\"\S+\"", line)
                for name_match in name_matches:
                    name = name_match[6:-1]
                    name_demangled = demangle_tag(name, logger, cxxfilt_bin)
                    if "(" in name_demangled:
                        # function call found. remove arguments
                        name_cleaned = name_demangled[: name_demangled.index("(")]
                        name_demangled = name_cleaned
                    line = line.replace(name_match, 'name="' + name_demangled + '"')

                # match >...< : "\>\S+\<"
                tag_matches = re.findall(r"\>\S+\<", line)
                for tag_match in tag_matches:
                    tag = tag_match[1:-1]
                    tag_demangled = demangle_tag(tag, logger, cxxfilt_bin)

                    line = line.replace(tag_match, ">" + tag_demangled + "<")

                if len(orig_line) != len(line):
                    logger.debug("line " + str(idx) + " : " + orig_line)
                    logger.debug("line " + str(idx) + " : " + line)
                    logger.debug("")

                of.write(line + "\n")

    # overwrite Data.xml
    os.remove(data_xml_path)
    os.rename(processed_data_xml_path, data_xml_path)

    logger.info("Done.")
