# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from posixpath import abspath, dirname
from typing import Dict, cast
from discopop_explorer.utilities.PEGraphConstruction.classes.DependenceItem import DependenceItem
from discopop_explorer.utilities.PEGraphConstruction.parser import __parse_dep_file
from discopop_library.DependencyComparator.DependencyComparatorArguments import DependencyComparatorArguments
from discopop_library.global_data.version.utils import get_version


def run(arguments: DependencyComparatorArguments) -> int:

    if not os.path.exists(arguments.gold_standard_dynamic):
        raise FileNotFoundError(arguments.gold_standard_dynamic)
    if not os.path.exists(arguments.gold_standard_static):
        raise FileNotFoundError(arguments.gold_standard_static)
    if not os.path.exists(arguments.test_set_dynamic):
        raise FileNotFoundError(arguments.test_set_dynamic)
    if not os.path.exists(arguments.test_set_static):
        raise FileNotFoundError(arguments.test_set_static)
    output_results: bool = True
    if arguments.output == "None" or arguments.output is None:
        output_results = False

    if os.path.exists(arguments.output):
        os.remove(arguments.output)

    # read gold standard
    with open(arguments.gold_standard_dynamic, "r") as f:
        parsed_gold_standard_dynamic = __parse_dep_file(f, dirname(abspath(arguments.gold_standard_dynamic)))[0]
    with open(arguments.gold_standard_static, "r") as f:
        parsed_gold_standard_static = __parse_dep_file(f, dirname(abspath(arguments.gold_standard_static)))[0]

    # read test_set
    with open(arguments.test_set_dynamic, "r") as f:
        parsed_test_set_dynamic = __parse_dep_file(f, dirname(abspath(arguments.test_set_dynamic)))[0]
    with open(arguments.test_set_dynamic, "r") as f:
        parsed_test_set_static = __parse_dep_file(f, dirname(abspath(arguments.test_set_static)))[0]

    overlap = []
    missing = []
    missing_init = []
    additional = []
    additional_init = []

    for dep in parsed_gold_standard_dynamic + parsed_gold_standard_static:
        found = False
        for dep_2 in parsed_test_set_dynamic + parsed_test_set_static:
            if dep_equal(dep, arguments.gold_standard_dynamic, dep_2, arguments.test_set_dynamic):
                overlap.append(dep)
                found = True
                break
        if found:
            continue
        if dep.type == "INIT":
            missing_init.append(dep)
        else:
            missing.append(dep)

    for dep in parsed_test_set_dynamic + parsed_test_set_static:
        found = False
        for dep_2 in parsed_gold_standard_dynamic + parsed_gold_standard_static:
            if dep_equal(dep, arguments.test_set_dynamic, dep_2, arguments.gold_standard_dynamic):
                found = True
                break
        if found:
            continue
        if dep.type == "INIT":
            additional_init.append(dep)
        else:
            additional.append(dep)

    result_dir = {
        "overlap": len(overlap),
        "missing": len(missing),
        "missing_init": len(missing_init),
        "additional_init": len(additional_init),
        "additional": len(additional),
    }

    if arguments.verbose:
        if len(missing) > 0:
            print("MISSING: ")
            for miss in missing:
                print("-> ", miss)
            print()

        if len(missing_init) > 0:
            print("MISSING_INIT: ")
            for missi in missing_init:
                print("-> ", missi)
            print()

        if len(additional) > 0:
            print("ADDITIONAL: ")
            for add in additional:
                print("-> ", add)
            print()

        if len(additional_init) > 0:
            print("ADDITIONAL INIT: ")
            for addi in additional_init:
                print("-> ", addi)
            print()

        print("overlap: ", len(overlap))
        print("missing: ", len(missing))
        print("missing_init: ", len(missing_init))
        print("additional: ", len(additional))
        print("additional init: ", len(additional_init))

    if output_results:
        with open(arguments.output, "w+") as f:
            json.dump(result_dir, f)

    # identify return value
    return_code = 0
    if len(missing) > 0:
        return_code += 100
    if len(additional) > 0:
        return_code += 1
    if len(additional_init) > 0:
        return_code += 1

    return return_code


