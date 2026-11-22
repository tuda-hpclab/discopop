# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``--list-builds`` and ``--delete-builds`` of the project manager."""

import os
import sys
import time
from typing import List

from tabulate import tabulate  # type: ignore

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import delete_builds, list_builds
from discopop_library.ProjectManager.configurations.build_sharing import BuildSharingError, members_of, set_build_from
from discopop_library.ProjectManager.configurations.runs import disk_usage
from discopop_library.ProjectManager.services.build_overview import build_state_of, format_size


def show_builds(arguments: ProjectManagerArguments) -> None:
    records = list_builds(arguments.project_dir)
    if not records:
        print("No builds. A run of a configuration in a project copy (without --inplace) creates one.")
        return
    table: List[List[str]] = [
        ["Build", "Mode", "Suggestions", "Built", "Compile time", "Size", "Also used by", "State"]
    ]
    for record in records:
        table.append(
            [
                record.build_id,
                record.mode,
                ",".join(record.suggestions) or "-",
                time.strftime("%Y-%m-%d %H:%M", time.localtime(record.built_at)),
                "%.1f s" % record.compile_seconds,
                format_size(disk_usage(record.tree)) if os.path.isdir(record.tree) else "-",
                ", ".join(members_of(arguments.project_config_dir, record.configuration)) or "-",
                build_state_of(arguments, record),
            ]
        )
    print(tabulate(table, headers="firstrow", tablefmt="grid"))


def delete_builds_from_cli(arguments: ProjectManagerArguments) -> None:
    requested = (arguments.delete_builds or "all").strip()
    ids = None if requested == "all" else [name.strip() for name in requested.split(",") if name.strip()]
    known = {record.build_id for record in list_builds(arguments.project_dir)}
    for unknown in sorted(set(ids or []) - known):
        print("WARNING: no build named " + unknown + " (see --list-builds)")
    deleted = delete_builds(arguments, ids)
    print("Deleted " + str(len(deleted)) + " build(s)" + (": " + ", ".join(deleted) if deleted else "") + ".")


def change_build_sharing(arguments: ProjectManagerArguments) -> None:
    """``--share-build MEMBER:OWNER`` and ``--unshare-build MEMBER``."""
    config_dir = arguments.project_config_dir
    try:
        if arguments.share_build is not None:
            member, separator, owner = arguments.share_build.partition(":")
            if not separator or not member or not owner:
                print("ERROR: --share-build expects MEMBER:OWNER")
                sys.exit(1)
            set_build_from(config_dir, member, owner)
            print(member + " builds from " + owner + " now; its runs execute in the builds of " + owner + ".")
        if arguments.unshare_build is not None:
            set_build_from(config_dir, arguments.unshare_build, None)
            print(arguments.unshare_build + " builds for itself.")
    except BuildSharingError as error:
        print("ERROR: " + str(error))
        sys.exit(1)
