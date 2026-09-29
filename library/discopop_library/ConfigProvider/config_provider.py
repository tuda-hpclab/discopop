# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path
from discopop_library.ConfigProvider.ConfigProviderArguments import ConfigProviderArguments
from discopop_library.global_data.version.utils import get_version
import shutil


def run(arguments: ConfigProviderArguments) -> str:
    """Returns the contents of the written build_config.txt"""

    if arguments.return_dp_build_dir:
        found_final = False
        executable = str(shutil.which("discopop_cc"))
        while not found_final:
            try:
                tmp = str(os.readlink(executable))
                executable = tmp
            except:
                found_final = True
        return str(Path(executable).parent.parent.absolute())
        # return str(Path(str(os.readlink(executable))).parent.parent.absolute())
    elif arguments.return_llvm_bin_dir:
        for _v in [22, 21, 20, 19]:
            clang = shutil.which(f"clang-{_v}")
            if clang:
                return str(Path(clang).parent.absolute())
        raise RuntimeError("No supported clang version (19-22) found in PATH")
    elif arguments.return_full_config:
        ret_str = ""
        assets_path = os.path.join(Path(__file__).parent.absolute(), "assets", "build_config.py")
        with open(assets_path, "r") as f:
            for line in f.readlines():
                ret_str += line
        # remove trailing \n
        if ret_str[-1] == "\n":
            ret_str = ret_str[:-1]
        return ret_str
    elif arguments.return_version_string:
        return get_version()
    else:
        raise ValueError("No valid operation for execution configuration: \n" + str(arguments))
