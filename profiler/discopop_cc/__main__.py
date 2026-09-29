# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import subprocess
import sys
from pathlib import Path


def main() -> int:
    site_packages = Path(__file__).parent.parent
    libs_dir = site_packages / "discopop-profiler.libs"
    cc_wrapper = libs_dir / "CC_wrapper.sh"
    cmd = [cc_wrapper] + sys.argv[1:]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
