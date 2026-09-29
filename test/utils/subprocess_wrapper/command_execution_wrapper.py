import subprocess
from typing import Dict, Tuple


def run_cmd(cmd: str, cwd: str, env: Dict[str, str]) -> None:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        executable="/bin/bash",
        shell=True,
        env=env,
        capture_output=True,
    )
    # print(result.stdout.decode("utf-8"))
    if result.returncode != 0:
        raise ValueError(
            "Error during subprocess call. \nCALL: "
            + cmd
            + "\nCWD: "
            + cwd
            + "\nCODE: "
            + str(result.returncode)
            + "\nSTDOUT:\n"
            + str(result.stdout.decode("utf-8"))
            + "\nSTDERR:\n"
            + str(result.stderr.decode("utf-8"))
        )
