# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import re

# checks the commit message for correct formatting.
# invoked by the git commit-msg hook, if configured.
import sys

# todo translate to python

path_to_commit_msg = sys.argv[1]

with open(path_to_commit_msg, "r") as f:
    commit_msg = f.read()
    commit_msg = commit_msg.replace("\n", "")

pattern = re.compile(
    "(^(feat|fix|test|chore|update|refactor|doc|docs|perf|wip|ci|build|style)(\(.+\))?(\[.+\])?:.+$)|(Merge \S* ?branch '\S+' into \S+)|(Revert .+)"
)
matches = bool(pattern.match(commit_msg))

if matches:
    print("VALID commit message: ", commit_msg)
    sys.exit(0)
else:
    print("INVALID commit message: ")
    print("\t", commit_msg)
    print("Please use the following format:")
    print("\t<type>(scope)[optional info]: commit message")
    print("where `<type>` can be any of `feat,fix,test,chore,update,wip,refactor,doc,docs,perf,ci,build,style`.")
    sys.exit(1)