def get_instructionID_to_lineID_mapping(project_folder: Path) -> Dict[str, str]:
    # read instructionID to lineID mapping
    mappings_dict: Dict[str, str] = {"*": "*"}  # {instructionID: lineID}}
    mappings_file = os.path.join(project_folder, "profiler", "instructionID_to_lineID_mapping.txt")
    if os.path.exists(mappings_file):
        with open(mappings_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or len(line) == 0:
                    continue
                line_split = [elem for elem in line.split(" ") if len(elem) > 0]
                instruction_id = line_split[0]
                line_id = line_split[1]
                if line_id.startswith("*"):
                    continue
                line_id_split = line_id.split(":")
                file_id = line_id_split[0]
                line_num = line_id_split[1]
                column_num = line_id_split[2]
                mappings_dict[instruction_id] = str(file_id) + ":" + str(line_num)
    return mappings_dict


def dep_equal(a: DependenceItem, a_dep_file: str, b: DependenceItem, b_dep_file: str) -> bool:
    # ensure correct equality check in case of different profiler versions (legacy vs. instruction-based)
    a_source_legacy = ":" in a.source
    a_sink_legacy = ":" in a.sink
    b_source_legacy = ":" in b.source
    b_sink_legacy = ":" in b.sink

    # strip state from instruction-based locations
    if "@" in a.source:
        a.source = a.source.split("@")[0]
    if "@" in b.source:
        b.source = b.source.split("@")[0]
    if "@" in a.sink:
        a.sink = a.sink.split("@")[0]
    if "@" in b.sink:
        b.sink = b.sink.split("@")[0]

    # convert location "0" to "*" if conversion to legacy representation is required
    #    if a_source_legacy and not b_source_legacy:
    #        if b.source == "0":
    #            b.source = "*"
    #    if b_source_legacy and not a_source_legacy:
    #        if a.source == "0":
    #            a.source = "*"
    #    if a_sink_legacy and not b_sink_legacy:
    #        if a.sink == "0":
    #            a.sink = "*"
    #    if b_sink_legacy and not a_sink_legacy:
    #        if b.sink == "0":
    #            b.sink = "*"

    # check var name
    if a.var_name != b.var_name:
        return False
    # check type
    if a.type != b.type:
        return False

    # check source equality. convert instruction based to legacy representation if necessary.
    if a_source_legacy and b_source_legacy:
        if a.source != b.source:
            return False
    elif a_source_legacy and not b_source_legacy:

        # compare a.source with converted b.source
        instruction_id_mappings = get_instructionID_to_lineID_mapping(Path(str(b_dep_file)).parent.parent)
        if a.source != instruction_id_mappings[b.source]:
            return False
    elif not a_source_legacy and b_source_legacy:
        # compare a.source with converted b.source
        instruction_id_mappings = get_instructionID_to_lineID_mapping(Path(str(a_dep_file)).parent.parent)
        if instruction_id_mappings[a.source] != b.source:
            return False
    else:
        # both are instruction-based
        if a.source != b.source:
            return False

    # check sink equality
    if a_sink_legacy and b_sink_legacy:
        if a.sink != b.sink:
            return False
    elif a_sink_legacy and not b_sink_legacy:
        # compare a.sink with converted b.sink
        instruction_id_mappings = get_instructionID_to_lineID_mapping(Path(str(b_dep_file)).parent.parent)
        if a.sink != instruction_id_mappings[b.sink]:
            return False
    elif not a_sink_legacy and b_sink_legacy:
        # compare a.sink with converted b.sink
        instruction_id_mappings = get_instructionID_to_lineID_mapping(Path(str(a_dep_file)).parent.parent)
        if instruction_id_mappings[a.sink] != b.sink:
            return False
    else:
        # both are instruction-based
        if a.sink != b.sink:
            return False
    return True
