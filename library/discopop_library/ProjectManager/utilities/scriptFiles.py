# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os

PATH = str


def write_script_file(path: PATH, content: str, ensure_shebang: bool = True, make_executable: bool = True) -> None:
    """Writes a shell script to `path`, optionally prepending a #!/bin/bash shebang and marking it executable."""
    if ensure_shebang and not content.lstrip().startswith("#!"):
        content = "#!/bin/bash\n" + content

    with open(path, "w") as f:
        f.write(content)

    if make_executable:
        os.chmod(path, os.stat(path).st_mode | 0o111)
